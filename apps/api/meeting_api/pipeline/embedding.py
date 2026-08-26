from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Protocol

EmbeddingVector = tuple[float, ...]


class EmbeddingBackend(Protocol):
    name: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...

    def embed(self, audio_path: Path, cluster_id: str) -> EmbeddingVector: ...


class FakeEmbeddingBackend:
    """只按簇 id 生成确定性向量；不读取音频，也不调用真实模型。"""

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

    def embed(self, audio_path: Path, cluster_id: str) -> EmbeddingVector:
        del audio_path
        if not self._loaded:
            raise RuntimeError("声纹后端未加载（先 load()）")
        digest = hashlib.sha256(cluster_id.encode("utf-8")).digest()
        return tuple(byte / 255.0 for byte in digest[:8])


def embedding_to_bytes(vector: EmbeddingVector) -> bytes:
    """使用固定大端 float32 编码，便于 SQLite BLOB 做确定性 fake 匹配。"""
    return struct.pack(f">{len(vector)}f", *vector)


def get_embedding_backend(name: str = "fake") -> EmbeddingBackend:
    if name == "fake":
        return FakeEmbeddingBackend()
    raise ValueError(f"未知声纹后端: {name}")
