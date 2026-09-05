"""落盘前的磁盘余量校验：上传与 Plaud 下载共用同一套阈值与文案。"""

from __future__ import annotations

import shutil
from collections.abc import Mapping

from fastapi import HTTPException, status

from meeting_api.config import Settings


def ensure_disk_space(
    settings: Settings,
    upload_size: int,
    *,
    headers: Mapping[str, str] | None = None,
) -> None:
    free_bytes = shutil.disk_usage(settings.data_dir).free
    required_bytes = upload_size + settings.upload_disk_reserve_bytes
    if free_bytes < required_bytes:
        free_gib = free_bytes / 1024**3
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"磁盘空间不足，还剩 {free_gib:.2f} GB",
            headers=headers,
        )
