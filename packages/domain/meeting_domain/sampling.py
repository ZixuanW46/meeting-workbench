"""确认停点试听片段的取样规则。

连续片段只能证明「这几秒是同一个人」；分散在会议不同时段的片段才支撑
「整簇是不是同一个人」的人工判断。规则留在领域层，由单测锁定。
"""

from __future__ import annotations

from collections.abc import Sequence

TimeWindow = tuple[float, float]

# 每簇试听片段上限：匹配、入库、试听共用同一批时间窗。
REVIEW_CLIP_LIMIT = 5


def select_spread_windows(
    windows: Sequence[TimeWindow], *, limit: int = REVIEW_CLIP_LIMIT
) -> list[TimeWindow]:
    """从一个簇的全部发言窗里选至多 limit 个，覆盖会议不同时段。

    把该簇首末发言的时间跨度均分成 limit 个时段桶，每桶取最长的一段
    （短残段听不出是谁）；有空桶时按时长补齐，输出恢复时间顺序。
    """
    ordered = sorted(windows)
    if len(ordered) <= limit:
        return ordered

    span_start = ordered[0][0]
    span_end = max(end for _, end in ordered)
    width = (span_end - span_start) / limit

    def duration(index: int) -> float:
        start, end = ordered[index]
        return end - start

    remaining = set(range(len(ordered)))
    chosen: set[int] = set()
    for bucket in range(limit):
        lower = span_start + width * bucket
        upper = span_end if bucket == limit - 1 else span_start + width * (bucket + 1)
        candidates = [
            index
            for index in remaining
            if lower <= (ordered[index][0] + ordered[index][1]) / 2 <= upper
        ]
        if candidates:
            # 同长时取更早的一段，结果确定可复现。
            picked = max(candidates, key=lambda index: (duration(index), -index))
            chosen.add(picked)
            remaining.discard(picked)

    for index in sorted(remaining, key=lambda index: (-duration(index), index)):
        if len(chosen) >= limit:
            break
        chosen.add(index)

    return [ordered[index] for index in sorted(chosen)]
