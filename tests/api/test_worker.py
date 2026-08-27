from __future__ import annotations

import io
import json
import wave
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select

from meeting_api.models import Meeting, Person, SpeakerCluster, TranscriptSegment, Voiceprint
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend
from meeting_api.pipeline.diarization import FakeDiarizationBackend, SpeakerSegment
from meeting_api.pipeline.embedding import FakeEmbeddingBackend, embedding_to_bytes
from meeting_api.pipeline.serial import SingleModelSlot
from meeting_api.worker import Worker


def _queue_meeting(client, title: str = "待处理会议", expected_speakers: int = 2) -> str:
    created = client.post(
        "/api/meetings",
        json={"title": title, "expected_speakers": expected_speakers},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    return meeting_id


def _queue_meeting_with_real_wav(
    client,
    seconds: float = 20.0,
    title: str = "真 wav 会议",
    expected_speakers: int = 2,
) -> str:
    created = client.post(
        "/api/meetings", json={"title": title, "expected_speakers": expected_speakers}
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * int(16000 * seconds))
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", buffer.getvalue(), "audio/wav")},
    )
    assert uploaded.status_code == 200
    return meeting_id


def _worker(client, **overrides) -> Worker:
    options = {
        "session_factory": client.app.state.session_factory,
        "settings": client.app.state.settings,
    }
    options.update(overrides)
    return Worker(**options)


def _seed_s1_voiceprint(client) -> None:
    backend = FakeEmbeddingBackend()
    with SingleModelSlot().use(backend) as loaded:
        embedding = embedding_to_bytes(loaded.embed(Path("unused.wav"), "S1"))
    with client.app.state.session_factory() as session:
        session.add(Person(id="fake-person-1", display_name="已知用户 1"))
        session.add(Voiceprint(person_id="fake-person-1", embedding=embedding))
        session.commit()


def test_process_next_synchronously_advances_uploaded_meeting_to_review(client):
    meeting_id = _queue_meeting(client)

    _worker(client).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.status_code == 200
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"


def test_process_next_persists_transcript_and_speaker_review_artifacts(client):
    meeting_id = _queue_meeting(client)

    _worker(client).process_next()

    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()

    assert segments
    assert all(segment.start_seconds < segment.end_seconds for segment in segments)
    assert all(segment.text for segment in segments)
    assert {segment.cluster_id for segment in segments} == {"S1", "S2"}

    assert [cluster.cluster_id for cluster in clusters] == ["S1", "S2"]
    for cluster in clusters:
        samples = json.loads(cluster.sample_clips_json)
        assert 2 <= len(samples) <= 3
        assert all(sample["start_seconds"] < sample["end_seconds"] for sample in samples)
    # M10：声纹库为空时不得再凭簇 id 硬编码建议身份。
    assert clusters[0].suggested_person_id is None
    assert clusters[1].suggested_person_id is None


def test_process_next_reaches_review_with_more_expected_speakers(client):
    # 回归：expected_speakers>2 时 fake 切分也要给每簇留足 2–3 个试听片段，
    # 不能让合法输入直接 FAILED。
    meeting_id = _queue_meeting(client, "四人会", expected_speakers=4)

    _worker(client).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    with client.app.state.session_factory() as session:
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
    assert {cluster.cluster_id for cluster in clusters} == {"S1", "S2", "S3", "S4"}
    for cluster in clusters:
        assert 2 <= len(json.loads(cluster.sample_clips_json)) <= 3


def test_process_next_only_handles_one_of_two_queued_meetings(client):
    first_id = _queue_meeting(client, "第一场")
    second_id = _queue_meeting(client, "第二场")

    _worker(client).process_next()

    with client.app.state.session_factory() as session:
        states = {
            meeting_id: session.get(Meeting, meeting_id).state
            for meeting_id in (first_id, second_id)
        }
    assert sorted(states.values()) == ["AWAITING_SPEAKER_REVIEW", "QUEUED"]


class ProbeSlot(SingleModelSlot):
    def __init__(self) -> None:
        super().__init__()
        self.used_backends: list[str] = []

    @contextmanager
    def use(self, backend):
        self.used_backends.append(backend.name)
        with super().use(backend) as loaded:
            yield loaded


class ProbeAsr(FakeAsrBackend):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.other: FakeDiarizationBackend | None = None

    def load(self) -> None:
        assert self.other is not None and not self.other.loaded
        self.events.append("asr:load")
        super().load()

    def unload(self) -> None:
        self.events.append("asr:unload")
        super().unload()


class ProbeDiarization(FakeDiarizationBackend):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.other: FakeAsrBackend | None = None

    def load(self) -> None:
        assert self.other is not None and not self.other.loaded
        self.events.append("diarization:load")
        super().load()

    def unload(self) -> None:
        self.events.append("diarization:unload")
        super().unload()


def test_models_use_single_slot_and_are_never_loaded_together(client):
    _queue_meeting(client)
    _seed_s1_voiceprint(client)
    events: list[str] = []
    asr = ProbeAsr(events)
    diarization = ProbeDiarization(events)
    asr.other = diarization
    diarization.other = asr
    slot = ProbeSlot()

    _worker(
        client,
        asr_backend=asr,
        diarization_backend=diarization,
        model_slot=slot,
    ).process_next()

    assert slot.used_backends == ["fake-asr", "fake-diarization", "fake-embedding"]
    assert events == ["asr:load", "asr:unload", "diarization:load", "diarization:unload"]
    assert not asr.loaded
    assert not diarization.loaded


class SingleTurnDiarization(FakeDiarizationBackend):
    """S2 只发言一次但时长足够：是真实说话人，必须保留并给出 1 个试听片段。"""

    def diarize(self, audio_path: Path, expected_speakers=None):
        del expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 5.0, "S1"),
            SpeakerSegment(5.0, 10.0, "S2"),
            SpeakerSegment(10.0, 15.0, "S1"),
        ]


def test_single_turn_cluster_reaches_review_with_one_clip(client):
    # 回归：过去「每簇必须凑满 2 个试听片段」会把单次发言者整场打成 FAILED。
    meeting_id = _queue_meeting(client)

    _worker(client, diarization_backend=SingleTurnDiarization()).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    with client.app.state.session_factory() as session:
        clusters = {
            cluster.cluster_id: json.loads(cluster.sample_clips_json)
            for cluster in session.scalars(
                select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
            )
        }
    assert set(clusters) == {"S1", "S2"}
    assert len(clusters["S1"]) == 2
    assert len(clusters["S2"]) == 1


class FragmentDiarization(FakeDiarizationBackend):
    """真实音频常见输出：主簇之外混着一个亚秒碎簇 S9。"""

    def diarize(self, audio_path: Path, expected_speakers=None):
        del expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 5.0, "S1"),
            SpeakerSegment(5.0, 10.0, "S2"),
            SpeakerSegment(10.0, 15.0, "S1"),
            SpeakerSegment(15.2, 15.8, "S9"),
            SpeakerSegment(16.0, 21.0, "S2"),
        ]


def test_fragment_cluster_is_merged_and_meeting_reaches_review(client):
    meeting_id = _queue_meeting(client)

    _worker(client, diarization_backend=FragmentDiarization()).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    with client.app.state.session_factory() as session:
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
    assert {cluster.cluster_id for cluster in clusters} == {"S1", "S2"}


class FailingEmbedding(FakeEmbeddingBackend):
    def embed(self, audio_path: Path, cluster_id: str):
        raise RuntimeError("fake embedding 故障")


def test_late_failure_after_segments_commit_still_lands_in_failed(client):
    # 声纹匹配发生在转写片段已落库之后：晚期异常仍要回滚并落 FAILED。
    meeting_id = _queue_meeting(client)
    _seed_s1_voiceprint(client)

    _worker(client, embedding_backend=FailingEmbedding()).process_next()

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting.state == "FAILED"
        assert meeting.processing_step == "VOICEPRINT_MATCHING"
        assert "fake embedding 故障" in meeting.processing_error

    # 失败后队列不被卡住：下一场照常处理。
    other_id = _queue_meeting(client, "下一场")
    _worker(client).process_next()
    detail = client.get(f"/api/meetings/{other_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"


class BlobAsr(FakeAsrBackend):
    """整段无时间戳转写并记录每次收到的音频：模拟 Qwen3-ASR 的真实行为。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path, hotwords=()) -> list[AsrSegment]:
        if not self.loaded:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        self.calls.append(Path(audio_path))
        return [AsrSegment(0.0, 1.0, f"整段转写{len(self.calls)}")]


def test_blob_transcript_is_retranscribed_per_turn(client):
    # 整段无时间戳转写 + 多个发言轮次：逐轮切音频重转写，让每句话有归属。
    meeting_id = _queue_meeting_with_real_wav(client, seconds=20.0)
    asr = BlobAsr()

    _worker(client, asr_backend=asr).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()
    # fake 切分给出 S1/S2 交替 4 轮（每轮 5s）；首次整段转写被逐轮结果替换。
    assert [segment.cluster_id for segment in segments] == ["S1", "S2", "S1", "S2"]
    assert [segment.text for segment in segments] == [
        "整段转写2",
        "整段转写3",
        "整段转写4",
        "整段转写5",
    ]
    assert [
        (segment.start_seconds, segment.end_seconds) for segment in segments
    ] == [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0)]
    # 第 1 次是整段，后 4 次是切片；切片文件在临时目录、事后清理。
    assert len(asr.calls) == 5
    assert all(not path.exists() for path in asr.calls[1:])


class CoarseBlobAsr(FakeAsrBackend):
    """长音频场景：整段转写被 ASR 内部分块成少数粗段（仍远粗于轮次粒度）。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path, hotwords=()) -> list[AsrSegment]:
        if not self.loaded:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        self.calls.append(Path(audio_path))
        if len(self.calls) == 1:
            return [
                AsrSegment(0.0, 20.0, "粗段一"),
                AsrSegment(20.0, 40.0, "粗段二"),
            ]
        return [AsrSegment(0.0, 1.0, f"轮次{len(self.calls) - 1}")]


def test_coarse_multi_segment_transcript_is_retranscribed_per_turn(client):
    # 真机踩过的坑：27 分钟录音 ASR 返回 2 个巨型段（不是 1 个），
    # 逐轮重转写不能只认「恰好 1 段」，粒度远粗于轮次时也要触发。
    meeting_id = _queue_meeting_with_real_wav(client, seconds=40.0, expected_speakers=4)
    asr = CoarseBlobAsr()

    _worker(client, asr_backend=asr).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()
    # fake 切分 4 人 8 段（5s 交替）→ 8 个轮次，各自重转写
    assert [segment.text for segment in segments] == [
        f"轮次{index}" for index in range(1, 9)
    ]
    assert len(asr.calls) == 9  # 1 次整段 + 8 次切片


class SingleClusterDiarization(FakeDiarizationBackend):
    def diarize(self, audio_path: Path, expected_speakers=None):
        del expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 5.0, "S1"),
            SpeakerSegment(5.0, 10.0, "S1"),
        ]


def test_blob_transcript_with_single_turn_is_kept_as_is(client):
    meeting_id = _queue_meeting_with_real_wav(client, seconds=10.0)
    asr = BlobAsr()

    _worker(
        client, asr_backend=asr, diarization_backend=SingleClusterDiarization()
    ).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    assert len(asr.calls) == 1
    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        ).all()
    assert [segment.text for segment in segments] == ["整段转写1"]


def test_blob_transcript_keeps_whole_text_when_audio_not_sliceable(client):
    # 音频不是可解析的 PCM wav（如损坏文件）：保留整段转写，不许整场失败。
    meeting_id = _queue_meeting(client)
    asr = BlobAsr()

    _worker(client, asr_backend=asr).process_next()

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    assert len(asr.calls) == 1
    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        ).all()
    assert [segment.text for segment in segments] == ["整段转写1"]


class FailingAsr(FakeAsrBackend):
    def transcribe(self, audio_path: Path, hotwords=()) -> list[AsrSegment]:
        raise RuntimeError("fake ASR 故障")


def test_processing_exception_marks_meeting_failed_and_persists_error(client):
    meeting_id = _queue_meeting(client)

    _worker(client, asr_backend=FailingAsr()).process_next()

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.state == "FAILED"
        assert meeting.processing_step == "ASR"
        assert meeting.processing_error is not None
        assert "fake ASR 故障" in meeting.processing_error
