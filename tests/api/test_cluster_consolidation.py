"""碎说话人簇合并：真实音频的自动聚类几乎必产单段/亚秒碎簇，
不能让它们把确认停点整场打崩。只合并时间轴，不做任何身份判断。"""

from __future__ import annotations

from meeting_api.pipeline.diarization import (
    SpeakerSegment,
    consolidate_fragment_clusters,
)


def _ids(segments: list[SpeakerSegment]) -> list[str]:
    return [segment.cluster_id for segment in segments]


def test_singleton_short_cluster_merges_into_nearest_major():
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(10.5, 11.2, "S9"),  # 0.7 秒碎簇，离 S1 更近
        SpeakerSegment(12.0, 20.0, "S2"),
        SpeakerSegment(21.0, 30.0, "S2"),
        SpeakerSegment(35.0, 44.0, "S1"),
    ]

    merged = consolidate_fragment_clusters(segments)

    assert _ids(merged) == ["S1", "S1", "S2", "S2", "S1"]
    # 时间轴不许动，只允许换簇标签。
    assert [(s.start, s.end) for s in merged] == [(s.start, s.end) for s in segments]


def test_real_single_turn_speaker_is_kept():
    # 只发言一次但时长足够的真实说话人不得被并掉。
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(10.0, 15.0, "S2"),
        SpeakerSegment(15.0, 25.0, "S1"),
    ]

    merged = consolidate_fragment_clusters(segments)

    assert merged == segments


def test_scattered_tiny_cluster_merges_each_segment_to_nearest_major():
    segments = [
        SpeakerSegment(0.0, 10.0, "S1"),
        SpeakerSegment(10.1, 10.7, "S7"),  # 离 S1 尾部 0.1s
        SpeakerSegment(11.0, 20.0, "S2"),
        SpeakerSegment(20.2, 20.9, "S7"),  # 离 S2 尾部 0.2s
        SpeakerSegment(21.0, 29.0, "S2"),
    ]

    merged = consolidate_fragment_clusters(segments)

    assert _ids(merged) == ["S1", "S1", "S2", "S2", "S2"]


def test_all_fragments_keep_largest_cluster_as_anchor():
    segments = [
        SpeakerSegment(0.0, 1.0, "S1"),
        SpeakerSegment(2.0, 3.5, "S2"),
        SpeakerSegment(4.0, 4.5, "S3"),
    ]

    merged = consolidate_fragment_clusters(segments)

    assert set(_ids(merged)) == {"S2"}
    assert len(merged) == 3


def test_empty_input_returns_empty():
    assert consolidate_fragment_clusters([]) == []
