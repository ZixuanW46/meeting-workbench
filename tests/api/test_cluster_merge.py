"""簇级声纹二次合并：sherpa 自动聚类在长录音上会把同一真人撕成多个主簇
（真机 27 分钟录音：92 原始簇里前 15 个主簇实测形成 3 个块内距离 ≤0.39、
块间距离 ≥0.63 的声纹块）。二次合并只在簇均值声纹足够近时换标签，
时间轴不动，也不做任何身份判断。"""

from __future__ import annotations

import math

from meeting_api.pipeline.diarization import (
    CLUSTER_MERGE_MAX_DISTANCE,
    SpeakerSegment,
    merge_similar_clusters,
    pick_embedding_spans,
)


def _ids(segments: list[SpeakerSegment]) -> list[str]:
    return [segment.cluster_id for segment in segments]


def _unit(x: float, y: float) -> tuple[float, float]:
    norm = math.hypot(x, y)
    return (x / norm, y / norm)


def test_near_identical_clusters_merge_into_longer_anchor():
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(12.0, 16.0, "S7"),
        SpeakerSegment(20.0, 30.0, "S1"),
    ]
    embeddings = {
        "S1": _unit(1.0, 0.0),
        "S7": _unit(1.0, 0.05),  # 与 S1 余弦距离 ≈0.001
    }

    merged = merge_similar_clusters(segments, embeddings)

    assert _ids(merged) == ["S1", "S1", "S1"]
    # 时间轴不许动，只允许换簇标签。
    assert [(s.start, s.end) for s in merged] == [(s.start, s.end) for s in segments]


def test_distant_clusters_stay_separate():
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(12.0, 22.0, "S2"),
    ]
    embeddings = {
        "S1": _unit(1.0, 0.0),
        "S2": _unit(0.0, 1.0),  # 正交：余弦距离 1.0
    }

    assert merge_similar_clusters(segments, embeddings) == segments


def test_average_linkage_chains_only_while_group_average_stays_close():
    # S1–S3 单对距离超阈，但经 S2 桥接后组平均仍在阈内 → 三者并成一组；
    # S4 与该组的平均距离远超阈 → 必须留在组外。
    segments = [
        SpeakerSegment(0.0, 12.0, "S1"),
        SpeakerSegment(12.0, 20.0, "S2"),
        SpeakerSegment(20.0, 26.0, "S3"),
        SpeakerSegment(26.0, 32.0, "S4"),
    ]
    theta = math.acos(1.0 - CLUSTER_MERGE_MAX_DISTANCE)
    embeddings = {
        "S1": _unit(1.0, 0.0),
        "S2": _unit(math.cos(theta * 0.6), math.sin(theta * 0.6)),
        "S3": _unit(math.cos(theta * 1.2), math.sin(theta * 1.2)),
        "S4": _unit(math.cos(theta * 2.6), math.sin(theta * 2.6)),
    }

    merged = merge_similar_clusters(segments, embeddings)

    assert _ids(merged) == ["S1", "S1", "S1", "S4"]


def test_cluster_without_embedding_is_left_untouched():
    # 太短提不出声纹的簇没有合并依据：保持原标签，交给后续时间就近碎簇合并。
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(10.5, 11.0, "S9"),
        SpeakerSegment(12.0, 20.0, "S1"),
    ]
    embeddings = {"S1": _unit(1.0, 0.0)}

    assert merge_similar_clusters(segments, embeddings) == segments


def test_unnormalized_embeddings_are_normalized_before_compare():
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(12.0, 16.0, "S7"),
    ]
    embeddings = {
        "S1": (10.0, 0.0),
        "S7": (0.2, 0.0),  # 同方向不同模长：余弦距离 0
    }

    assert _ids(merge_similar_clusters(segments, embeddings)) == ["S1", "S1"]


def test_anchor_tie_breaks_to_smaller_cluster_id():
    segments = [
        SpeakerSegment(0.0, 5.0, "S8"),
        SpeakerSegment(6.0, 11.0, "S3"),
    ]
    embeddings = {"S8": _unit(1.0, 0.0), "S3": _unit(1.0, 0.02)}

    assert _ids(merge_similar_clusters(segments, embeddings)) == ["S3", "S3"]


def test_empty_input_returns_empty():
    assert merge_similar_clusters([], {}) == []


# ---------- 取样片段挑选 ----------


def test_pick_embedding_spans_prefers_longest_and_drops_subsecond_tail():
    # 有像样的长段时，<0.5s 的残段不进声纹取样（质量太差只会拉脏均值）。
    segments = [
        SpeakerSegment(0.0, 0.4, "S1"),
        SpeakerSegment(10.0, 18.0, "S1"),
        SpeakerSegment(30.0, 33.0, "S1"),
    ]

    spans = pick_embedding_spans(segments)

    assert spans == [(10.0, 18.0), (30.0, 33.0)]


def test_pick_embedding_spans_caps_count_and_total_seconds():
    # 20s 预算 + 最多 6 段：8 个 5s 段只取前 4 段（时长相同按开始时间稳定排序）。
    segments = [SpeakerSegment(i * 10.0, i * 10.0 + 5.0, "S1") for i in range(8)]

    spans = pick_embedding_spans(segments)

    assert spans == [(0.0, 5.0), (10.0, 15.0), (20.0, 25.0), (30.0, 35.0)]


def test_pick_embedding_spans_keeps_single_short_segment():
    # 全是亚秒段时也要给出最长的那段，宁可声纹质量差也不放弃合并依据。
    segments = [
        SpeakerSegment(0.0, 0.3, "S1"),
        SpeakerSegment(1.0, 1.4, "S1"),
    ]

    assert pick_embedding_spans(segments) == [(1.0, 1.4)]
