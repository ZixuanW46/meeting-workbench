from meeting_domain import (
    DecisionKind,
    SpeakerCard,
    SpeakerDecision,
    decision_field_error,
    has_unconfirmed_speakers,
    review_complete,
)
from meeting_domain.speaker_review import missing_decisions

CARDS = [
    SpeakerCard("S1", suggested_person_id="p-zhang"),
    SpeakerCard("S2", suggested_person_id=None),
]


def test_incomplete_when_a_card_has_no_decision():
    decisions = [SpeakerDecision("S1", DecisionKind.CONFIRM)]
    assert not review_complete(CARDS, decisions)
    assert missing_decisions(CARDS, decisions) == ["S2"]


def test_complete_when_every_card_decided():
    decisions = [
        SpeakerDecision("S1", DecisionKind.CONFIRM),
        SpeakerDecision("S2", DecisionKind.NEW_PERSON),
    ]
    assert review_complete(CARDS, decisions)


def test_keep_unknown_is_a_valid_decision_but_marks_minutes():
    decisions = [
        SpeakerDecision("S1", DecisionKind.CONFIRM),
        SpeakerDecision("S2", DecisionKind.UNDECIDED_UNKNOWN),
    ]
    assert review_complete(CARDS, decisions)
    assert has_unconfirmed_speakers(decisions)


def test_all_confirmed_means_no_unconfirmed_mark():
    decisions = [
        SpeakerDecision("S1", DecisionKind.CONFIRM),
        SpeakerDecision("S2", DecisionKind.LINK_EXISTING, person_id="p-li"),
    ]
    assert not has_unconfirmed_speakers(decisions)


def test_duplicate_or_stray_decisions_are_incomplete():
    duplicated = [
        SpeakerDecision("S1", DecisionKind.CONFIRM),
        SpeakerDecision("S1", DecisionKind.KEEP_UNKNOWN),
    ]
    assert not review_complete(CARDS, duplicated)

    stray = [
        SpeakerDecision("S1", DecisionKind.CONFIRM),
        SpeakerDecision("S2", DecisionKind.NEW_PERSON),
        SpeakerDecision("S99", DecisionKind.NEW_PERSON),
    ]
    assert not review_complete(CARDS, stray)


def test_decision_field_rules_live_in_domain():
    # 缺必填字段 → 报错文案
    assert decision_field_error(SpeakerDecision("S1", DecisionKind.REASSIGN))
    assert decision_field_error(SpeakerDecision("S1", DecisionKind.LINK_EXISTING))
    assert decision_field_error(SpeakerDecision("S2", DecisionKind.NEW_PERSON))
    assert decision_field_error(
        SpeakerDecision("S2", DecisionKind.NEW_PERSON, display_name="   ")
    )
    assert decision_field_error(SpeakerDecision("S2", DecisionKind.MERGE_WITH_CLUSTER))
    # 自合并非法
    assert decision_field_error(
        SpeakerDecision("S2", DecisionKind.MERGE_WITH_CLUSTER, merge_into_cluster_id="S2")
    )
    # 合法组合 → None
    assert decision_field_error(SpeakerDecision("S1", DecisionKind.CONFIRM)) is None
    assert decision_field_error(SpeakerDecision("S1", DecisionKind.KEEP_UNKNOWN)) is None
    assert decision_field_error(SpeakerDecision("S2", DecisionKind.UNDECIDED_UNKNOWN)) is None
    assert (
        decision_field_error(
            SpeakerDecision("S1", DecisionKind.REASSIGN, person_id="p-li")
        )
        is None
    )
    assert (
        decision_field_error(
            SpeakerDecision("S2", DecisionKind.NEW_PERSON, display_name="李雷")
        )
        is None
    )
    assert (
        decision_field_error(
            SpeakerDecision("S2", DecisionKind.MERGE_WITH_CLUSTER, merge_into_cluster_id="S1")
        )
        is None
    )


def test_nearest_confirmed_needs_no_extra_fields_and_is_not_unknown():
    # 就近归属产生身份：不需要附加字段；不算「未确认」，但也不入声纹库
    # （入库资格见 voiceprint 规则测试）。
    decision = SpeakerDecision(cluster_id="S9", kind=DecisionKind.NEAREST_CONFIRMED)

    assert decision_field_error(decision) is None
    assert has_unconfirmed_speakers([decision]) is False
