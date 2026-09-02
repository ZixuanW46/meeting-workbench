"""FAILED 不再是死胡同：错误文本透出，音频还在就能重新处理。"""

from __future__ import annotations

from meeting_api.models import Meeting
from meeting_domain import MeetingState


def _create_and_upload(client) -> str:
    meeting_id = client.post("/api/meetings", json={"title": "失败会议"}).json()["id"]
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert response.status_code == 200
    return meeting_id


def _force_state(client, meeting_id: str, state: MeetingState, error: str | None) -> None:
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.state = state.value
        meeting.processing_error = error
        meeting.processing_step = "ASR" if state is MeetingState.FAILED else None
        session.commit()


def test_meeting_response_exposes_processing_error(client):
    meeting_id = _create_and_upload(client)
    _force_state(client, meeting_id, MeetingState.FAILED, "RuntimeError: 模型内存不足")

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    listed = client.get("/api/meetings").json()["items"][0]

    assert detail["processing_error"] == "RuntimeError: 模型内存不足"
    assert listed["processing_error"] == "RuntimeError: 模型内存不足"
    # 错误文本只给人看，不能带服务器路径。
    assert str(client.app.state.settings.data_dir) not in detail["processing_error"]


def test_failed_meeting_with_audio_can_be_retranscribed(client):
    meeting_id = _create_and_upload(client)
    _force_state(client, meeting_id, MeetingState.FAILED, "RuntimeError: 模型内存不足")

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "QUEUED"
    assert body["processing_error"] is None
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )


def test_canceled_meeting_with_audio_can_be_retranscribed(client):
    meeting_id = _create_and_upload(client)
    _force_state(client, meeting_id, MeetingState.CANCELED, None)

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 200
    assert response.json()["state"] == "QUEUED"


def test_failed_meeting_without_audio_cannot_be_retranscribed(client):
    meeting_id = client.post("/api/meetings", json={"title": "没音频"}).json()["id"]
    _force_state(client, meeting_id, MeetingState.FAILED, "ValueError: 会议缺少完整的音频元数据")

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 409
    assert "音频" in response.json()["detail"]
