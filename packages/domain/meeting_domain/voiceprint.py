"""声纹入库资格规则。"""

from __future__ import annotations

from meeting_domain.speaker_review import DecisionKind, SpeakerDecision

# fake 与后续真实后端共用的领域阈值；达到阈值才允许入库。
VOICEPRINT_QUALITY_THRESHOLD = 0.7

ENROLLABLE_DECISION_KINDS: frozenset[DecisionKind] = frozenset(
    {
        DecisionKind.CONFIRM,
        DecisionKind.REASSIGN,
        DecisionKind.LINK_EXISTING,
        DecisionKind.NEW_PERSON,
    }
)


def eligible_for_enrollment(decision: SpeakerDecision, quality: float) -> bool:
    """仅明确确认身份且片段质量达标的簇可入声纹库。"""
    return (
        decision.kind in ENROLLABLE_DECISION_KINDS
        and quality >= VOICEPRINT_QUALITY_THRESHOLD
    )
