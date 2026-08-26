"""串行模型槽：16GB 机器上同一时刻只允许一个模型驻留。

用法：
    slot = SingleModelSlot()
    with slot.use(asr) as backend:
        backend.transcribe(...)
    with slot.use(diar) as backend:   # 进入前 asr 已被卸载
        backend.diarize(...)

并发语义：
- 同一线程嵌套占槽是编程错误，立即抛 ModelSlotBusy；
- 跨线程抢槽（如 HTTP 提交决定入库声纹时 worker 正在转写）排队等待，
  槽空出后再加载，绝不同时驻留两个模型。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol


class LoadableModel(Protocol):
    name: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...


class ModelSlotBusy(Exception):
    pass


class SingleModelSlot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: LoadableModel | None = None
        self._owner_thread: int | None = None

    @property
    def current_name(self) -> str | None:
        return self._current.name if self._current is not None else None

    @contextmanager
    def use(self, backend: Any) -> Iterator[Any]:
        if self._owner_thread == threading.get_ident():
            occupant = self.current_name or "未知模型"
            raise ModelSlotBusy(
                f"模型槽被 {occupant} 占用，不允许同时加载 {backend.name}"
            )
        with self._lock:
            self._owner_thread = threading.get_ident()
            try:
                backend.load()
                self._current = backend
                try:
                    yield backend
                finally:
                    backend.unload()
                    self._current = None
            finally:
                self._owner_thread = None
