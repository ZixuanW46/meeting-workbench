from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select

from meeting_api.models import Meeting, SpeakerCluster, TranscriptSegment
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend
from meeting_api.pipeline.diarization import FakeDiarizationBackend, SpeakerSegment
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


def _worker(client, **overrides) -> Worker:
    options = {
        "session_factory": client.app.state.session_factory,
        "settings": client.app.state.settings,
    }
    options.update(overrides)
    return Worker(**options)


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
    assert clusters[0].suggested_person_id == "fake-person-1"
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

    assert slot.used_backends == ["fake-asr", "fake-diarization"]
    assert events == ["asr:load", "asr:unload", "diarization:load", "diarization:unload"]
    assert not asr.loaded
    assert not diarization.loaded


class SparseDiarization(FakeDiarizationBackend):
    """某簇只有 1 段：让失败发生在片段已落库之后的准备确认包步骤。"""

    def diarize(self, audio_path: Path, expected_speakers=None):
        del expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 5.0, "S1"),
            SpeakerSegment(5.0, 10.0, "S2"),
            SpeakerSegment(10.0, 15.0, "S1"),
        ]


def test_late_failure_after_processing_commit_still_lands_in_failed(client):
    meeting_id = _queue_meeting(client)

    _worker(client, diarization_backend=SparseDiarization()).process_next()

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting.state == "FAILED"
        assert meeting.processing_step == "PREPARING_REVIEW"
        assert "S2" in meeting.processing_error

    # 失败后队列不被卡住：下一场照常处理。
    other_id = _queue_meeting(client, "下一场")
    _worker(client).process_next()
    detail = client.get(f"/api/meetings/{other_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"


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
