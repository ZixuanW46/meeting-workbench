from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SpeakerSegment:
    start: float  # 秒
    end: float
    cluster_id: str  # 本场内的说话人簇代号，如 "S1"


# 总时长低于该值的簇撑不起人工试听判断，视为切分噪声（笑声、插话、拖尾）。
FRAGMENT_CLUSTER_MAX_SECONDS = 3.0

# 簇级声纹二次合并阈值（余弦距离，平均连接）。真机 27 分钟多人闲聊实测：
# sherpa 自动聚类把同一真人撕成多个主簇，同人主簇的均值声纹距离 ≤0.39，
# 不同真人 ≥0.63；取空隙的保守侧——停点误并不可拆，误拆还能手工合并。
CLUSTER_MERGE_MAX_DISTANCE = 0.4

# 每簇声纹取样：优先最长片段；有像样长段时 <0.5s 残段不取（质量差拉脏均值），
# 全簇都是残段则保底取最长一段；总量至多 6 段 / 20 秒。
EMBEDDING_SPAN_MIN_SECONDS = 0.5
EMBEDDING_SPAN_MAX_COUNT = 6
EMBEDDING_SPAN_MAX_TOTAL_SECONDS = 20.0


def pick_embedding_spans(
    segments: Sequence[SpeakerSegment],
) -> list[tuple[float, float]]:
    """从一个簇的片段里挑出用于提取簇声纹的时间窗。"""
    picked: list[tuple[float, float]] = []
    budget = EMBEDDING_SPAN_MAX_TOTAL_SECONDS
    ordered = sorted(
        segments, key=lambda segment: segment.end - segment.start, reverse=True
    )
    for segment in ordered:
        duration = segment.end - segment.start
        if duration < EMBEDDING_SPAN_MIN_SECONDS and picked:
            break
        picked.append((segment.start, segment.end))
        budget -= duration
        if budget <= 0 or len(picked) >= EMBEDDING_SPAN_MAX_COUNT:
            break
    return picked


def merge_similar_clusters(
    segments: Sequence[SpeakerSegment],
    embeddings: Mapping[str, Sequence[float]],
    *,
    max_distance: float = CLUSTER_MERGE_MAX_DISTANCE,
) -> list[SpeakerSegment]:
    """把均值声纹足够近的簇并成一个（平均连接层次合并）。

    只在有声纹证据时换簇标签：没提出声纹的簇原样保留，时间轴永远不动，
    也不做任何身份判断——身份仍只能来自用户在确认停点的决定。
    """
    if not segments:
        return []
    normalized: dict[str, tuple[float, ...]] = {}
    for cluster_id, vector in embeddings.items():
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            normalized[cluster_id] = tuple(value / norm for value in vector)
    if len(normalized) < 2:
        return list(segments)

    def distance(left: str, right: str) -> float:
        paired = zip(normalized[left], normalized[right], strict=True)
        return 1.0 - sum(a * b for a, b in paired)

    groups = [[cluster_id] for cluster_id in sorted(normalized)]
    while len(groups) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                pairs = [(a, b) for a in groups[i] for b in groups[j]]
                group_distance = sum(distance(a, b) for a, b in pairs) / len(pairs)
                if best is None or group_distance < best[0]:
                    best = (group_distance, i, j)
        assert best is not None  # len(groups) > 1 时必有候选
        if best[0] > max_distance:
            break
        _, i, j = best
        groups[i] += groups[j]
        del groups[j]

    totals: dict[str, float] = {}
    for segment in segments:
        totals[segment.cluster_id] = (
            totals.get(segment.cluster_id, 0.0) + segment.end - segment.start
        )
    relabel: dict[str, str] = {}
    for group in groups:
        anchor = min(group, key=lambda cid: (-totals.get(cid, 0.0), cid))
        for member in group:
            if member != anchor:
                relabel[member] = anchor
    if not relabel:
        return list(segments)
    return [
        segment
        if segment.cluster_id not in relabel
        else SpeakerSegment(segment.start, segment.end, relabel[segment.cluster_id])
        for segment in segments
    ]


def consolidate_fragment_clusters(
    segments: Sequence[SpeakerSegment],
    *,
    min_cluster_seconds: float = FRAGMENT_CLUSTER_MAX_SECONDS,
) -> list[SpeakerSegment]:
    """把总时长过短的碎簇并入时间上最近的主簇。

    真实音频的自动聚类几乎必产亚秒碎簇，曾让确认包准备整场 FAILED。
    这里只重排时间轴上的簇标签，不做任何身份判断——身份仍只能来自用户
    在确认停点的决定；总时长达标的单次发言者会原样保留。
    """
    if not segments:
        return []
    totals: dict[str, float] = {}
    for segment in segments:
        totals[segment.cluster_id] = (
            totals.get(segment.cluster_id, 0.0) + segment.end - segment.start
        )
    majors = {
        cluster_id
        for cluster_id, total in totals.items()
        if total >= min_cluster_seconds
    }
    if not majors:
        # 全是碎簇的极端输入：留总时长最大的当锚，保证停点仍有簇可确认。
        majors = {max(totals, key=lambda cluster_id: (totals[cluster_id], cluster_id))}
    major_segments = [
        segment for segment in segments if segment.cluster_id in majors
    ]

    def nearest_major_id(fragment: SpeakerSegment) -> str:
        def gap(candidate: SpeakerSegment) -> float:
            if candidate.end < fragment.start:
                return fragment.start - candidate.end
            if fragment.end < candidate.start:
                return candidate.start - fragment.end
            return 0.0

        best = min(
            major_segments,
            key=lambda candidate: (
                gap(candidate),
                -totals[candidate.cluster_id],
                candidate.cluster_id,
            ),
        )
        return best.cluster_id

    return [
        segment
        if segment.cluster_id in majors
        else SpeakerSegment(segment.start, segment.end, nearest_major_id(segment))
        for segment in segments
    ]


def merge_adjacent_turns(
    segments: Sequence[SpeakerSegment],
    *,
    max_gap_seconds: float = 1.0,
) -> list[SpeakerSegment]:
    """把时间上连续的同簇片段并成发言轮次，供整段转写按轮次重切。"""
    ordered = sorted(segments, key=lambda segment: (segment.start, segment.end))
    turns: list[SpeakerSegment] = []
    for segment in ordered:
        if (
            turns
            and turns[-1].cluster_id == segment.cluster_id
            and segment.start - turns[-1].end <= max_gap_seconds
        ):
            turns[-1] = SpeakerSegment(
                turns[-1].start,
                max(turns[-1].end, segment.end),
                segment.cluster_id,
            )
        else:
            turns.append(segment)
    return turns


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
        # 二次合并用的簇声纹提取器：与切分共用同一份 embedding.onnx，
        # 同属切分槽的生命周期，不违反 16GB 单模型串行约束。
        self._extractor = None

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
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.embedding_path))
        )

    def unload(self) -> None:
        if self._model is not None and hasattr(self._model, "close"):
            self._model.close()
        self._model = None
        if self._extractor is not None and hasattr(self._extractor, "close"):
            self._extractor.close()
        self._extractor = None

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
        segments = [
            SpeakerSegment(float(item.start), float(item.end), f"S{int(item.speaker) + 1}")
            for item in result
        ]
        # sherpa 在长录音上会把同一真人撕成多个主簇（27 分钟实测 92 簇），
        # 用簇均值声纹做一次保守二次合并，再交给 worker 的碎簇时间就近合并。
        return merge_similar_clusters(
            segments, self._cluster_embeddings(samples, target_rate, segments)
        )

    def _cluster_embeddings(
        self, samples, sample_rate: int, segments: Sequence[SpeakerSegment]
    ) -> dict[str, tuple[float, ...]]:
        """对每个簇的代表片段提声纹，按片段时长加权平均出簇均值声纹。"""
        by_cluster: dict[str, list[SpeakerSegment]] = {}
        for segment in segments:
            by_cluster.setdefault(segment.cluster_id, []).append(segment)

        vectors: dict[str, tuple[float, ...]] = {}
        for cluster_id, members in sorted(by_cluster.items()):
            weighted: list[float] | None = None
            weight_total = 0.0
            for start, end in pick_embedding_spans(members):
                piece = samples[int(start * sample_rate) : int(end * sample_rate)]
                if len(piece) < int(0.3 * sample_rate):
                    continue
                stream = self._extractor.create_stream()
                stream.accept_waveform(sample_rate=sample_rate, waveform=piece)
                stream.input_finished()
                if not self._extractor.is_ready(stream):
                    continue
                vector = [float(value) for value in self._extractor.compute(stream)]
                norm = math.sqrt(sum(value * value for value in vector))
                if norm <= 0:
                    continue
                weight = end - start
                scaled = [value / norm * weight for value in vector]
                weighted = (
                    scaled
                    if weighted is None
                    else [a + b for a, b in zip(weighted, scaled, strict=True)]
                )
                weight_total += weight
            if weighted is not None and weight_total > 0:
                vectors[cluster_id] = tuple(value / weight_total for value in weighted)
        return vectors


def _require_darwin(backend_name: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError(f"真实后端 {backend_name} 仅支持 macOS；当前平台请使用 fake")


def get_diarization_backend(
    name: str = "fake", models_dir: Path = Path("data/models")
) -> DiarizationBackend:
    if name == "auto":
        model_dir = models_dir / SherpaOnnxDiarizationBackend.model_subdir
        if sys.platform == "darwin" and all(
            (model_dir / filename).is_file()
            for filename in ("segmentation.onnx", "embedding.onnx")
        ):
            return SherpaOnnxDiarizationBackend(models_dir)
        return FakeDiarizationBackend()
    if name == "fake":
        return FakeDiarizationBackend()
    if name == "sherpa-onnx":
        _require_darwin(name)
        return SherpaOnnxDiarizationBackend(models_dir)
    raise ValueError(f"未知 diarization 后端: {name}")
