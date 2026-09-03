"""取消处理：排队/转写中 → CANCELED；生成纪要中 → PARTIAL_READY（转写与确认不丢）。

worker 是协作式取消：在步骤边界重读数据库状态，发现被取消就放弃本轮，
绝不用内存里的旧状态把 CANCELED 覆盖回去。
"""

from __future__ import annotations

from pathlib import Path

from meeting_api.models import Meeting
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend
from meeting_api.worker import Worker
from meeting_domain import MeetingState


def _create_and_upload(client) -> str:
    meeting_id = client.post("/api/meetings", json={"title": "取消测试"}).json()["id"]
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert response.status_code == 200
    return meeting_id


def _to_generating_minutes(client, meeting_id: str) -> None:
    assert client.app.state.worker.process_next() == meeting_id
    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEW_PERSON", "display_name": "王芳"},
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "GENERATING_MINUTES"


def _replace_worker(client, **overrides) -> Worker:
    options = {
        "session_factory": client.app.state.session_factory,
        "settings": client.app.state.settings,
        "event_store": client.app.state.events,
    }
    options.update(overrides)
    worker = Worker(**options)
    client.app.state.worker = worker
    return worker


def test_cancel_queued_meeting_goes_canceled_and_worker_skips_it(client):
    meeting_id = _create_and_upload(client)

    response = client.post(f"/api/meetings/{meeting_id}/cancel")

    assert response.status_code == 200
    assert response.json()["state"] == "CANCELED"
    assert client.app.state.worker.process_next() is None
    assert client.get(f"/api/meetings/{meeting_id}/progress").json()["state"] == "CANCELED"


def test_cancel_during_processing_is_honored_at_next_step_boundary(client):
    meeting_id = _create_and_upload(client)

    class CancelingAsr(FakeAsrBackend):
        def transcribe(self, audio_path: Path, hotwords=(), language="zh") -> list[AsrSegment]:
            # 模拟用户在转写进行中点了取消。
            assert client.post(f"/api/meetings/{meeting_id}/cancel").status_code == 200
            return super().transcribe(audio_path, hotwords, language)

    _replace_worker(client, asr_backend=CancelingAsr())

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    assert detail["state"] == "CANCELED"
    assert detail["processing_error"] is None
    # 半途产物不留：取消后再重新处理必须从零开始。
    assert client.get(f"/api/meetings/{meeting_id}/review").status_code == 409


def test_cancel_during_minutes_generation_falls_back_to_partial_ready(client):
    meeting_id = _create_and_upload(client)
    _to_generating_minutes(client, meeting_id)
    target_dir = client.app.state.settings.data_dir / "meetings" / meeting_id

    class CancelingMinutes:
        def generate(self, transcript: str) -> str:
            assert client.post(f"/api/meetings/{meeting_id}/cancel").status_code == 200
            return "# 不该落盘的纪要"

    client.app.state.settings.transcript_cleaning_enabled = False
    _replace_worker(client, minutes_adapter=CancelingMinutes())

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    assert detail["state"] == "PARTIAL_READY"
    assert not (target_dir / "minutes.md").exists()
    # 转写与确认还在，随时可重试纪要。
    assert client.get(f"/api/meetings/{meeting_id}/transcript").status_code == 200
    assert client.post(f"/api/meetings/{meeting_id}/minutes/retry").status_code == 200


def test_cancel_generating_minutes_endpoint_returns_partial_ready(client):
    meeting_id = _create_and_upload(client)
    _to_generating_minutes(client, meeting_id)

    response = client.post(f"/api/meetings/{meeting_id}/cancel")

    assert response.status_code == 200
    assert response.json()["state"] == "PARTIAL_READY"


def test_cancel_rejects_states_that_are_not_being_processed(client):
    draft_id = client.post("/api/meetings", json={"title": "草稿"}).json()["id"]
    assert client.post(f"/api/meetings/{draft_id}/cancel").status_code == 409

    ready_id = _create_and_upload(client)
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, ready_id)
        assert meeting is not None
        meeting.state = MeetingState.READY.value
        session.commit()
    assert client.post(f"/api/meetings/{ready_id}/cancel").status_code == 409
    assert client.post("/api/meetings/nope/cancel").status_code == 404
