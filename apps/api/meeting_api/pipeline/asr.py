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

    def transcribe(
        self,
        audio_path: Path,
        hotwords: Sequence[str] = (),
        language: str = "zh",
    ) -> list[AsrSegment]: ...


# 会议语言到 Qwen3-ASR 语言名的映射；未知语言按中文处理。
LANGUAGE_NAMES = {"zh": "Chinese", "en": "English"}

# 单块音频时长上限（秒）。mlx-audio 默认 1200s，而 MLX 峰值内存随块长涨
# （真机实测 2 分钟 3.9 GB / 10 分钟 7.6 GB / 20 分钟 12.4 GB），
# 16GB 机器必须切小；实际值由 Settings.asr_chunk_seconds 决定。
DEFAULT_CHUNK_SECONDS = 300.0


class FakeAsrBackend:
    """假转写：返回固定片段；hotwords 与非中文语言标记原样拼进文本，便于断言。"""

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

    def transcribe(
        self,
        audio_path: Path,
        hotwords: Sequence[str] = (),
        language: str = "zh",
    ) -> list[AsrSegment]:
        if not self._loaded:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        suffix = f"（热词: {'、'.join(hotwords)}）" if hotwords else ""
        if language != "zh":
            suffix += f"（语言: {language}）"
        return [
            AsrSegment(0.0, 5.0, f"这是 {audio_path.name} 的假转写第一段{suffix}"),
            AsrSegment(5.0, 10.0, "这是假转写第二段"),
        ]


class Qwen3AsrMlxBackend:
    """从本地目录加载 mlx-audio 的 Qwen3-ASR；不会联网下载模型。"""

    name = "qwen3-asr-mlx"
    model_subdir = Path("qwen3-asr-mlx")

    def __init__(
        self,
        models_dir: Path = Path("data/models"),
        *,
        chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    ) -> None:
        self.model_dir = models_dir / self.model_subdir
        self.chunk_seconds = chunk_seconds
        self._model = None
        self._mlx = None

    def load(self) -> None:
        _require_darwin(self.name)
        if not (self.model_dir / "config.json").is_file():
            raise FileNotFoundError(
                f"Qwen3-ASR 模型文件不完整；请按 scripts/download_models.md 把模型放到 "
                f"{self.model_dir}/（至少包含 config.json）"
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

    def transcribe(
        self,
        audio_path: Path,
        hotwords: Sequence[str] = (),
        language: str = "zh",
    ) -> list[AsrSegment]:
        if self._model is None:
            raise RuntimeError("ASR 后端未加载（先 load()）")
        # mlx-audio 的 Qwen3-ASR 提供官方 hotwords 参数（折进 system_prompt 做偏置）；
        # 快照由 worker 固定并传入，全程只在本机推理，不把数据发往云端。
        # chunk_duration 决定单块音频有多长，也就决定了 MLX 的峰值内存上限。
        result = self._model.generate(
            str(audio_path),
            language=LANGUAGE_NAMES.get(language, "Chinese"),
            hotwords=list(hotwords) or None,
            chunk_duration=self.chunk_seconds,
        )
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
    name: str = "fake",
    models_dir: Path = Path("data/models"),
    *,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
) -> AsrBackend:
    """按名字取 ASR 后端；chunk_seconds 只对真实后端有意义，fake 不分块。"""
    if name == "auto":
        if sys.platform == "darwin" and (
            models_dir / Qwen3AsrMlxBackend.model_subdir / "config.json"
        ).is_file():
            return Qwen3AsrMlxBackend(models_dir, chunk_seconds=chunk_seconds)
        return FakeAsrBackend()
    if name == "fake":
        return FakeAsrBackend()
    if name == "qwen3-asr-mlx":
        _require_darwin(name)
        return Qwen3AsrMlxBackend(models_dir, chunk_seconds=chunk_seconds)
    raise ValueError(f"未知 ASR 后端: {name}")
