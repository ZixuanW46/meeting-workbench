from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select

from meeting_api.minutes.adapter import FakeMinutesAdapter, MinutesCliError
from meeting_api.models import Meeting, SpeakerCluster, TranscriptSegment
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend
from meeting_api.storage import meeting_dir


def _create_meeting(client, *, hotwords: list[str] | None = None) -> str:
    response = client.post(
        "/api/meetings",
        json={
            "title": "M9 词语库测试",
            "expected_speakers": 2,
            "hotwords": hotwords or [],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _queue_meeting(client, *, hotwords: list[str] | None = None) -> str:
    meeting_id = _create_meeting(client, hotwords=hotwords)
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert response.status_code == 200
    return meeting_id


def _prepare_review(client, *, hotwords: list[str] | None = None) -> str:
    meeting_id = _queue_meeting(client, hotwords=hotwords)
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )
    return meeting_id


def _submit_decisions(client, meeting_id: str) -> None:
    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "GENERATING_MINUTES"


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for child in value.values() for text in _all_strings(child)]
    if isinstance(value, Sequence):
        return [text for child in value for text in _all_strings(child)]
    return []


def test_global_hotword_crud_is_sorted_validated_and_does_not_expose_paths(client):
    second = client.post("/api/hotwords", json={"word": "  术语乙  "})
    first = client.post("/api/hotwords", json={"word": "术语甲"})

    assert second.status_code == 201
    assert first.status_code == 201
    listed = client.get("/api/hotwords")
    assert listed.status_code == 200
    assert [item["word"] for item in listed.json()["items"]] == sorted(["术语甲", "术语乙"])
    assert not any(
        str(client.app.state.settings.data_dir) in value
        for value in _all_strings(listed.json())
    )

    blank = client.post("/api/hotwords", json={"word": "   "})
    assert blank.status_code == 422

    deleted = client.delete(f"/api/hotwords/{first.json()['id']}")
    assert deleted.status_code == 204
    assert [item["word"] for item in client.get("/api/hotwords").json()["items"]] == [
        "术语乙"
    ]


class SnapshotProbeAsr(FakeAsrBackend):
    def __init__(self, session_factory) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.received_hotwords: tuple[str, ...] | None = None

    def transcribe(
        self,
        audio_path: Path,
        hotwords: Sequence[str] = (),
    ) -> list[AsrSegment]:
        self.received_hotwords = tuple(hotwords)
        # 模拟快照落库之后全局词库发生变化；本次 ASR 不得看到这个新值。
        from meeting_api.models import HotwordEntry

        with self.session_factory() as session:
            session.add(HotwordEntry(word="事后新增"))
            session.commit()
        return super().transcribe(audio_path, hotwords)


def test_worker_persists_combined_snapshot_and_asr_reads_only_that_snapshot(client):
    assert client.post("/api/hotwords", json={"word": "全局词"}).status_code == 201
    assert client.post("/api/hotwords", json={"word": "共同词"}).status_code == 201
    meeting_id = _queue_meeting(client, hotwords=["本场词", "共同词"])
    probe = SnapshotProbeAsr(client.app.state.session_factory)
    client.app.state.worker.asr_backend = probe

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        persisted = tuple(json.loads(meeting.hotword_snapshot_json))
    assert persisted == tuple(sorted({"共同词", "全局词", "本场词"}))
    assert probe.received_hotwords == persisted
    assert "事后新增" not in persisted


def _prepare_state_with_artifacts(client, target_state: str) -> str:
    meeting_id = _prepare_review(client, hotwords=["本场词"])
    if target_state in {"READY", "PARTIAL_READY"}:
        _submit_decisions(client, meeting_id)
        if target_state == "PARTIAL_READY":
            client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
                error=MinutesCliError("模拟纪要失败")
            )
        assert client.app.state.worker.process_next() == meeting_id
        assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == target_state

    target_dir = meeting_dir(client.app.state.settings, meeting_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "transcript.txt").write_text("旧逐字稿", encoding="utf-8")
    (target_dir / "minutes.md").write_text("旧纪要", encoding="utf-8")
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        meeting.processing_step = "OLD_STEP"
        meeting.processing_error = "旧错误"
        meeting.has_unconfirmed_speakers = True
        session.commit()
    return meeting_id


@pytest.mark.parametrize(
    "target_state",
    ["AWAITING_SPEAKER_REVIEW", "READY", "PARTIAL_READY"],
)
def test_retranscribe_allowed_states_resnapshot_clear_artifacts_and_requeue(
    client, target_state
):
    assert client.post("/api/hotwords", json={"word": "旧全局词"}).status_code == 201
    meeting_id = _prepare_state_with_artifacts(client, target_state)
    old_snapshot: str
    with client.app.state.session_factory() as session:
        old_snapshot = session.get(Meeting, meeting_id).hotword_snapshot_json

    entries = client.get("/api/hotwords").json()["items"]
    for entry in entries:
        assert client.delete(f"/api/hotwords/{entry['id']}").status_code == 204
    assert client.post("/api/hotwords", json={"word": "新全局词"}).status_code == 201

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 200
    assert response.json()["state"] == "QUEUED"
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        segment_count = session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
        )
        cluster_count = session.scalar(
            select(func.count())
            .select_from(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
        )
    assert meeting.state == "QUEUED"
    assert meeting.hotword_snapshot_json != old_snapshot
    assert json.loads(meeting.hotword_snapshot_json) == ["新全局词", "本场词"]
    assert segment_count == 0
    assert cluster_count == 0
    assert meeting.has_unconfirmed_speakers is False
    assert meeting.processing_step is None
    assert meeting.processing_error is None
    target_dir = meeting_dir(client.app.state.settings, meeting_id)
    assert not (target_dir / "transcript.txt").exists()
    assert not (target_dir / "minutes.md").exists()
    assert (target_dir / "raw" / meeting.audio_filename).is_file()


@pytest.mark.parametrize(
    "meeting_state",
    [
        "DRAFT",
        "QUEUED",
        "PROCESSING",
        "APPLYING_DECISIONS",
        "GENERATING_MINUTES",
        "FAILED",
        "CANCELED",
    ],
)
def test_retranscribe_rejects_other_states(client, meeting_state):
    meeting_id = _create_meeting(client)
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        meeting.state = meeting_state
        session.commit()

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 409
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == meeting_state


def test_retranscribe_missing_meeting_returns_404(client):
    assert client.post("/api/meetings/not-found/retranscribe").status_code == 404


def test_speaker_decisions_do_not_retranscribe_or_change_snapshot(client):
    assert client.post("/api/hotwords", json={"word": "全局词"}).status_code == 201
    meeting_id = _prepare_review(client, hotwords=["本场词"])
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        snapshot_before = meeting.hotword_snapshot_json
        segment_ids_before = session.scalars(
            select(TranscriptSegment.id).where(TranscriptSegment.meeting_id == meeting_id)
        ).all()

    assert client.post("/api/hotwords", json={"word": "事后新增"}).status_code == 201
    _submit_decisions(client, meeting_id)

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        segment_ids_after = session.scalars(
            select(TranscriptSegment.id).where(TranscriptSegment.meeting_id == meeting_id)
        ).all()
    assert meeting.state == "GENERATING_MINUTES"
    assert meeting.hotword_snapshot_json == snapshot_before
    assert segment_ids_after == segment_ids_before


def test_global_hotword_changes_do_not_automatically_requeue_meetings(client):
    meeting_id = _prepare_review(client)
    with client.app.state.session_factory() as session:
        snapshot_before = session.get(Meeting, meeting_id).hotword_snapshot_json

    created = client.post("/api/hotwords", json={"word": "不会自动生效"})

    assert created.status_code == 201
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
    assert meeting.state == "AWAITING_SPEAKER_REVIEW"
    assert meeting.hotword_snapshot_json == snapshot_before
