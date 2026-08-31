"""出卡前碎簇按声纹吸收进主簇：只合并簇标签、绝不自动赋身份。"""

from __future__ import annotations

import math
from pathlib import Path

from sqlalchemy import select

from meeting_api.config import Settings
from meeting_api.models import Person, SpeakerCluster, TranscriptSegment, Voiceprint
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend
from meeting_api.pipeline.diarization import FakeDiarizationBackend, SpeakerSegment
from meeting_api.pipeline.embedding import FakeEmbeddingBackend, embedding_to_bytes
from meeting_api.worker import Worker

S1_VECTOR = (1.0, 0.0, 0.0)
S2_VECTOR = (0.0, 1.0, 0.0)
S9_VECTOR = (0.9, math.sqrt(1.0 - 0.9 * 0.9), 0.0)


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


class FragmentAbsorbDiarization(FakeDiarizationBackend):
    def diarize(self, audio_path: Path, expected_speakers=None):
        del audio_path, expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 10.0, "S1"),
            SpeakerSegment(10.0, 20.0, "S2"),
            SpeakerSegment(20.0, 24.0, "S9"),
            SpeakerSegment(30.0, 40.0, "S1"),
            SpeakerSegment(40.0, 50.0, "S2"),
            SpeakerSegment(50.0, 54.0, "S9"),
            SpeakerSegment(60.0, 65.0, "S1"),
            SpeakerSegment(65.0, 70.0, "S2"),
        ]


class ThreeClusterFragmentDiarization(FakeDiarizationBackend):
    def diarize(self, audio_path: Path, expected_speakers=None):
        del audio_path, expected_speakers
        if not self.loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        return [
            SpeakerSegment(0.0, 10.0, "S1"),
            SpeakerSegment(10.0, 20.0, "S2"),
            SpeakerSegment(20.0, 24.0, "S9"),
            SpeakerSegment(30.0, 40.0, "S1"),
            SpeakerSegment(40.0, 50.0, "S2"),
            SpeakerSegment(50.0, 54.0, "S9"),
            SpeakerSegment(60.0, 70.0, "S3"),
            SpeakerSegment(80.0, 90.0, "S3"),
        ]


class SegmentAlignedAsr(FakeAsrBackend):
    def transcribe(self, audio_path: Path, hotwords=()):
        del audio_path, hotwords
        if not self.loaded:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        return [
            AsrSegment(0.0, 10.0, "S1 第一段"),
            AsrSegment(10.0, 20.0, "S2 第一段"),
            AsrSegment(20.0, 24.0, "S9 第一段"),
            AsrSegment(30.0, 40.0, "S1 第二段"),
            AsrSegment(40.0, 50.0, "S2 第二段"),
            AsrSegment(50.0, 54.0, "S9 第二段"),
            AsrSegment(60.0, 70.0, "S3 第一段"),
            AsrSegment(80.0, 90.0, "S3 第二段"),
        ]


class ClusterAwareEmbedding(FakeEmbeddingBackend):
    def embed(self, audio_path: Path, windows):
        del audio_path
        if not self.loaded:
            raise RuntimeError("声纹后端未加载（先 load()）")
        starts = {start for start, _ in windows}
        if starts <= {0.0, 30.0} or starts <= {0.0, 30.0, 60.0}:
            return S1_VECTOR
        if starts <= {10.0, 40.0} or starts <= {10.0, 40.0, 65.0}:
            return S2_VECTOR
        if starts <= {20.0, 50.0}:
            return S9_VECTOR
        if starts <= {60.0, 80.0}:
            return (0.95, math.sqrt(1.0 - 0.95 * 0.95), 0.0)
        raise AssertionError(f"未覆盖的声纹窗口: {windows}")


def _seed_s1_voiceprint(client) -> None:
    with client.app.state.session_factory() as session:
        session.add(Person(id="fake-person-1", display_name="已知用户 1"))
        session.add(
            Voiceprint(
                person_id="fake-person-1",
                embedding=embedding_to_bytes(S1_VECTOR),
            )
        )
        session.commit()


def _settings_with_fragment_limit(client, seconds: float) -> Settings:
    current = client.app.state.settings
    return Settings(
        data_dir=current.data_dir,
        static_dir=current.static_dir,
        database_url=current.database_url,
        upload_disk_reserve_bytes=current.upload_disk_reserve_bytes,
        worker_disabled=current.worker_disabled,
        worker_poll_seconds=current.worker_poll_seconds,
        asr_backend=current.asr_backend,
        diarization_backend=current.diarization_backend,
        embedding_backend=current.embedding_backend,
        minutes_backend=current.minutes_backend,
        fragment_merge_max_seconds=seconds,
    )


def test_embedding_absorbs_fragment_cluster_before_review_cards(client):
    _seed_s1_voiceprint(client)
    meeting_id = _queue_meeting(client)

    _worker(
        client,
        asr_backend=SegmentAlignedAsr(),
        diarization_backend=FragmentAbsorbDiarization(),
        embedding_backend=ClusterAwareEmbedding(),
    ).process_next()

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )
    with client.app.state.session_factory() as session:
        clusters = {
            cluster.cluster_id: cluster
            for cluster in session.scalars(
                select(SpeakerCluster)
                .where(SpeakerCluster.meeting_id == meeting_id)
                .order_by(SpeakerCluster.cluster_id)
            )
        }
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()

    assert set(clusters) == {"S1", "S2"}
    assert [segment.cluster_id for segment in segments if segment.text.startswith("S9")] == [
        "S1",
        "S1",
    ]
    assert clusters["S1"].total_seconds == 33.0
    assert clusters["S1"].person_id is None
    assert clusters["S2"].person_id is None
    assert clusters["S1"].suggested_person_id == "fake-person-1"
    assert clusters["S1"].suggested_tier == "high"

    review = client.get(f"/api/meetings/{meeting_id}/review")
    assert review.status_code == 200
    assert {card["cluster_id"] for card in review.json()["cards"]} == {"S1", "S2"}


def test_default_fake_embedding_keeps_orthogonal_fragment_as_card(client):
    meeting_id = _queue_meeting(client)

    _worker(
        client,
        asr_backend=SegmentAlignedAsr(),
        diarization_backend=FragmentAbsorbDiarization(),
    ).process_next()

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )
    with client.app.state.session_factory() as session:
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
    assert [cluster.cluster_id for cluster in clusters] == ["S1", "S2", "S9"]

    review = client.get(f"/api/meetings/{meeting_id}/review")
    assert {card["cluster_id"] for card in review.json()["cards"]} == {"S1", "S2", "S9"}


def test_fragment_absorption_can_be_disabled_by_settings(client):
    meeting_id = _queue_meeting(client)

    _worker(
        client,
        settings=_settings_with_fragment_limit(client, 0.0),
        asr_backend=SegmentAlignedAsr(),
        diarization_backend=FragmentAbsorbDiarization(),
        embedding_backend=ClusterAwareEmbedding(),
    ).process_next()

    with client.app.state.session_factory() as session:
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
    assert [cluster.cluster_id for cluster in clusters] == ["S1", "S2", "S9"]


def test_decisions_still_support_merge_and_nearest_after_fragment_absorption(client):
    meeting_id = _queue_meeting(client)

    _worker(
        client,
        asr_backend=SegmentAlignedAsr(),
        diarization_backend=ThreeClusterFragmentDiarization(),
        embedding_backend=ClusterAwareEmbedding(),
    ).process_next()

    review = client.get(f"/api/meetings/{meeting_id}/review")
    assert review.status_code == 200
    assert {card["cluster_id"] for card in review.json()["cards"]} == {"S1", "S2", "S3"}

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEW_PERSON", "display_name": "王芳"},
                {
                    "cluster_id": "S2",
                    "kind": "MERGE_WITH_CLUSTER",
                    "merge_into_cluster_id": "S1",
                },
                {"cluster_id": "S3", "kind": "NEAREST_CONFIRMED"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "GENERATING_MINUTES"
    with client.app.state.session_factory() as session:
        clusters = {
            cluster.cluster_id: cluster
            for cluster in session.scalars(
                select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
            )
        }
    assert clusters["S2"].person_id == clusters["S1"].person_id
    assert clusters["S3"].person_id == clusters["S1"].person_id
    assert clusters["S3"].assigned_via == "voiceprint_nearest"
