"""纯内存假流水线：驱动状态机走完整链路，不碰任何模型/IO。

用途：
- 单测验证「DRAFT 一路推到 AWAITING_SPEAKER_REVIEW，夹具确认后推到 READY」。
- M3 的单队列 worker 会复用同样的推进顺序，把每步换成真实任务。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meeting_domain.speaker_review import (
    ReviewIncomplete,
    SpeakerCard,
    SpeakerDecision,
    missing_decisions,
    review_complete,
)
from meeting_domain.state import MeetingState, transition


@dataclass
class FakeMeetingPipeline:
    """一场会议的假流水线。state 只能通过状态机合法迁移。"""

    cards: list[SpeakerCard] = field(default_factory=list)
    state: MeetingState = MeetingState.DRAFT
    decisions: list[SpeakerDecision] = field(default_factory=list)

    def _advance(self, dst: MeetingState) -> None:
        self.state = transition(self.state, dst)

    def run_until_review(self) -> MeetingState:
        """模拟上传+处理：DRAFT → … → AWAITING_SPEAKER_REVIEW。"""
        self._advance(MeetingState.UPLOADING)
        self._advance(MeetingState.QUEUED)
        self._advance(MeetingState.PROCESSING)
        self._advance(MeetingState.AWAITING_SPEAKER_REVIEW)
        return self.state

    def confirm_speakers(self, decisions: list[SpeakerDecision]) -> MeetingState:
        """人工停点：所有卡都有决定才放行，否则抛 ReviewIncomplete。"""
        if not review_complete(self.cards, decisions):
            raise ReviewIncomplete(missing_decisions(self.cards, decisions))
        self.decisions = list(decisions)
        self._advance(MeetingState.APPLYING_DECISIONS)
        self._advance(MeetingState.GENERATING_MINUTES)
        return self.state

    def finish_minutes(self, *, cli_ok: bool) -> MeetingState:
        """纪要 CLI 成功 → READY；失败（如配额）→ PARTIAL_READY 可重试。"""
        self._advance(MeetingState.READY if cli_ok else MeetingState.PARTIAL_READY)
        return self.state

    def retry_minutes(self) -> MeetingState:
        self._advance(MeetingState.GENERATING_MINUTES)
        return self.state

    def fail(self) -> MeetingState:
        self._advance(MeetingState.FAILED)
        return self.state

    def cancel(self) -> MeetingState:
        self._advance(MeetingState.CANCELED)
        return self.state
