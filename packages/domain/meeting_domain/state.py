"""会议状态机（锁定方案第 5 节 + 第 10 节）。

主链：
DRAFT → UPLOADING → QUEUED → PROCESSING → AWAITING_SPEAKER_REVIEW
      → APPLYING_DECISIONS → GENERATING_MINUTES → READY

旁路：
- FAILED：处理链路上的失败（人工停点本身不会失败，只能取消）。
- CANCELED：用户主动取消处理中会议。
- PARTIAL_READY：转写已好、纪要 CLI 失败；不是终态，可重试回 GENERATING_MINUTES。
- AWAITING_SPEAKER_REVIEW / READY / PARTIAL_READY：用户可显式重转写回 QUEUED。
"""

from __future__ import annotations

from enum import StrEnum


class MeetingState(StrEnum):
    DRAFT = "DRAFT"
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_SPEAKER_REVIEW = "AWAITING_SPEAKER_REVIEW"
    APPLYING_DECISIONS = "APPLYING_DECISIONS"
    GENERATING_MINUTES = "GENERATING_MINUTES"
    READY = "READY"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    PARTIAL_READY = "PARTIAL_READY"


class InvalidTransition(Exception):
    def __init__(self, src: MeetingState, dst: MeetingState) -> None:
        super().__init__(f"非法状态迁移: {src} -> {dst}")
        self.src = src
        self.dst = dst


TRANSITIONS: dict[MeetingState, frozenset[MeetingState]] = {
    MeetingState.DRAFT: frozenset({MeetingState.UPLOADING, MeetingState.CANCELED}),
    MeetingState.UPLOADING: frozenset(
        {MeetingState.QUEUED, MeetingState.FAILED, MeetingState.CANCELED}
    ),
    MeetingState.QUEUED: frozenset(
        {MeetingState.PROCESSING, MeetingState.FAILED, MeetingState.CANCELED}
    ),
    MeetingState.PROCESSING: frozenset(
        {MeetingState.AWAITING_SPEAKER_REVIEW, MeetingState.FAILED, MeetingState.CANCELED}
    ),
    # 唯一人工停点：可被确认推进、显式重转写或取消，不存在自动失败。
    MeetingState.AWAITING_SPEAKER_REVIEW: frozenset(
        {
            MeetingState.APPLYING_DECISIONS,
            MeetingState.QUEUED,
            MeetingState.CANCELED,
        }
    ),
    MeetingState.APPLYING_DECISIONS: frozenset(
        {MeetingState.GENERATING_MINUTES, MeetingState.FAILED, MeetingState.CANCELED}
    ),
    MeetingState.GENERATING_MINUTES: frozenset(
        {
            MeetingState.READY,
            MeetingState.PARTIAL_READY,
            MeetingState.FAILED,
            MeetingState.CANCELED,
        }
    ),
    # 纪要 CLI 失败（如配额）可重试；转写结果仍在，随时可导出。
    MeetingState.PARTIAL_READY: frozenset(
        {
            MeetingState.GENERATING_MINUTES,
            MeetingState.QUEUED,
            MeetingState.CANCELED,
        }
    ),
    # QUEUED 边只供用户显式重转写；不是自动失败或自动重试。
    MeetingState.READY: frozenset({MeetingState.QUEUED}),
    MeetingState.FAILED: frozenset(),
    MeetingState.CANCELED: frozenset(),
}

TERMINAL_STATES: frozenset[MeetingState] = frozenset(
    {MeetingState.FAILED, MeetingState.CANCELED}
)

ACTIVE_STATES: frozenset[MeetingState] = frozenset(MeetingState) - TERMINAL_STATES


def can_transition(src: MeetingState, dst: MeetingState) -> bool:
    return dst in TRANSITIONS[src]


def transition(src: MeetingState, dst: MeetingState) -> MeetingState:
    """校验并返回新状态；非法迁移抛 InvalidTransition。"""
    if not can_transition(src, dst):
        raise InvalidTransition(src, dst)
    return dst
