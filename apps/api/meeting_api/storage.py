from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from meeting_api.config import Settings


@dataclass(frozen=True)
class SavedUpload:
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True)
class PendingUpload:
    """尚未完成的 tus 上传；路径只供服务端内部使用。"""

    path: Path
    length: int
    offset: int
    filename: str | None = None


class EmptyUploadError(ValueError):
    pass


class AudioTranscodeError(RuntimeError):
    pass


# ffmpeg 卡死不能拖垮上传请求：超时按转码失败处理，测试里会调小这个值。
TRANSCODE_TIMEOUT_SECONDS = 120.0


def _describe_file(path: Path) -> SavedUpload:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return SavedUpload(filename=path.name, size=size, sha256=digest.hexdigest())


def meeting_dir(settings: Settings, meeting_id: str) -> Path:
    """返回会议的本地目录；调用方不得把该路径放进 API 响应。"""
    return settings.data_dir / "meetings" / meeting_id


def create_pending_upload(
    settings: Settings,
    meeting_id: str,
    upload_id: str,
    length: int,
    filename: str | None = None,
) -> PendingUpload:
    upload_dir = meeting_dir(settings, meeting_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{upload_id}.part"
    metadata_path = upload_dir / f"{upload_id}.json"
    path.touch(exist_ok=False)
    metadata_path.write_text(
        json.dumps({"length": length, "filename": filename}), encoding="utf-8"
    )
    return PendingUpload(path=path, length=length, offset=0, filename=filename)


def get_pending_upload(
    settings: Settings,
    meeting_id: str,
    upload_id: str,
) -> PendingUpload | None:
    upload_dir = meeting_dir(settings, meeting_id) / "uploads"
    path = upload_dir / f"{upload_id}.part"
    metadata_path = upload_dir / f"{upload_id}.json"
    if not path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        length = metadata["length"]
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(length, int) or length <= 0:
        return None
    filename = metadata.get("filename")
    if not isinstance(filename, str):
        filename = None
    return PendingUpload(
        path=path, length=length, offset=path.stat().st_size, filename=filename
    )


def clear_pending_uploads(settings: Settings, meeting_id: str) -> None:
    """作废该会议的全部未完成上传（用户放弃后重新发起时调用）。"""
    upload_dir = meeting_dir(settings, meeting_id) / "uploads"
    if not upload_dir.is_dir():
        return
    for entry in upload_dir.iterdir():
        if entry.is_file():
            entry.unlink(missing_ok=True)
    try:
        upload_dir.rmdir()
    except OSError:
        pass


def remove_pending_upload(
    settings: Settings,
    meeting_id: str,
    upload_id: str,
) -> None:
    upload_dir = meeting_dir(settings, meeting_id) / "uploads"
    (upload_dir / f"{upload_id}.part").unlink(missing_ok=True)
    (upload_dir / f"{upload_id}.json").unlink(missing_ok=True)
    try:
        upload_dir.rmdir()
    except OSError:
        pass


def save_stream(
    settings: Settings,
    meeting_id: str,
    filename: str | None,
    stream: BinaryIO,
) -> SavedUpload:
    raw_dir = meeting_dir(settings, meeting_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 浏览器文件名不可信，同时兼容 POSIX 与 Windows 风格的路径。
    # Path("a/..").name == ".."，会把目标指到 raw/ 上层，必须一并兜底。
    safe_filename = Path((filename or "").replace("\\", "/")).name
    if safe_filename in {"", ".", ".."} or "\x00" in safe_filename:
        safe_filename = "audio"
    target = raw_dir / safe_filename
    digest = hashlib.sha256()
    size = 0

    with target.open("wb") as output:
        while chunk := stream.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)

    if size == 0:
        target.unlink()
        raise EmptyUploadError("音频文件不能为空")

    return SavedUpload(filename=safe_filename, size=size, sha256=digest.hexdigest())


def transcode_audio_if_needed(
    settings: Settings,
    meeting_id: str,
    saved: SavedUpload,
) -> SavedUpload:
    """把需要兼容的压缩音频转为 16kHz 单声道 PCM WAV。"""
    if Path(saved.filename).suffix.lower() not in {".mp3", ".m4a", ".aac"}:
        return saved

    raw_dir = meeting_dir(settings, meeting_id) / "raw"
    source = raw_dir / saved.filename
    wav_filename = f"{Path(saved.filename).stem}.wav"
    target = raw_dir / wav_filename
    command = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-c:a",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(target),
    ]

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=TRANSCODE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        source.unlink(missing_ok=True)
        raise AudioTranscodeError("未找到 ffmpeg，无法完成音频转码") from exc
    except subprocess.TimeoutExpired as exc:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise AudioTranscodeError("音频转码超时，请检查音频文件是否损坏") from exc

    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise AudioTranscodeError("音频转码失败，请检查音频文件是否损坏")

    source.unlink(missing_ok=True)
    return _describe_file(target)
