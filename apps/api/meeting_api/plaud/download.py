"""把 Plaud 预签名直链的音频流式落到会议目录。

预签名链接 24 小时有效、只允许 GET（HEAD 返回 403），所以不做预检，
直接 GET 并把响应对象喂给 storage.save_stream，全程不把整段音频读进内存。
socket 超时防单次读卡死，另有一个总时长守卫防「一直慢慢滴水」。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from meeting_api.config import Settings
from meeting_api.disk import ensure_disk_space
from meeting_api.plaud.errors import PlaudError, PlaudTimeoutError
from meeting_api.storage import SavedUpload, save_stream

SOCKET_TIMEOUT_SECONDS = 60.0
DEFAULT_AUDIO_SUFFIX = ".mp3"
# 进度回调的最小步进：save_stream 每次读 1 MiB，这个阈值等于「每块都报」，
# 但换成更小的读块时也不会把回调打爆。
PROGRESS_REPORT_BYTES = 256 * 1024
# 只有 fake 后端才放行 file://：真实通道必须是 Plaud 的 https 直链。
_REAL_SCHEMES = frozenset({"http", "https"})
_FAKE_SCHEMES = frozenset({"http", "https", "file"})

# (已下载字节, Content-Length 或 None)
ProgressCallback = Callable[[int, int | None], None]


def filename_from_url(url: str, fallback_stem: str) -> str:
    """取 URL 路径的 basename（如 <file_id>.mp3）；没有扩展名就补 .mp3。"""
    raw = urllib.parse.urlparse(url).path
    name = Path(raw.replace("\\", "/")).name
    if name in {"", ".", ".."} or "\x00" in name:
        name = fallback_stem
    if not Path(name).suffix:
        name = f"{name}{DEFAULT_AUDIO_SUFFIX}"
    return name


class _DeadlineReader:
    """给 save_stream 用的只读包装：每次读之前检查总时长，顺便统一异常。

    每次读都过这里，所以字节计数与进度回调也搭在这上面：按 PROGRESS_REPORT_BYTES
    步进上报，读到 EOF 时必定再报一次最终值。
    """

    def __init__(
        self,
        stream: BinaryIO,
        deadline: float,
        *,
        on_progress: ProgressCallback | None = None,
        expected_bytes: int | None = None,
    ) -> None:
        self._stream = stream
        self._deadline = deadline
        self._on_progress = on_progress
        self._expected_bytes = expected_bytes
        self._bytes_done = 0
        self._reported_bytes = 0

    def read(self, size: int = -1) -> bytes:
        if time.monotonic() > self._deadline:
            raise PlaudTimeoutError("下载 Plaud 录音超时")
        try:
            chunk = self._stream.read(size)
        except TimeoutError as exc:
            raise PlaudTimeoutError("下载 Plaud 录音超时") from exc
        except OSError as exc:
            raise PlaudError(f"下载 Plaud 录音失败：{exc}") from exc
        self._bytes_done += len(chunk)
        self._report(final=not chunk)
        return chunk

    def _report(self, *, final: bool) -> None:
        if self._on_progress is None:
            return
        if not final and self._bytes_done - self._reported_bytes < PROGRESS_REPORT_BYTES:
            return
        self._reported_bytes = self._bytes_done
        self._on_progress(self._bytes_done, self._expected_bytes)


def download_to_meeting(
    settings: Settings,
    meeting_id: str,
    url: str,
    filename: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> SavedUpload:
    allowed = _FAKE_SCHEMES if settings.plaud_backend == "fake" else _REAL_SCHEMES
    if urllib.parse.urlparse(url).scheme not in allowed:
        raise PlaudError("录音下载地址不合法")

    deadline = time.monotonic() + settings.plaud_download_timeout_seconds
    try:
        response = urllib.request.urlopen(url, timeout=SOCKET_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise PlaudError(f"下载 Plaud 录音失败：HTTP {exc.code}") from exc
    except TimeoutError as exc:
        raise PlaudTimeoutError("下载 Plaud 录音超时") from exc
    except OSError as exc:
        raise PlaudError(f"下载 Plaud 录音失败：{exc}") from exc

    with response:
        expected_bytes = _content_length(response)
        if expected_bytes is not None:
            # 开始写盘前先按声明大小做与上传同一套的余量校验（同样的 422 文案）。
            ensure_disk_space(settings, expected_bytes)
        reader: BinaryIO = _DeadlineReader(  # type: ignore[assignment]
            response,
            deadline,
            on_progress=on_progress,
            expected_bytes=expected_bytes,
        )
        return save_stream(settings, meeting_id, filename, reader)


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    raw = headers.get("Content-Length") if headers is not None else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
