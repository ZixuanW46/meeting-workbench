from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SpeakerSegment:
    start: float  # 秒
    end: float
    cluster_id: str  # 本场内的说话人簇代号，如 "S1"


class DiarizationBackend(Protocol):
    name: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...

    def diarize(
        self, audio_path: Path, expected_speakers: int | None = None
    ) -> list[SpeakerSegment]: ...


class FakeDiarizationBackend:
    """假切分：按 expected_speakers（默认 2）轮流产出簇。人数只是先验，不硬凑。"""

    name = "fake-diarization"

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def diarize(
        self, audio_path: Path, expected_speakers: int | None = None
    ) -> list[SpeakerSegment]:
        if not self._loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        n = expected_speakers or 2
        return [
            SpeakerSegment(float(i * 5), float(i * 5 + 5), f"S{i % n + 1}")
            for i in range(4)
        ]


def get_diarization_backend(name: str = "fake") -> DiarizationBackend:
    if name == "fake":
        return FakeDiarizationBackend()
    if name == "sherpa-onnx":
        # M11：接 sherpa-onnx 切分 + 声纹。此前一律 fake。
        raise NotImplementedError("sherpa-onnx 在 M11 接入，当前请用 fake")
    raise ValueError(f"未知 diarization 后端: {name}")
