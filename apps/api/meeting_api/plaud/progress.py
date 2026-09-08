"""Plaud 导入的进程内下载进度。

POST /api/plaud/import 是同步的：整段音频在 handler 里下载完才返回 201。
前端在这期间轮询 GET /api/plaud/import-progress/{file_id} 拿实时字节数，
所以这里只需要一份「与请求同生命周期」的内存状态，不落库、不跨进程。

handler 跑在 anyio 线程池里，写入必须自带锁。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

ImportPhase = Literal["resolving", "downloading", "finalizing", "done", "failed"]

# done / failed 之后再留一会儿：POST 返回后前端还会再轮询一次，
# 那一次必须看到终态而不是 404。
RETENTION_SECONDS = 120.0
# 兜底：进程被硬杀等极端情况留下的「永远在下载」的条目也要能回收。
STALE_SECONDS = 3600.0

_TERMINAL_PHASES = frozenset({"done", "failed"})


@dataclass(frozen=True, slots=True)
class ImportProgress:
    file_id: str
    phase: ImportPhase
    bytes_done: int = 0
    # Content-Length；上游没给就是 None（前端只好显示不确定进度）。
    bytes_total: int | None = None
    meeting_id: str | None = None
    error: str | None = None
    updated_at: float = 0.0


class ImportProgressRegistry:
    """按 plaud_file_id 记录导入进度；读写都加锁，过期条目在访问时惰性清理。"""

    def __init__(
        self,
        *,
        retention_seconds: float = RETENTION_SECONDS,
        stale_seconds: float = STALE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._retention_seconds = retention_seconds
        self._stale_seconds = stale_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, ImportProgress] = {}

    def start(self, file_id: str) -> ImportProgress:
        """开一条新记录（覆盖同一录音的上一次导入）。"""
        entry = ImportProgress(file_id=file_id, phase="resolving", updated_at=self._clock())
        with self._lock:
            self._evict_locked()
            self._entries[file_id] = entry
        return entry

    def update(self, file_id: str, **fields: object) -> ImportProgress | None:
        """更新在途记录；条目已被清理（或从未 start）就当无事发生。"""
        with self._lock:
            return self._replace_locked(file_id, fields)

    def finish(self, file_id: str, meeting_id: str) -> ImportProgress | None:
        with self._lock:
            return self._replace_locked(
                file_id, {"phase": "done", "meeting_id": meeting_id, "error": None}
            )

    def fail(self, file_id: str, error: str) -> ImportProgress | None:
        with self._lock:
            return self._replace_locked(file_id, {"phase": "failed", "error": error})

    def get(self, file_id: str) -> ImportProgress | None:
        with self._lock:
            self._evict_locked()
            return self._entries.get(file_id)

    def _replace_locked(
        self, file_id: str, fields: dict[str, object]
    ) -> ImportProgress | None:
        self._evict_locked()
        current = self._entries.get(file_id)
        if current is None:
            return None
        updated = replace(current, updated_at=self._clock(), **fields)  # type: ignore[arg-type]
        self._entries[file_id] = updated
        return updated

    def _evict_locked(self) -> None:
        now = self._clock()
        for file_id in [
            file_id
            for file_id, entry in self._entries.items()
            if self._expired(entry, now)
        ]:
            del self._entries[file_id]

    def _expired(self, entry: ImportProgress, now: float) -> bool:
        age = now - entry.updated_at
        if entry.phase in _TERMINAL_PHASES:
            return age > self._retention_seconds
        return age > self._stale_seconds
