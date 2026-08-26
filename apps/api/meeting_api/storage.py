from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from meeting_api.config import Settings


@dataclass(frozen=True)
class SavedUpload:
    filename: str
    size: int
    sha256: str


class EmptyUploadError(ValueError):
    pass


def meeting_dir(settings: Settings, meeting_id: str) -> Path:
    """返回会议的本地目录；调用方不得把该路径放进 API 响应。"""
    return settings.data_dir / "meetings" / meeting_id


def save_stream(
    settings: Settings,
    meeting_id: str,
    filename: str | None,
    stream: BinaryIO,
) -> SavedUpload:
    raw_dir = meeting_dir(settings, meeting_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 浏览器文件名不可信，同时兼容 POSIX 与 Windows 风格的路径。
    safe_filename = Path((filename or "").replace("\\", "/")).name or "audio"
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
