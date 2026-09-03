from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select

from meeting_api.minutes.adapter import FakeMinutesAdapter, MinutesCliError
from meeting_api.models import Meeting, Person, SpeakerCluster, TranscriptSegment
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
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": "已知用户 1",
                },
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
    second = client.post(
        "/api/hotwords", json={"word": "  术语乙  ", "note": "  乙的注解  "}
    )
    first = client.post("/api/hotwords", json={"word": "术语甲"})

    assert second.status_code == 201
    assert first.status_code == 201
    assert second.json()["note"] == "乙的注解"
    assert first.json()["note"] is None
    listed = client.get("/api/hotwords")
    assert listed.status_code == 200
    assert [item["word"] for item in listed.json()["items"]] == sorted(["术语甲", "术语乙"])
    assert {
        item["word"]: item["note"] for item in listed.json()["items"]
    } == {"术语甲": None, "术语乙": "乙的注解"}
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
        language: str = "zh",
    ) -> list[AsrSegment]:
        self.received_hotwords = tuple(hotwords)
        # 模拟快照落库之后全局词库发生变化；本次 ASR 不得看到这个新值。
        from meeting_api.models import HotwordEntry

        with self.session_factory() as session:
            session.add(HotwordEntry(word="事后新增"))
            session.commit()
        return super().transcribe(audio_path, hotwords, language)


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
    else:
        # 本用例验证重转写不删除跨会议人员资产；停在审核态时显式造一位人员。
        with client.app.state.session_factory() as session:
            session.add(Person(display_name="跨会议人员"))
            session.commit()

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
        person_count_before = session.scalar(select(func.count()).select_from(Person))

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
        person_count_after = session.scalar(select(func.count()).select_from(Person))
    assert meeting.state == "QUEUED"
    # 人员是跨会议资产：清本场产物不得动 persons 表。
    assert person_count_before > 0
    assert person_count_after == person_count_before
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


def test_hotword_note_can_be_set_cleared_validated_and_404(client):
    created = client.post("/api/hotwords", json={"word": "术语甲", "note": "旧注解"})
    assert created.status_code == 201
    entry_id = created.json()["id"]

    updated = client.patch(f"/api/hotwords/{entry_id}", json={"note": "  新注解  "})

    assert updated.status_code == 200
    assert updated.json() == {"id": entry_id, "word": "术语甲", "note": "新注解"}

    cleared = client.patch(f"/api/hotwords/{entry_id}", json={"note": "   "})
    assert cleared.status_code == 200
    assert cleared.json()["note"] is None

    cleared_with_null = client.patch(f"/api/hotwords/{entry_id}", json={"note": None})
    assert cleared_with_null.status_code == 200
    assert cleared_with_null.json()["note"] is None

    too_long = client.patch(f"/api/hotwords/{entry_id}", json={"note": "字" * 501})
    assert too_long.status_code == 422

    # 创建入口与 PATCH 同一上限，不给超长注解留后门。
    too_long_create = client.post(
        "/api/hotwords", json={"word": "超长注解词", "note": "字" * 501}
    )
    assert too_long_create.status_code == 422

    missing = client.patch("/api/hotwords/missing-entry", json={"note": "新注解"})
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "meeting_state",
    [
        "DRAFT",
        # UPLOADING → QUEUED 是合法的上传完成边，但不是重转写；必须 409。
        "UPLOADING",
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


def test_retranscribe_asr_uses_snapshot_taken_at_worker_run_start(client):
    """重转写请求会预写一次快照，但 ASR 语义钉在 worker 开跑那一刻：

    POST /retranscribe 之后、worker 开跑之前的全局词库改动会生效；
    开跑之后的改动不生效。快照锁定的时点是「开跑」，不是「请求」。
    """
    meeting_id = _prepare_review(client, hotwords=["本场词"])
    assert client.post(f"/api/meetings/{meeting_id}/retranscribe").status_code == 200
    assert client.post("/api/hotwords", json={"word": "排队期间新增"}).status_code == 201

    probe = SnapshotProbeAsr(client.app.state.session_factory)
    client.app.state.worker.asr_backend = probe
    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        persisted = tuple(
            json.loads(session.get(Meeting, meeting_id).hotword_snapshot_json)
        )
    assert persisted == tuple(sorted({"排队期间新增", "本场词"}))
    assert probe.received_hotwords == persisted
    # probe 在转写过程中往全局词库插入的「事后新增」不得回流进本次快照。
    assert "事后新增" not in persisted


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
