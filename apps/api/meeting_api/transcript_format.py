"""逐字稿排版：把 ASR 碎片合并成 PLAUD 风格段落块并渲染成文本。

纯函数模块，导出与纪要输入共用同一套口径；说话人标签由调用方决定。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PUNCTUATION_ENDINGS = set("，。！？；：、…—」』”\"）》.!?,;:")
MAX_BLOCK_SECONDS = 60.0


@dataclass(frozen=True)
class TranscriptBlock:
    start_seconds: float
    end_seconds: float
    label: str
    text: str


TranscriptInput = tuple[float, float, str, str]


def format_timestamp(seconds: float) -> str:
    total_seconds = math.floor(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes:02d}:{seconds_part:02d}"


def build_transcript_blocks(
    segments: Sequence[TranscriptInput],
    *,
    max_block_seconds: float = MAX_BLOCK_SECONDS,
) -> list[TranscriptBlock]:
    blocks: list[TranscriptBlock] = []
    current: TranscriptBlock | None = None

    for start_seconds, end_seconds, label, text in segments:
        should_start = (
            current is None
            or current.label != label
            or end_seconds - current.start_seconds > max_block_seconds
        )
        if should_start:
            if current is not None:
                blocks.append(current)
            current = TranscriptBlock(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                label=label,
                text=text,
            )
            continue

        current = TranscriptBlock(
            start_seconds=current.start_seconds,
            end_seconds=end_seconds,
            label=current.label,
            text=_join_text(current.text, text),
        )

    if current is not None:
        blocks.append(current)
    return blocks


def render_transcript_blocks(blocks: Iterable[TranscriptBlock]) -> str:
    return "\n\n".join(
        f"{block.label} {format_timestamp(block.start_seconds)}-"
        f"{format_timestamp(block.end_seconds)}\n{block.text}"
        for block in blocks
    )


def format_transcript_blocks(segments: Sequence[TranscriptInput]) -> str:
    return render_transcript_blocks(build_transcript_blocks(segments))


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    separator = "" if left[-1] in PUNCTUATION_ENDINGS else " "
    return f"{left}{separator}{right}"
