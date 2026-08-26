from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

import pytest

from meeting_api.models import Meeting

TUS_VERSION = "1.0.0"


def _create_meeting(client) -> dict:
    response = client.post("/api/meetings", json={"title": "tus 上传会议"})
    assert response.status_code == 201
    return response.json()


def _create_upload(client, meeting_id: str, length: int):
    return client.post(
        f"/api/meetings/{meeting_id}/files/",
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Length": str(length),
        },
    )


def _upload_path(response) -> str:
    location = response.headers["Location"]
    assert "/workspace" not in location
    assert "data/meetings" not in location
    path = urlsplit(location).path
    assert path.startswith("/api/meetings/")
    return path


def _patch(client, path: str, offset: int, content: bytes):
    return client.patch(
        path,
        content=content,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Offset": str(offset),
            "Content-Type": "application/offset+octet-stream",
        },
    )


def test_tus_creation_returns_protocol_headers_and_resource_location(client):
    meeting = _create_meeting(client)

    response = _create_upload(client, meeting["id"], 12)

    assert response.status_code == 201
    assert response.headers["Tus-Resumable"] == TUS_VERSION
    path = _upload_path(response)
    assert path.startswith(f"/api/meetings/{meeting['id']}/files/")
    assert path != f"/api/meetings/{meeting['id']}/files/"


@pytest.mark.parametrize("upload_length", [None, "0"])
def test_tus_creation_rejects_missing_or_zero_upload_length(client, upload_length):
    meeting = _create_meeting(client)
    headers = {"Tus-Resumable": TUS_VERSION}
    if upload_length is not None:
        headers["Upload-Length"] = upload_length

    response = client.post(
        f"/api/meetings/{meeting['id']}/files/",
        headers=headers,
    )

    assert response.status_code in {400, 422}
    assert client.get(f"/api/meetings/{meeting['id']}").json()["state"] == "DRAFT"


def test_tus_creation_checks_meeting_scope_and_draft_state(client):
    missing = _create_upload(client, "does-not-exist", 5)
    assert missing.status_code == 404

    meeting = _create_meeting(client)
    multipart = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("existing.wav", b"audio", "audio/wav")},
    )
    assert multipart.status_code == 200

    response = _create_upload(client, meeting["id"], 5)

    assert response.status_code == 409


def test_tus_two_patches_finalize_using_multipart_storage_semantics(client):
    meeting = _create_meeting(client)
    content = b"RIFF\x00\x01resumable-meeting-audio"
    split_at = 9
    created = _create_upload(client, meeting["id"], len(content))
    assert created.status_code == 201
    path = _upload_path(created)

    first = _patch(client, path, 0, content[:split_at])
    assert first.status_code == 204
    assert first.headers["Tus-Resumable"] == TUS_VERSION
    assert first.headers["Upload-Offset"] == str(split_at)
    assert client.get(f"/api/meetings/{meeting['id']}").json()["state"] != "QUEUED"

    second = _patch(client, path, split_at, content[split_at:])

    assert second.status_code == 204
    assert second.headers["Tus-Resumable"] == TUS_VERSION
    assert second.headers["Upload-Offset"] == str(len(content))
    assert "/workspace" not in str(second.headers)
    detail = client.get(f"/api/meetings/{meeting['id']}")
    assert detail.status_code == 200
    assert detail.json()["state"] == "QUEUED"

    with client.app.state.session_factory() as session:
        stored = session.get(Meeting, meeting["id"])
        assert stored is not None
        assert stored.audio_size == len(content)
        assert stored.audio_sha256 == hashlib.sha256(content).hexdigest()
        assert stored.audio_filename is not None
        filename = stored.audio_filename

    raw_file = (
        client.app.state.settings.data_dir
        / "meetings"
        / meeting["id"]
        / "raw"
        / filename
    )
    assert raw_file.read_bytes() == content


def test_tus_wrong_patch_offset_returns_conflict_without_writing(client):
    meeting = _create_meeting(client)
    created = _create_upload(client, meeting["id"], 6)
    assert created.status_code == 201
    path = _upload_path(created)
    first = _patch(client, path, 0, b"abc")
    assert first.status_code == 204

    conflict = _patch(client, path, 1, b"XYZ")

    assert conflict.status_code == 409
    head = client.head(path, headers={"Tus-Resumable": TUS_VERSION})
    assert head.status_code == 200
    assert head.headers["Upload-Offset"] == "3"


def test_tus_head_reports_progress_and_upload_can_resume(client):
    meeting = _create_meeting(client)
    content = b"disconnect-then-resume"
    split_at = 10
    created = _create_upload(client, meeting["id"], len(content))
    assert created.status_code == 201
    path = _upload_path(created)
    assert _patch(client, path, 0, content[:split_at]).status_code == 204

    head = client.head(path, headers={"Tus-Resumable": TUS_VERSION})

    assert head.status_code == 200
    assert head.headers["Upload-Offset"] == str(split_at)
    assert head.headers["Upload-Length"] == str(len(content))
    assert head.headers["Cache-Control"] == "no-store"
    assert head.headers["Tus-Resumable"] == TUS_VERSION

    resumed = _patch(client, path, split_at, content[split_at:])
    assert resumed.status_code == 204
    assert resumed.headers["Upload-Offset"] == str(len(content))
    assert client.get(f"/api/meetings/{meeting['id']}").json()["state"] == "QUEUED"


def test_tus_empty_patch_does_not_queue_positive_length_upload(client):
    meeting = _create_meeting(client)
    created = _create_upload(client, meeting["id"], 4)
    assert created.status_code == 201
    path = _upload_path(created)

    response = _patch(client, path, 0, b"")

    assert response.status_code == 204
    assert response.headers["Upload-Offset"] == "0"
    assert client.get(f"/api/meetings/{meeting['id']}").json()["state"] != "QUEUED"


def test_tus_cors_exposes_protocol_headers_for_browser_client(client):
    meeting = _create_meeting(client)
    origin = "http://localhost:5173"
    preflight = client.options(
        f"/api/meetings/{meeting['id']}/files/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "tus-resumable,upload-length",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == origin

    created = client.post(
        f"/api/meetings/{meeting['id']}/files/",
        headers={
            "Origin": origin,
            "Tus-Resumable": TUS_VERSION,
            "Upload-Length": "5",
        },
    )
    exposed = {
        item.strip().lower()
        for item in created.headers["Access-Control-Expose-Headers"].split(",")
    }
    assert created.status_code == 201
    assert {"location", "upload-offset", "tus-resumable", "tus-version"} <= exposed


def test_existing_multipart_upload_endpoint_remains_available(client):
    meeting = _create_meeting(client)
    content = b"multipart-still-supported"

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("legacy.wav", content, "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    assert client.get(f"/api/meetings/{meeting['id']}").json()["state"] == "QUEUED"
