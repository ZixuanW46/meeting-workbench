"""串行模型槽：16GB 机器上同一时刻只允许一个模型驻留。

用法：
    slot = SingleModelSlot()
    with slot.use(asr) as backend:
        backend.transcribe(...)
    with slot.use(diar) as backend:   # 进入前 asr 已被卸载
        backend.diarize(...)
"""

from __future__ import annotations

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
        self._current: LoadableModel | None = None

    @property
    def current_name(self) -> str | None:
        return self._current.name if self._current is not None else None

    @contextmanager
    def use(self, backend: Any) -> Iterator[Any]:
        if self._current is not None:
            raise ModelSlotBusy(
                f"模型槽被 {self._current.name} 占用，不允许同时加载 {backend.name}"
            )
        backend.load()
        self._current = backend
        try:
            yield backend
        finally:
            backend.unload()
            self._current = None
