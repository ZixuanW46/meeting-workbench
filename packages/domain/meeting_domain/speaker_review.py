"""说话人确认规则（锁定方案第 6 节）。

- 每张卡（一个说话人簇）必须有且仅有一个决定，才能离开人工停点。
- 「保持未知 / 暂时不知道」是合法决定：可以出纪要，但纪要要标记
  「含未确认说话人」，且该簇不入声纹库。
- 系统只建议，不自动落名——落名永远来自这里的用户决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionKind(StrEnum):
    # 已有建议身份的簇
    CONFIRM = "CONFIRM"  # 确认建议
    REASSIGN = "REASSIGN"  # 换成另一个已有人
    KEEP_UNKNOWN = "KEEP_UNKNOWN"  # 保持未知
    # 未知簇
    NEW_PERSON = "NEW_PERSON"  # 新建人
    LINK_EXISTING = "LINK_EXISTING"  # 关联已有人
    MERGE_WITH_CLUSTER = "MERGE_WITH_CLUSTER"  # 与本场另一簇是同一人
    UNDECIDED_UNKNOWN = "UNDECIDED_UNKNOWN"  # 暂时不知道（也是一种明确决定）


# 这些决定不产生确认身份 → 纪要须标记「含未确认说话人」，且不入声纹库。
UNCONFIRMED_KINDS: frozenset[DecisionKind] = frozenset(
    {DecisionKind.KEEP_UNKNOWN, DecisionKind.UNDECIDED_UNKNOWN}
)


@dataclass(frozen=True)
class SpeakerCard:
    cluster_id: str
    suggested_person_id: str | None = None  # None = 未知簇


@dataclass(frozen=True)
class SpeakerDecision:
    cluster_id: str
    kind: DecisionKind
    person_id: str | None = None  # REASSIGN / LINK_EXISTING 时指向人
    merge_into_cluster_id: str | None = None  # MERGE_WITH_CLUSTER 时指向另一簇
    display_name: str | None = None  # NEW_PERSON 时的新人显示名


def decision_field_error(decision: SpeakerDecision) -> str | None:
    """决定的字段级规则：返回错误文案，None 表示合法。

    规则集中在领域层；API 层只负责把它翻译成 422，不得自己再写一套。
    """
    if decision.kind in {DecisionKind.REASSIGN, DecisionKind.LINK_EXISTING}:
        if decision.person_id is None:
            return f"{decision.kind.value} 决定必须提供 person_id"
    if decision.kind == DecisionKind.NEW_PERSON:
        if not (decision.display_name or "").strip():
            return "NEW_PERSON 决定必须提供 display_name"
    if decision.kind == DecisionKind.MERGE_WITH_CLUSTER:
        if decision.merge_into_cluster_id is None:
            return "MERGE_WITH_CLUSTER 决定必须提供 merge_into_cluster_id"
        if decision.merge_into_cluster_id == decision.cluster_id:
            return "MERGE_WITH_CLUSTER 不能把簇合并进自己"
    return None


class ReviewIncomplete(Exception):
    def __init__(self, missing_cluster_ids: list[str]) -> None:
        super().__init__(f"以下说话人卡还没有决定: {missing_cluster_ids}")
        self.missing_cluster_ids = missing_cluster_ids


def review_complete(
    cards: list[SpeakerCard], decisions: list[SpeakerDecision]
) -> bool:
    """每张卡恰有一个决定，且没有多余/重复决定。"""
    card_ids = {c.cluster_id for c in cards}
    decided_ids = [d.cluster_id for d in decisions]
    if len(decided_ids) != len(set(decided_ids)):
        return False
    if set(decided_ids) != card_ids:
        return False
    return True


def missing_decisions(
    cards: list[SpeakerCard], decisions: list[SpeakerDecision]
) -> list[str]:
    decided = {d.cluster_id for d in decisions}
    return [c.cluster_id for c in cards if c.cluster_id not in decided]


def has_unconfirmed_speakers(decisions: list[SpeakerDecision]) -> bool:
    """有任一「未知类」决定 → 纪要须标记「含未确认说话人」。"""
    return any(d.kind in UNCONFIRMED_KINDS for d in decisions)
