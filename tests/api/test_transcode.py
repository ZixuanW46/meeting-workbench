from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from meeting_api.models import Meeting

TUS_VERSION = "1.0.0"
TRANSCODED_AUDIO = b"RIFF-fake-16k-mono-wav"


def _create_meeting(client) -> dict:
    response = client.post("/api/meetings", json={"title": "转码测试会议"})
    assert response.status_code == 201
    return response.json()


def _install_ffmpeg_stub(tmp_path: Path, monkeypatch, *, exit_code: int = 0) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "ffmpeg-argv.txt"
    stub = bin_dir / "ffmpeg"
    stub.write_text(
        """#!/bin/sh
printf '%s\\n' "$@" > "$FFMPEG_ARGV_FILE"
if [ "$FFMPEG_STUB_EXIT" -ne 0 ]; then
    exit "$FFMPEG_STUB_EXIT"
fi
for output_path do :; done
printf 'RIFF-fake-16k-mono-wav' > "$output_path"
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("FFMPEG_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("FFMPEG_STUB_EXIT", str(exit_code))
    return argv_file


def _stored_meeting(client, meeting_id: str) -> Meeting:
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        session.expunge(meeting)
        return meeting


def _raw_dir(client, meeting_id: str) -> Path:
    return client.app.state.settings.data_dir / "meetings" / meeting_id / "raw"


@pytest.mark.parametrize("extension", ["wav", "flac", "ogg"])
def test_multipart_keeps_supported_audio_without_ffmpeg(
    client, tmp_path, monkeypatch, extension
):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    meeting = _create_meeting(client)
    content = f"original-{extension}-bytes".encode()

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": (f"recording.{extension}", content, "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "QUEUED"
    assert stored.audio_filename == f"recording.{extension}"
    assert (_raw_dir(client, meeting["id"]) / stored.audio_filename).read_bytes() == content


@pytest.mark.parametrize("extension", ["mp3", "m4a", "aac"])
def test_multipart_transcodes_compressed_audio_before_queueing(
    client, tmp_path, monkeypatch, extension
):
    argv_file = _install_ffmpeg_stub(tmp_path, monkeypatch)
    meeting = _create_meeting(client)

    response = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": (f"recording.{extension}", b"compressed-audio", "audio/mpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "size": len(TRANSCODED_AUDIO),
        "sha256": hashlib.sha256(TRANSCODED_AUDIO).hexdigest(),
    }
    argv = argv_file.read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("-ar") + 1] == "16000"
    assert argv[argv.index("-ac") + 1] == "1"
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "QUEUED"
    assert stored.audio_filename == "recording.wav"
    assert (_raw_dir(client, meeting["id"]) / "recording.wav").read_bytes() == TRANSCODED_AUDIO


@pytest.mark.parametrize("extension", ["MP3", "m4a", "aac"])
def test_tus_completion_transcodes_before_queueing(
    client, tmp_path, monkeypatch, extension
):
    argv_file = _install_ffmpeg_stub(tmp_path, monkeypatch)
    meeting = _create_meeting(client)
    content = b"tus-compressed-audio"
    filename = base64.b64encode(f"访谈.{extension}".encode()).decode()
    created = client.post(
        f"/api/meetings/{meeting['id']}/files/",
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Length": str(len(content)),
            "Upload-Metadata": f"filename {filename}",
        },
    )
    assert created.status_code == 201

    response = client.patch(
        urlsplit(created.headers["Location"]).path,
        content=content,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
    )

    assert response.status_code == 204
    argv = argv_file.read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("-ar") + 1] == "16000"
    assert argv[argv.index("-ac") + 1] == "1"
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "QUEUED"
    assert stored.audio_filename == "访谈.wav"
    assert (_raw_dir(client, meeting["id"]) / "访谈.wav").read_bytes() == TRANSCODED_AUDIO


def test_missing_ffmpeg_returns_422_and_multipart_can_retry(
    client, tmp_path, monkeypatch
):
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    meeting = _create_meeting(client)

    failed = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("recording.mp3", b"compressed", "audio/mpeg")},
    )

    assert failed.status_code == 422
    assert "未找到 ffmpeg" in failed.json()["detail"]
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "DRAFT"
    assert stored.audio_filename is None
    retried = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("retry.wav", b"RIFF-retry", "audio/wav")},
    )
    assert retried.status_code == 200


def test_ffmpeg_timeout_returns_422_and_keeps_draft(client, tmp_path, monkeypatch):
    from meeting_api import storage

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sleep_bin = shutil.which("sleep")
    assert sleep_bin is not None
    stub = bin_dir / "ffmpeg"
    stub.write_text(f"#!/bin/sh\nexec {sleep_bin} 30\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(storage, "TRANSCODE_TIMEOUT_SECONDS", 0.2)
    meeting = _create_meeting(client)

    failed = client.post(
        f"/api/meetings/{meeting['id']}/upload",
        files={"file": ("recording.mp3", b"compressed", "audio/mpeg")},
    )

    assert failed.status_code == 422
    assert "转码超时" in failed.json()["detail"]
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "DRAFT"
    assert stored.audio_filename is None
    assert list(_raw_dir(client, meeting["id"]).iterdir()) == []


def test_ffmpeg_failure_returns_422_and_tus_can_restart(client, tmp_path, monkeypatch):
    _install_ffmpeg_stub(tmp_path, monkeypatch, exit_code=7)
    meeting = _create_meeting(client)
    content = b"broken-compressed-audio"
    filename = base64.b64encode(b"broken.aac").decode()
    created = client.post(
        f"/api/meetings/{meeting['id']}/files/",
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Length": str(len(content)),
            "Upload-Metadata": f"filename {filename}",
        },
    )
    upload_path = urlsplit(created.headers["Location"]).path

    failed = client.patch(
        upload_path,
        content=content,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
    )

    assert failed.status_code == 422
    assert "转码失败" in failed.json()["detail"]
    stored = _stored_meeting(client, meeting["id"])
    assert stored.state == "UPLOADING"
    assert stored.audio_filename is None
    restarted = client.post(
        f"/api/meetings/{meeting['id']}/files/",
        headers={"Tus-Resumable": TUS_VERSION, "Upload-Length": "4"},
    )
    assert restarted.status_code == 201
    assert client.head(upload_path, headers={"Tus-Resumable": TUS_VERSION}).status_code == 404
