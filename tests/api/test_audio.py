"""M8 补的最小只读音频流：GET /api/meetings/{id}/audio。"""

from __future__ import annotations


def _create_meeting(client) -> dict:
    response = client.post("/api/meetings", json={"title": "试听会议"})
    assert response.status_code == 201
    return response.json()


def test_audio_stream_returns_uploaded_bytes(client):
    meeting = _create_meeting(client)
    content = b"RIFF\x00\x01fake-wav-bytes"
    upload = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("meeting.wav", content, "audio/wav")},
    )
    assert upload.status_code == 200

    response = client.get(f"/api/meetings/{meeting['id']}/audio")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("audio/")


def test_audio_stream_does_not_leak_server_paths(client):
    meeting = _create_meeting(client)
    upload = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("meeting.wav", b"bytes", "audio/wav")},
    )
    assert upload.status_code == 200

    response = client.get(f"/api/meetings/{meeting['id']}/audio")

    assert response.status_code == 200
    data_dir = str(client.app.state.settings.data_dir)
    for value in response.headers.values():
        assert data_dir not in value
        assert "meetings/" not in value


def test_audio_stream_before_upload_conflicts(client):
    meeting = _create_meeting(client)

    response = client.get(f"/api/meetings/{meeting['id']}/audio")

    assert response.status_code == 409


def test_audio_stream_unknown_meeting_not_found(client):
    response = client.get("/api/meetings/does-not-exist/audio")

    assert response.status_code == 404
