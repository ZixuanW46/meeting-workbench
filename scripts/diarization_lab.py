"""离线切分聚类对比实验（仅限放好真实模型的 macOS 真机手动运行）。

用同一段真实录音对比几条候选路线，给「确认停点卡片数不可用」的修复选型提供数据：

1. sherpa FastClustering 的 threshold 扫描（每个值完整跑一遍切分管线，结果落盘缓存）；
2. 二次合并：对基线（threshold=0.5）产出的簇提取均值声纹，按余弦距离做平均连接层次合并；
3. 时长 Top-K：只留时长最大的 K 个主簇，其余并入时间上最近的主簇（等价于把
   consolidate_fragment_clusters 的时长阈值抬到第 K 大簇的时长）。

用法（在仓库根目录）：
    .venv/bin/python scripts/diarization_lab.py data/meetings/<id>/raw/xxx.wav --out /tmp/lab

输出：--out 目录下每个 threshold 一份 segments JSON（重复运行直接复用缓存）、
基线簇声纹 JSON，以及 stdout 的 markdown 对比报告。本脚本只做实验，不改任何产品行为。
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 实验脚本直接复用产品代码里的碎簇合并逻辑，保证模拟口径一致。
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "domain"))


@dataclass(frozen=True)
class Seg:
    start: float
    end: float
    cluster_id: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def load_audio(path: Path, target_rate: int) -> object:
    """与 SherpaOnnxDiarizationBackend.diarize 相同的读取与重采样口径。"""
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    samples = np.ascontiguousarray(audio[:, 0])
    if sample_rate != target_rate:
        sample_count = round(len(samples) * target_rate / sample_rate)
        samples = np.interp(
            np.linspace(0, len(samples), sample_count, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype("float32")
    return samples


def run_sherpa(samples: object, models_dir: Path, threshold: float) -> tuple[list[Seg], float]:
    """按产品同款配置跑一遍完整切分，仅 threshold 可变；返回段列表与耗时秒。"""
    import sherpa_onnx

    model_dir = models_dir / "sherpa-onnx"
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(model_dir / "segmentation.onnx"), window_shift_ratio=0.1
            )
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_dir / "embedding.onnx")
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError(f"sherpa-onnx 配置无效，请检查 {model_dir}/")
    model = sherpa_onnx.OfflineSpeakerDiarization(config)
    began = time.perf_counter()
    result = model.process(samples).sort_by_start_time()
    elapsed = time.perf_counter() - began
    segments = [
        Seg(float(item.start), float(item.end), f"S{int(item.speaker) + 1}") for item in result
    ]
    del model
    gc.collect()
    return segments, elapsed


def sweep_threshold(
    samples: object, models_dir: Path, out_dir: Path, thresholds: list[float]
) -> dict[float, list[Seg]]:
    runs: dict[float, list[Seg]] = {}
    for threshold in thresholds:
        cache = out_dir / f"segments_t{threshold:.2f}.json"
        if cache.is_file():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            runs[threshold] = [Seg(**item) for item in payload["segments"]]
            print(f"[cache] threshold={threshold:.2f}: {len(cluster_totals(runs[threshold]))} 簇")
            continue
        segments, elapsed = run_sherpa(samples, models_dir, threshold)
        cache.write_text(
            json.dumps(
                {
                    "threshold": threshold,
                    "elapsed_seconds": round(elapsed, 1),
                    "segments": [vars(segment) for segment in segments],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        runs[threshold] = segments
        print(
            f"[run] threshold={threshold:.2f}: {len(cluster_totals(segments))} 簇，"
            f"耗时 {elapsed:.0f}s"
        )
    return runs


def cluster_totals(segments: list[Seg]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for segment in segments:
        totals[segment.cluster_id] = totals.get(segment.cluster_id, 0.0) + segment.duration
    return totals


def describe(segments: list[Seg]) -> str:
    totals = sorted(cluster_totals(segments).values(), reverse=True)
    head = ", ".join(f"{value:.0f}" for value in totals[:10])
    tail_lt3 = sum(1 for value in totals if value < 3.0)
    tail_lt10 = sum(1 for value in totals if value < 10.0)
    return (
        f"{len(totals)} 簇 | 前 10 时长(s): {head} | <10s 簇 {tail_lt10} 个 | <3s 簇 {tail_lt3} 个"
    )


def cards_after_consolidate(segments: list[Seg], min_cluster_seconds: float = 3.0) -> list[Seg]:
    from meeting_api.pipeline.diarization import SpeakerSegment, consolidate_fragment_clusters

    merged = consolidate_fragment_clusters(
        [SpeakerSegment(s.start, s.end, s.cluster_id) for s in segments],
        min_cluster_seconds=min_cluster_seconds,
    )
    return [Seg(s.start, s.end, s.cluster_id) for s in merged]


def top_k_min_seconds(segments: list[Seg], k: int) -> float:
    """把 consolidate 阈值抬到第 K 大簇的时长，即等价于 Top-K 策略。"""
    totals = sorted(cluster_totals(segments).values(), reverse=True)
    if len(totals) <= k:
        return 3.0
    return totals[k - 1]


def reassigned_seconds(before: list[Seg], after: list[Seg]) -> float:
    pairs = zip(before, after, strict=True)
    return sum(b.duration for b, a in pairs if b.cluster_id != a.cluster_id)


# ---------- 基线簇声纹与二次合并 ----------


def embed_clusters(
    samples: object, segments: list[Seg], models_dir: Path, sample_rate: int
) -> dict[str, list[float]]:
    """每簇取时长最长的若干段（≥0.5s，总计 ≤20s），逐段提声纹后按时长加权平均。"""
    import numpy as np
    import sherpa_onnx

    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(models_dir / "sherpa-onnx" / "embedding.onnx")
    )
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    by_cluster: dict[str, list[Seg]] = {}
    for segment in segments:
        by_cluster.setdefault(segment.cluster_id, []).append(segment)

    vectors: dict[str, list[float]] = {}
    for cluster_id, members in sorted(by_cluster.items()):
        picked: list[Seg] = []
        budget = 20.0
        for member in sorted(members, key=lambda item: item.duration, reverse=True):
            if member.duration < 0.5 and picked:
                break
            picked.append(member)
            budget -= member.duration
            if budget <= 0 or len(picked) >= 6:
                break
        weighted = None
        weight_total = 0.0
        for member in picked:
            piece = samples[int(member.start * sample_rate) : int(member.end * sample_rate)]
            if len(piece) < int(0.3 * sample_rate):
                continue
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sample_rate, waveform=piece)
            stream.input_finished()
            if not extractor.is_ready(stream):
                continue
            vector = np.asarray(extractor.compute(stream), dtype="float64")
            vector /= max(float(np.linalg.norm(vector)), 1e-9)
            weight = member.duration
            weighted = vector * weight if weighted is None else weighted + vector * weight
            weight_total += weight
        if weighted is None:
            continue
        mean = weighted / weight_total
        mean /= max(float(np.linalg.norm(mean)), 1e-9)
        vectors[cluster_id] = [float(value) for value in mean]
    del extractor
    gc.collect()
    return vectors


def cosine_distance(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return 1.0 - dot  # 向量已归一化


def average_linkage_groups(
    vectors: dict[str, list[float]], threshold: float
) -> list[list[str]]:
    """纯 Python 平均连接层次聚类：距离矩阵上反复合并最近的两组，直到最近距离超阈值。"""
    ids = sorted(vectors)
    groups = [[cluster_id] for cluster_id in ids]

    def group_distance(left: list[str], right: list[str]) -> float:
        pairs = [(a, b) for a in left for b in right]
        return sum(cosine_distance(vectors[a], vectors[b]) for a, b in pairs) / len(pairs)

    while len(groups) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                distance = group_distance(groups[i], groups[j])
                if best is None or distance < best[0]:
                    best = (distance, i, j)
        assert best is not None
        if best[0] > threshold:
            break
        _, i, j = best
        groups[i] = groups[i] + groups[j]
        del groups[j]
    return [sorted(group) for group in groups]


def relabel_by_groups(segments: list[Seg], groups: list[list[str]]) -> list[Seg]:
    """组内以总时长最大的簇 id 为代表，把其余成员的段改挂到代表上。"""
    totals = cluster_totals(segments)
    target: dict[str, str] = {}
    for group in groups:
        anchor = max(group, key=lambda cluster_id: (totals.get(cluster_id, 0.0), cluster_id))
        for member in group:
            target[member] = anchor
    return [
        Seg(segment.start, segment.end, target.get(segment.cluster_id, segment.cluster_id))
        for segment in segments
    ]


# ---------- 跨策略分组一致性 ----------


def map_partition(baseline: list[Seg], other: list[Seg]) -> dict[str, str]:
    """把基线每个簇按时间重叠最大原则映射到另一次运行的簇，得到基线簇的隐含分组。"""
    overlap: dict[str, dict[str, float]] = {}
    for base_segment in baseline:
        row = overlap.setdefault(base_segment.cluster_id, {})
        for other_segment in other:
            shared = min(base_segment.end, other_segment.end) - max(
                base_segment.start, other_segment.start
            )
            if shared > 0:
                row[other_segment.cluster_id] = row.get(other_segment.cluster_id, 0.0) + shared
    return {
        cluster_id: max(row, key=lambda key: row[key]) if row else f"unmapped-{cluster_id}"
        for cluster_id, row in overlap.items()
    }


def pair_agreement(partition_a: dict[str, str], partition_b: dict[str, str]) -> float:
    """两个「基线簇 → 组代表」映射在所有簇对上的同组/异组判断一致率。"""
    ids = sorted(set(partition_a) & set(partition_b))
    if len(ids) < 2:
        return 1.0
    same = 0
    total = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            total += 1
            together_a = partition_a[ids[i]] == partition_a[ids[j]]
            together_b = partition_b[ids[i]] == partition_b[ids[j]]
            same += together_a == together_b
    return same / total


def partition_of_groups(groups: list[list[str]]) -> dict[str, str]:
    return {member: group[0] for group in groups for member in group}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--models-dir", type=Path, default=REPO_ROOT / "data" / "models")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--thresholds", default="0.5,0.6,0.7,0.8,0.9")
    parser.add_argument("--merge-cuts", default="0.20,0.25,0.30,0.35,0.40,0.45,0.50")
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    thresholds = [float(value) for value in args.thresholds.split(",")]
    baseline_threshold = thresholds[0]

    import sherpa_onnx  # noqa: F401  # 提前失败：没装 sherpa 时直接报错

    print(f"加载音频 {args.audio} …")
    samples = load_audio(args.audio, target_rate=16000)
    print(f"时长 {len(samples) / 16000:.0f}s\n")

    runs = sweep_threshold(samples, args.models_dir, args.out, thresholds)
    baseline = runs[baseline_threshold]

    print("\n## A. threshold 扫描（完整管线）\n")
    print("| threshold | 原始簇 | 现行 consolidate(<3s) 后卡数 | 分布 |")
    print("|---|---|---|---|")
    for threshold in thresholds:
        segments = runs[threshold]
        cards = cards_after_consolidate(segments)
        print(
            f"| {threshold:.2f} | {len(cluster_totals(segments))} "
            f"| {len(cluster_totals(cards))} | {describe(segments)} |"
        )

    print("\n## B. 基线簇声纹 + 余弦层次二次合并\n")
    embeddings_cache = args.out / f"embeddings_t{baseline_threshold:.2f}.json"
    if embeddings_cache.is_file():
        vectors = json.loads(embeddings_cache.read_text(encoding="utf-8"))
    else:
        vectors = embed_clusters(samples, baseline, args.models_dir, 16000)
        embeddings_cache.write_text(json.dumps(vectors), encoding="utf-8")
    print(f"取到 {len(vectors)} 个簇声纹（基线 {len(cluster_totals(baseline))} 簇）\n")

    merge_partitions: dict[float, dict[str, str]] = {}
    print("| 合并距离阈值 | 组数 | 现行 consolidate 后卡数 | 被换簇的音频秒数 |")
    print("|---|---|---|---|")
    for cut in [float(value) for value in args.merge_cuts.split(",")]:
        groups = average_linkage_groups(vectors, cut)
        merged = relabel_by_groups(baseline, groups)
        cards = cards_after_consolidate(merged)
        merge_partitions[cut] = partition_of_groups(groups)
        print(
            f"| {cut:.2f} | {len(groups)} | {len(cluster_totals(cards))} "
            f"| {reassigned_seconds(baseline, merged):.0f}s |"
        )

    print(f"\n## C. 时长 Top-K + 就近归并（K = {args.top_k}）\n")
    min_seconds = top_k_min_seconds(baseline, args.top_k)
    topk_cards = cards_after_consolidate(baseline, min_cluster_seconds=min_seconds)
    print(
        f"等价 consolidate 阈值 {min_seconds:.1f}s → {len(cluster_totals(topk_cards))} 卡，"
        f"被按时间就近换簇的音频 {reassigned_seconds(baseline, topk_cards):.0f}s"
        f"（这些秒数没有任何声纹依据，纯赌时间相邻）"
    )

    print("\n## D. 跨策略分组一致性（都折算到基线簇上，1.0 = 完全一致）\n")
    sherpa_partitions = {
        threshold: map_partition(baseline, runs[threshold])
        for threshold in thresholds
        if threshold != baseline_threshold
    }
    header = " | ".join(f"merge@{cut:.2f}" for cut in merge_partitions)
    print(f"| sherpa\\二次合并 | {header} |")
    print("|---" * (len(merge_partitions) + 1) + "|")
    for threshold, partition in sherpa_partitions.items():
        cells = " | ".join(
            f"{pair_agreement(partition, merge_partition):.3f}"
            for merge_partition in merge_partitions.values()
        )
        print(f"| t={threshold:.2f} | {cells} |")

    print("\n完成。原始 JSON 见", args.out)


if __name__ == "__main__":
    main()
