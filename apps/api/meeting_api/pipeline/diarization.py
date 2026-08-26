from __future__ import annotations

import sys
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
        # 每簇至少留 2 段，确认停点才凑得齐 2–3 个试听片段。
        return [
            SpeakerSegment(float(i * 5), float(i * 5 + 5), f"S{i % n + 1}")
            for i in range(max(4, 2 * n))
        ]


class SherpaOnnxDiarizationBackend:
    """从本地 ONNX 文件加载 sherpa-onnx 离线说话人切分。"""

    name = "sherpa-onnx-diarization"
    model_subdir = Path("sherpa-onnx")

    def __init__(self, models_dir: Path = Path("data/models")) -> None:
        self.model_dir = models_dir / self.model_subdir
        self.segmentation_path = self.model_dir / "segmentation.onnx"
        self.embedding_path = self.model_dir / "embedding.onnx"
        self._model = None

    def load(self) -> None:
        _require_darwin(self.name)
        missing = [
            path.name
            for path in (self.segmentation_path, self.embedding_path)
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                f"sherpa-onnx 切分模型文件不完整；请按 scripts/download_models.md 把模型放到 "
                f"{self.model_dir}/（需要 segmentation.onnx 和 embedding.onnx）"
            )
        import sherpa_onnx

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(self.segmentation_path), window_shift_ratio=0.1
                )
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.embedding_path)
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=-1, threshold=0.5
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError(f"sherpa-onnx 切分模型配置无效，请检查 {self.model_dir}/")
        self._model = sherpa_onnx.OfflineSpeakerDiarization(config)

    def unload(self) -> None:
        if self._model is not None and hasattr(self._model, "close"):
            self._model.close()
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def diarize(
        self, audio_path: Path, expected_speakers: int | None = None
    ) -> list[SpeakerSegment]:
        if self._model is None:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        import numpy as np
        import soundfile as sf

        audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        samples = np.ascontiguousarray(audio[:, 0])
        target_rate = self._model.sample_rate
        if sample_rate != target_rate:
            sample_count = round(len(samples) * target_rate / sample_rate)
            samples = np.interp(
                np.linspace(0, len(samples), sample_count, endpoint=False),
                np.arange(len(samples)),
                samples,
            ).astype("float32")
        # expected_speakers 是提示而不是硬凑；模型加载配置默认自动聚类。
        del expected_speakers
        result = self._model.process(samples).sort_by_start_time()
        return [
            SpeakerSegment(float(item.start), float(item.end), f"S{int(item.speaker) + 1}")
            for item in result
        ]


def _require_darwin(backend_name: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError(f"真实后端 {backend_name} 仅支持 macOS；当前平台请使用 fake")


def get_diarization_backend(
    name: str = "fake", models_dir: Path = Path("data/models")
) -> DiarizationBackend:
    if name == "fake":
        return FakeDiarizationBackend()
    if name == "sherpa-onnx":
        _require_darwin(name)
        return SherpaOnnxDiarizationBackend(models_dir)
    raise ValueError(f"未知 diarization 后端: {name}")
