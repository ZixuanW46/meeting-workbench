from __future__ import annotations

import hashlib


def _create_meeting(client) -> dict:
    response = client.post("/api/meetings", json={"title": "待上传会议"})
    assert response.status_code == 201
    return response.json()


def test_upload_audio_and_queue_meeting(client):
    meeting = _create_meeting(client)
    content = b"fake-audio-content"

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("meeting.wav", content, "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    detail = client.get(f"/api/meetings/{meeting['id']}")
    assert detail.status_code == 200
    assert detail.json()["state"] == "QUEUED"


def test_upload_persists_identical_audio_bytes(client):
    meeting = _create_meeting(client)
    content = b"RIFF\x00\x01meeting-audio"

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("source.wav", content, "audio/wav")},
    )

    assert response.status_code == 200
    result = response.json()
    raw_dir = client.app.state.settings.data_dir / "meetings" / meeting["id"] / "raw"
    saved_files = list(raw_dir.iterdir())
    assert len(saved_files) == 1
    saved_content = saved_files[0].read_bytes()
    assert saved_content == content
    assert result["size"] == len(saved_content)
    assert result["sha256"] == hashlib.sha256(saved_content).hexdigest()


def test_upload_rejects_non_draft_meeting(client):
    meeting = _create_meeting(client)
    upload_url = f"/api/meetings/{meeting['id']}/upload"
    first = client.post(
        upload_url,
        files={"file": ("first.wav", b"first", "audio/wav")},
    )
    assert first.status_code == 200

    second = client.post(
        upload_url,
        files={"file": ("second.wav", b"second", "audio/wav")},
    )

    assert second.status_code == 409


def test_upload_rejects_empty_file(client):
    meeting = _create_meeting(client)

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )

    assert response.status_code == 422


def test_upload_response_does_not_expose_server_path(client):
    meeting = _create_meeting(client)

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("private.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200
    response_text = response.text
    assert "/workspace" not in response_text
    assert "data/meetings" not in response_text
    assert "\\" not in response_text

def test_empty_upload_leaves_meeting_in_draft(client):
    meeting = _create_meeting(client)
    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 422
    detail = client.get(f"/api/meetings/{meeting['id']}")
    assert detail.status_code == 200
    assert detail.json()["state"] == "DRAFT"
