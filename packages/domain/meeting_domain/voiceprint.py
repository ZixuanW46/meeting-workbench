"""声纹入库资格与建议匹配规则。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from meeting_domain.speaker_review import DecisionKind, SpeakerDecision

# fake 与后续真实后端共用的领域阈值；达到阈值才允许入库。
VOICEPRINT_QUALITY_THRESHOLD = 0.7

# 建议档位的余弦阈值。档位是给人的定性表达，绝不对外暴露相似度数值；
# 低于 SUGGEST 阈值宁可不建议，也不拿弱相似打扰确认停点。
VOICEPRINT_HIGH_THRESHOLD = 0.60
VOICEPRINT_SUGGEST_THRESHOLD = 0.45


class SuggestionTier(StrEnum):
    HIGH = "high"  # 「较高」
    UNCERTAIN = "uncertain"  # 「需判断」


@dataclass(frozen=True)
class VoiceprintMatch:
    person_id: str
    tier: SuggestionTier


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """维度不一致（换后端遗留的旧库向量）或零范数一律视为不相似。"""
    if len(a) != len(b):
        return 0.0
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (norm_a * norm_b)


def match_voiceprint(
    candidate: Sequence[float],
    enrolled: Mapping[str, Sequence[float]],
) -> VoiceprintMatch | None:
    """在声纹库里找与候选向量最相似的人；不够相似返回 None。

    这里只产生建议——落名永远来自用户在确认停点的决定。
    """
    best_person_id: str | None = None
    best_similarity = 0.0
    for person_id in sorted(enrolled):
        similarity = cosine_similarity(candidate, enrolled[person_id])
        if similarity > best_similarity:
            best_person_id = person_id
            best_similarity = similarity
    if best_person_id is None or best_similarity < VOICEPRINT_SUGGEST_THRESHOLD:
        return None
    tier = (
        SuggestionTier.HIGH
        if best_similarity >= VOICEPRINT_HIGH_THRESHOLD
        else SuggestionTier.UNCERTAIN
    )
    return VoiceprintMatch(person_id=best_person_id, tier=tier)

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
