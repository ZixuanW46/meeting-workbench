import pytest

from meeting_domain import (
    DecisionKind,
    FakeMeetingPipeline,
    MeetingState,
    ReviewIncomplete,
    SpeakerCard,
    SpeakerDecision,
)

CARDS = [
    SpeakerCard("S1", suggested_person_id="p-zhang"),
    SpeakerCard("S2", suggested_person_id=None),
]

FULL_DECISIONS = [
    SpeakerDecision("S1", DecisionKind.CONFIRM),
    SpeakerDecision("S2", DecisionKind.KEEP_UNKNOWN),
]


def test_runs_from_draft_to_awaiting_review():
    p = FakeMeetingPipeline(cards=CARDS)
    assert p.state == MeetingState.DRAFT
    assert p.run_until_review() == MeetingState.AWAITING_SPEAKER_REVIEW


def test_confirm_blocked_until_every_card_decided():
    p = FakeMeetingPipeline(cards=CARDS)
    p.run_until_review()
    with pytest.raises(ReviewIncomplete) as exc:
        p.confirm_speakers([SpeakerDecision("S1", DecisionKind.CONFIRM)])
    assert exc.value.missing_cluster_ids == ["S2"]
    assert p.state == MeetingState.AWAITING_SPEAKER_REVIEW


def test_fixture_confirmation_pushes_to_ready():
    p = FakeMeetingPipeline(cards=CARDS)
    p.run_until_review()
    assert p.confirm_speakers(FULL_DECISIONS) == MeetingState.GENERATING_MINUTES
    assert p.finish_minutes(cli_ok=True) == MeetingState.READY


def test_minutes_cli_failure_is_partial_ready_and_retryable():
    p = FakeMeetingPipeline(cards=CARDS)
    p.run_until_review()
    p.confirm_speakers(FULL_DECISIONS)
    assert p.finish_minutes(cli_ok=False) == MeetingState.PARTIAL_READY
    assert p.retry_minutes() == MeetingState.GENERATING_MINUTES
    assert p.finish_minutes(cli_ok=True) == MeetingState.READY


def test_cancel_from_review_stop_point():
    p = FakeMeetingPipeline(cards=CARDS)
    p.run_until_review()
    assert p.cancel() == MeetingState.CANCELED
