"""出卡前碎说话人簇按声纹吸收进主簇的纯领域计划。"""

from __future__ import annotations

import math
from collections.abc import Sequence

Embedding = Sequence[float]
ClusterForAbsorption = tuple[str, float, Embedding | None]

# 碎簇吸收阈值（余弦距离）。真机实测同人主簇均值声纹距离 <=0.39、
# 异人 >=0.63（见 diarization.py 里 CLUSTER_MERGE_MAX_DISTANCE 注释）；
# 碎片声纹噪声更大，取异人下限保守侧、比主簇二次合并的 0.4 松。
FRAGMENT_ABSORB_MAX_DISTANCE = 0.6


def plan_fragment_absorption(
    clusters: Sequence[ClusterForAbsorption],
    *,
    max_fragment_seconds: float,
    max_distance: float = FRAGMENT_ABSORB_MAX_DISTANCE,
) -> dict[str, str]:
    """规划碎簇到最相近主簇的吸收关系；只返回簇标签映射，不碰身份。"""
    if max_fragment_seconds <= 0:
        return {}

    normalized: dict[str, tuple[float, ...]] = {}
    totals: dict[str, float] = {}
    for cluster_id, total_seconds, embedding in clusters:
        totals[cluster_id] = total_seconds
        if embedding is None:
            continue
        norm = math.sqrt(sum(value * value for value in embedding))
        if norm > 0:
            normalized[cluster_id] = tuple(value / norm for value in embedding)

    majors = [
        cluster_id
        for cluster_id, total_seconds, _ in clusters
        if total_seconds >= max_fragment_seconds and cluster_id in normalized
    ]
    if not majors:
        return {}

    plan: dict[str, str] = {}
    for cluster_id, total_seconds, _ in clusters:
        if total_seconds >= max_fragment_seconds or cluster_id not in normalized:
            continue
        candidate = normalized[cluster_id]
        # 最相近主簇：按（距离、-主簇时长、簇号）取最小，结果确定可复现。
        best: tuple[float, float, str] | None = None
        for major_id in majors:
            vector = normalized[major_id]
            if len(vector) != len(candidate):
                continue
            distance = 1.0 - sum(
                left * right for left, right in zip(candidate, vector, strict=True)
            )
            key = (distance, -totals[major_id], major_id)
            if best is None or key < best:
                best = key
        if best is not None and best[0] <= max_distance:
            plan[cluster_id] = best[2]
    return plan
