from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AsrSegment:
    start: float  # 秒
    end: float
    text: str


class AsrBackend(Protocol):
    name: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...

    def transcribe(self, audio_path: Path, hotwords: Sequence[str] = ()) -> list[AsrSegment]: ...


class FakeAsrBackend:
    """假转写：返回固定片段；hotwords 原样拼进文本，方便测词库快照生效。"""

    name = "fake-asr"

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def transcribe(self, audio_path: Path, hotwords: Sequence[str] = ()) -> list[AsrSegment]:
        if not self._loaded:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        suffix = f"（热词: {'、'.join(hotwords)}）" if hotwords else ""
        return [
            AsrSegment(0.0, 5.0, f"这是 {audio_path.name} 的假转写第一段{suffix}"),
            AsrSegment(5.0, 10.0, "这是假转写第二段"),
        ]


def get_asr_backend(name: str = "fake") -> AsrBackend:
    if name == "fake":
        return FakeAsrBackend()
    if name == "qwen3-asr-mlx":
        # M11：仅 macOS/Apple Silicon，接 MLX 版 Qwen3-ASR-1.7B。此前一律 fake。
        raise NotImplementedError("qwen3-asr-mlx 在 M11 接入（仅 macOS），当前请用 fake")
    raise ValueError(f"未知 ASR 后端: {name}")
