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
    enrolled: Mapping[str, Sequence[Sequence[float]]],
) -> VoiceprintMatch | None:
    """在声纹库里找与候选向量最相似的人；不够相似返回 None。

    每人可有多条模板（不同会议/环境各留一条），取其中最高余弦——
    同一个人换了设备或房间，总有一条模板接得住。这里只产生建议——
    落名永远来自用户在确认停点的决定。
    """
    best_person_id: str | None = None
    best_similarity = 0.0
    for person_id in sorted(enrolled):
        for template in enrolled[person_id]:
            similarity = cosine_similarity(candidate, template)
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


# 每人模板上限：控住「取最高余弦」的误报面、把单次误挂污染限制在 1/K
# 并可被淘汰、保持声纹库审核页在人工可核对的规模。
TEMPLATE_CAP = 4

# 与现有模板余弦达到该值视为冗余：没有信息增益，只刷新录音条件。
TEMPLATE_REDUNDANCY_THRESHOLD = 0.9


@dataclass(frozen=True)
class EnrollmentPlan:
    action: str  # "append" | "replace"
    replace_index: int | None = None


def plan_enrollment(
    existing: Sequence[Sequence[float]],
    candidate: Sequence[float],
) -> EnrollmentPlan:
    """多模板入库策略；existing 按入库时间升序（最旧在前）。

    与某现有模板冗余（余弦 ≥0.9）→ 替换最相似那条（刷新录音条件而不是
    堆重复）；未满上限 → 追加（保留环境多样性）；满了 → 替换最旧。
    """
    best_index: int | None = None
    best_similarity = 0.0
    for index, template in enumerate(existing):
        similarity = cosine_similarity(candidate, template)
        if similarity > best_similarity:
            best_similarity = similarity
            best_index = index
    if best_index is not None and best_similarity >= TEMPLATE_REDUNDANCY_THRESHOLD:
        return EnrollmentPlan(action="replace", replace_index=best_index)
    if len(existing) < TEMPLATE_CAP:
        return EnrollmentPlan(action="append")
    return EnrollmentPlan(action="replace", replace_index=0)

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
