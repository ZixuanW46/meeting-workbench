"""转写 LLM 清洗：纯函数，不接触数据库与 Web 框架。"""

# 提示词常量按自然段落书写，与 minutes/prompt.py 同口径豁免行宽。
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from meeting_api.transcript_format import TranscriptBlock

CLEANING_INSTRUCTIONS = """你是会议转写清洗助手。输入是编号的 JSON 数组，格式为 [{"i": 块号, "speaker": 说话人, "text": 原文}]。

只输出一个 JSON 对象，格式为 {"块号": "清洗后文本"}，不得输出任何其他文字、解释、Markdown 或代码围栏。

清洗规则：
- 删除语气词（嗯、呃、啊等）与口吃重复。
- 修正标点与断句。
- 结合上下文修明显同音错字。
- 保留全部事实信息、数字、人名、专名。
- 禁止缩写概括，禁止跨块移动或合并内容，禁止翻译。
- 拿不准就保留原文。
- 术语表（如有）只用于纠正专名写法。
"""

MAX_CHUNK_CHARS = 3000


def chunk_indexed_blocks(
    blocks: Sequence[TranscriptBlock],
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[list[tuple[int, TranscriptBlock]]]:
    chunks: list[list[tuple[int, TranscriptBlock]]] = []
    current: list[tuple[int, TranscriptBlock]] = []
    current_chars = 0

    for index, block in enumerate(blocks):
        text_chars = len(block.text)
        if text_chars > max_chars:
            if current:
                chunks.append(current)
                current = []
                current_chars = 0
            chunks.append([(index, block)])
            continue

        if current and current_chars + text_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0

        current.append((index, block))
        current_chars += text_chars

    if current:
        chunks.append(current)
    return chunks


def build_cleaning_prompt(
    chunk: Sequence[tuple[int, TranscriptBlock]],
    glossary: str | None,
) -> str:
    rows = [
        {"i": index, "speaker": block.label, "text": block.text}
        for index, block in chunk
    ]
    glossary_block = f"\n术语表：\n{glossary.rstrip()}\n" if glossary else ""
    return (
        f"{CLEANING_INSTRUCTIONS.rstrip()}\n"
        f"{glossary_block}\n"
        f"{json.dumps(rows, ensure_ascii=False)}"
    )


def parse_cleaning_response(
    output: str,
    expected_indices: Sequence[int],
) -> dict[int, str]:
    text = _strip_code_fence(output.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("清洗响应不是 JSON 对象")

    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("清洗响应不是 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise ValueError("清洗响应不是 JSON 对象")

    expected = set(expected_indices)
    parsed: dict[int, str] = {}
    for key, value in payload.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index not in expected:
            continue
        if not isinstance(value, str):
            raise ValueError("清洗响应包含非字符串文本")
        parsed[index] = value
    return parsed


def accept_cleaned_text(raw: str, cleaned: str) -> bool:
    return bool(cleaned.strip()) and len(cleaned) <= 2 * len(raw) + 20


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_cleaned_blocks(
    blocks: Sequence[TranscriptBlock],
    cleaned_rows: Mapping[int, tuple[str, str]],
) -> tuple[list[TranscriptBlock], bool]:
    applied: list[TranscriptBlock] = []
    changed = False

    for index, block in enumerate(blocks):
        row = cleaned_rows.get(index)
        if row is None:
            applied.append(block)
            continue

        raw_sha256, cleaned_text = row
        if sha256_text(block.text) != raw_sha256:
            applied.append(block)
            continue

        applied.append(
            TranscriptBlock(
                start_seconds=block.start_seconds,
                end_seconds=block.end_seconds,
                label=block.label,
                text=cleaned_text,
            )
        )
        changed = True

    return applied, changed


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text
