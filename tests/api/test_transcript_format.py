from __future__ import annotations

import pytest

from meeting_api.transcript_format import (
    build_transcript_blocks,
    format_timestamp,
    render_transcript_blocks,
)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (65, "01:05"),
        (3599.9, "59:59"),
        (3600, "1:00:00"),
        (4090, "1:08:10"),
    ],
)
def test_format_timestamp_floors_seconds_and_uses_hours_when_needed(
    seconds, expected
):
    assert format_timestamp(seconds) == expected


def test_adjacent_segments_with_same_label_are_merged():
    blocks = build_transcript_blocks(
        [
            (0.0, 5.0, "张三", "先说第一句。"),
            (5.0, 10.0, "张三", "再说第二句"),
        ]
    )

    assert len(blocks) == 1
    assert blocks[0].start_seconds == 0.0
    assert blocks[0].end_seconds == 10.0
    assert blocks[0].label == "张三"
    assert blocks[0].text == "先说第一句。再说第二句"


def test_span_limit_starts_a_new_block():
    blocks = build_transcript_blocks(
        [
            (0.0, 30.0, "张三", "第一段"),
            (30.0, 60.0, "张三", "第二段"),
            (60.0, 61.0, "张三", "第三段"),
        ]
    )

    assert [(block.start_seconds, block.end_seconds) for block in blocks] == [
        (0.0, 60.0),
        (60.0, 61.0),
    ]


def test_label_change_starts_a_new_block():
    blocks = build_transcript_blocks(
        [
            (0.0, 5.0, "张三", "第一段"),
            (5.0, 10.0, "李四", "第二段"),
        ]
    )

    assert [block.label for block in blocks] == ["张三", "李四"]


def test_single_segment_over_span_limit_stays_in_one_block():
    blocks = build_transcript_blocks([(0.0, 70.0, "张三", "长段")])

    assert len(blocks) == 1
    assert blocks[0].start_seconds == 0.0
    assert blocks[0].end_seconds == 70.0
    assert blocks[0].text == "长段"


def test_text_joining_is_punctuation_aware():
    blocks = build_transcript_blocks(
        [
            (0.0, 2.0, "张三", "前面有标点，"),
            (2.0, 4.0, "张三", "直接相连"),
            (4.0, 6.0, "张三", "前面无标点"),
            (6.0, 8.0, "张三", "补空格"),
            (8.0, 10.0, "张三", "引用结束是“中文右引号”"),
            (10.0, 12.0, "张三", "也直接相连"),
        ]
    )

    assert blocks[0].text == (
        "前面有标点，直接相连 前面无标点 补空格 引用结束是“中文右引号”也直接相连"
    )


def test_render_uses_two_line_blocks_with_blank_line_between_blocks():
    blocks = build_transcript_blocks(
        [
            (0.0, 5.0, "张三", "第一段"),
            (5.0, 10.0, "李四", "第二段"),
        ]
    )

    assert render_transcript_blocks(blocks) == (
        "张三 00:00-00:05\n"
        "第一段\n"
        "\n"
        "李四 00:05-00:10\n"
        "第二段"
    )
