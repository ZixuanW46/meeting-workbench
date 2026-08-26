from __future__ import annotations

import shutil

from meeting_api.config import Settings
from meeting_api.routes import upload


def _create_meeting(client) -> str:
    response = client.post("/api/meetings", json={"title": "磁盘保护测试"})
    assert response.status_code == 201
    return response.json()["id"]


def _low_disk(monkeypatch, *, free_bytes: int) -> None:
    monkeypatch.setattr(
        upload.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(10 * 1024**3, 9 * 1024**3, free_bytes),
    )


def test_upload_disk_reserve_has_readable_one_gib_default():
    assert Settings().upload_disk_reserve_bytes == 1024**3


def test_multipart_upload_rejects_low_disk_with_human_readable_free_space(
    client, monkeypatch
):
    meeting_id = _create_meeting(client)
    _low_disk(monkeypatch, free_bytes=512 * 1024**2)

    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 422
    assert "磁盘空间不足" in response.json()["detail"]
    assert "还剩 0.50 GB" in response.json()["detail"]
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "DRAFT"


def test_tus_creation_rejects_low_disk_before_creating_upload(client, monkeypatch):
    meeting_id = _create_meeting(client)
    _low_disk(monkeypatch, free_bytes=768 * 1024**2)

    response = client.post(
        f"/api/meetings/{meeting_id}/files/",
        headers={"Tus-Resumable": "1.0.0", "Upload-Length": str(1024**2)},
    )

    assert response.status_code == 422
    assert "磁盘空间不足" in response.json()["detail"]
    assert "还剩 0.75 GB" in response.json()["detail"]
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "DRAFT"
