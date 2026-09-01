from __future__ import annotations

import pytest

from meeting_api.transcript_cleaning import (
    CLEANING_INSTRUCTIONS,
    accept_cleaned_text,
    apply_cleaned_blocks,
    build_cleaning_prompt,
    chunk_indexed_blocks,
    parse_cleaning_response,
    sha256_text,
)
from meeting_api.transcript_format import TranscriptBlock


def _block(text: str, label: str = "王芳") -> TranscriptBlock:
    return TranscriptBlock(
        start_seconds=0.0,
        end_seconds=1.0,
        label=label,
        text=text,
    )


def test_chunk_indexed_blocks_keeps_order_and_single_oversized_block_gets_own_chunk():
    blocks = [
        _block("甲" * 3),
        _block("乙" * 4),
        _block("丙" * 11),
        _block("丁" * 2),
    ]

    chunks = chunk_indexed_blocks(blocks, max_chars=10)

    assert [[index for index, _ in chunk] for chunk in chunks] == [[0, 1], [2], [3]]
    assert [block.text for chunk in chunks for _, block in chunk] == [
        "甲" * 3,
        "乙" * 4,
        "丙" * 11,
        "丁" * 2,
    ]


def test_build_cleaning_prompt_contains_instructions_glossary_and_block_json():
    prompt = build_cleaning_prompt(
        [(3, _block("嗯见山项目", label="说话人 2"))],
        glossary="- 见山：教育项目品牌",
    )

    assert CLEANING_INSTRUCTIONS in prompt
    assert "术语表：" in prompt
    assert "- 见山：教育项目品牌" in prompt
    assert '{"i": 3, "speaker": "说话人 2", "text": "嗯见山项目"}' in prompt


def test_build_cleaning_prompt_omits_empty_glossary_block():
    prompt = build_cleaning_prompt([(0, _block("普通文本"))], glossary=None)

    assert "术语表：" not in prompt
    assert '"i": 0' in prompt
    assert '"text": "普通文本"' in prompt


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('{"0": "清洗一", "1": "清洗二"}', {0: "清洗一", 1: "清洗二"}),
        ('```json\n{"0": "清洗一"}\n```', {0: "清洗一"}),
        ('{"0": "清洗一", "99": "忽略"}', {0: "清洗一"}),
        ('{"0": "清洗一"}', {0: "清洗一"}),
    ],
)
def test_parse_cleaning_response_accepts_supported_shapes(output, expected):
    assert parse_cleaning_response(output, expected_indices=[0, 1]) == expected


def test_parse_cleaning_response_raises_for_garbage_input():
    with pytest.raises(ValueError):
        parse_cleaning_response("不是 JSON", expected_indices=[0])


def test_parse_cleaning_response_raises_for_non_string_expected_value():
    with pytest.raises(ValueError):
        parse_cleaning_response('{"0": 123}', expected_indices=[0])


def test_accept_cleaned_text_requires_non_empty_and_reasonable_length():
    assert accept_cleaned_text("嗯我们今天开会", "我们今天开会") is True
    assert accept_cleaned_text("原文", "   ") is False
    assert accept_cleaned_text("短", "长" * 23) is False
    assert accept_cleaned_text("短", "长" * 22) is True


def test_apply_cleaned_blocks_replaces_only_matching_sha_rows():
    blocks = [
        TranscriptBlock(0.0, 1.0, "王芳", "第一段原文"),
        TranscriptBlock(1.0, 2.0, "李雷", "第二段原文"),
    ]

    applied, changed = apply_cleaned_blocks(
        blocks,
        {
            0: (sha256_text("第一段原文"), "第一段清洗"),
            1: (sha256_text("不匹配"), "第二段清洗"),
            9: (sha256_text("不存在"), "忽略"),
        },
    )

    assert changed is True
    assert [block.text for block in applied] == ["第一段清洗", "第二段原文"]
    assert [(block.start_seconds, block.end_seconds, block.label) for block in applied] == [
        (0.0, 1.0, "王芳"),
        (1.0, 2.0, "李雷"),
    ]


def test_apply_cleaned_blocks_reports_no_change_when_no_sha_matches():
    blocks = [TranscriptBlock(0.0, 1.0, "王芳", "第一段原文")]

    applied, changed = apply_cleaned_blocks(
        blocks,
        {0: (sha256_text("旧原文"), "第一段清洗")},
    )

    assert changed is False
    assert applied == blocks
