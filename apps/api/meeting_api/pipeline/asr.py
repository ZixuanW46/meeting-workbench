from __future__ import annotations

import sys
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


class Qwen3AsrMlxBackend:
    """从本地目录加载 mlx-audio 的 Qwen3-ASR；不会联网下载模型。"""

    name = "qwen3-asr-mlx"
    model_subdir = Path("qwen3-asr-mlx")

    def __init__(self, models_dir: Path = Path("data/models")) -> None:
        self.model_dir = models_dir / self.model_subdir
        self._model = None
        self._mlx = None

    def load(self) -> None:
        _require_darwin(self.name)
        if not (self.model_dir / "config.json").is_file():
            raise FileNotFoundError(
                "Qwen3-ASR 模型文件不完整；请把模型放到 "
                "data/models/qwen3-asr-mlx/（至少包含 config.json）"
            )
        # macOS 专属依赖只能在真正加载时导入，Linux/CI 默认 fake 不触碰它们。
        import mlx.core as mx
        from mlx_audio.stt import load

        self._model = load(str(self.model_dir))
        self._mlx = mx

    def unload(self) -> None:
        self._model = None
        if self._mlx is not None:
            self._mlx.clear_cache()
            self._mlx = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_path: Path, hotwords: Sequence[str] = ()) -> list[AsrSegment]:
        if self._model is None:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        # mlx-audio 当前没有独立 hotwords 参数；快照仍由 worker 固定并传入，
        # 后端升级支持提示词时可在这里接入，不能把数据发往云端。
        del hotwords
        result = self._model.generate(str(audio_path), language="Chinese")
        segments = getattr(result, "segments", None) or []
        if segments:
            return [
                AsrSegment(
                    float(segment["start"]),
                    float(segment["end"]),
                    str(segment["text"]),
                )
                for segment in segments
            ]
        text = str(getattr(result, "text", "")).strip()
        return [AsrSegment(0.0, 1.0, text)] if text else []


def _require_darwin(backend_name: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError(f"真实后端 {backend_name} 仅支持 macOS；当前平台请使用 fake")


def get_asr_backend(
    name: str = "fake", models_dir: Path = Path("data/models")
) -> AsrBackend:
    if name == "fake":
        return FakeAsrBackend()
    if name == "qwen3-asr-mlx":
        _require_darwin(name)
        return Qwen3AsrMlxBackend(models_dir)
    raise ValueError(f"未知 ASR 后端: {name}")
