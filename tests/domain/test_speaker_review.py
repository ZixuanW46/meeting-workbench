from meeting_domain import (
    DecisionKind,
    SpeakerCard,
    SpeakerDecision,
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
