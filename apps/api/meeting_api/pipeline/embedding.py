from __future__ import annotations

import hashlib
import struct
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

EmbeddingVector = tuple[float, ...]
# 一个簇内的声纹提取时间窗（秒）；与确认停点的试听片段共用同一批窗口。
TimeWindow = tuple[float, float]


class EmbeddingBackend(Protocol):
    name: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...

    def embed(self, audio_path: Path, windows: Sequence[TimeWindow]) -> EmbeddingVector: ...


class FakeEmbeddingBackend:
    """只按时间窗生成确定性向量；不读取音频，也不调用真实模型。

    向量各维居中到 [-1, 1]：不同窗口的向量近似正交（余弦≈0），
    同一批窗口的向量完全一致（余弦=1），这样余弦阈值规则可被 fake 覆盖。
    """

    name = "fake-embedding"

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def embed(self, audio_path: Path, windows: Sequence[TimeWindow]) -> EmbeddingVector:
        del audio_path
        if not self._loaded:
            raise RuntimeError("声纹后端未加载（先 load()）")
        if not windows:
            raise ValueError("声纹提取需要至少一个时间窗")
        key = "|".join(f"{start:.3f}-{end:.3f}" for start, end in windows)
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return tuple(byte / 127.5 - 1.0 for byte in digest)


def embedding_to_bytes(vector: EmbeddingVector) -> bytes:
    """使用固定大端 float32 编码存 SQLite BLOB；读回用 embedding_from_bytes。"""
    return struct.pack(f">{len(vector)}f", *vector)


def embedding_from_bytes(blob: bytes) -> EmbeddingVector:
    count = len(blob) // 4
    return tuple(struct.unpack(f">{count}f", blob[: count * 4]))


class SherpaOnnxEmbeddingBackend:
    """从本地 ONNX 文件加载 sherpa-onnx 声纹提取器。"""

    name = "sherpa-onnx-embedding"
    model_subdir = Path("sherpa-onnx")

    def __init__(self, models_dir: Path = Path("data/models")) -> None:
        self.model_path = models_dir / self.model_subdir / "embedding.onnx"
        self._model = None

    def load(self) -> None:
        _require_darwin(self.name)
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"sherpa-onnx 声纹模型文件不存在；请按 scripts/download_models.md 把模型放到 "
                f"{self.model_path}"
            )
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.model_path))
        if not config.validate():
            raise RuntimeError(f"sherpa-onnx 声纹模型配置无效，请检查 {self.model_path.parent}/")
        self._model = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def unload(self) -> None:
        if self._model is not None and hasattr(self._model, "close"):
            self._model.close()
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def embed(self, audio_path: Path, windows: Sequence[TimeWindow]) -> EmbeddingVector:
        """对簇内各时间窗分别提声纹后求均值。

        整场音频只提一个向量会把整场当成同一个人的声纹；声纹必须来自
        该簇自己的发言片段。模型判定太短的窗口跳过，全部不可用才报错。
        """
        if self._model is None:
            raise RuntimeError("声纹后端未加载（先 load()）")
        if not windows:
            raise ValueError("声纹提取需要至少一个时间窗")
        import numpy as np
        import soundfile as sf

        audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        samples = np.ascontiguousarray(audio[:, 0])
        vectors: list[np.ndarray] = []
        for start, end in windows:
            lo = max(0, int(start * sample_rate))
            hi = min(len(samples), int(end * sample_rate))
            if hi <= lo:
                continue
            stream = self._model.create_stream()
            stream.accept_waveform(
                sample_rate=sample_rate,
                waveform=np.ascontiguousarray(samples[lo:hi]),
            )
            stream.input_finished()
            if not self._model.is_ready(stream):
                continue
            vectors.append(np.asarray(self._model.compute(stream), dtype=np.float64))
        if not vectors:
            raise RuntimeError("簇内片段都太短，无法提取声纹")
        mean = np.mean(vectors, axis=0)
        return tuple(float(value) for value in mean)


def _require_darwin(backend_name: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError(f"真实后端 {backend_name} 仅支持 macOS；当前平台请使用 fake")


def get_embedding_backend(
    name: str = "fake", models_dir: Path = Path("data/models")
) -> EmbeddingBackend:
    if name == "auto":
        model_path = (
            models_dir / SherpaOnnxEmbeddingBackend.model_subdir / "embedding.onnx"
        )
        if sys.platform == "darwin" and model_path.is_file():
            return SherpaOnnxEmbeddingBackend(models_dir)
        return FakeEmbeddingBackend()
    if name == "fake":
        return FakeEmbeddingBackend()
    if name == "sherpa-onnx":
        _require_darwin(name)
        return SherpaOnnxEmbeddingBackend(models_dir)
    raise ValueError(f"未知声纹后端: {name}")
