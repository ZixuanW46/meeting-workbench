import pytest

from meeting_domain import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    MeetingState,
    can_transition,
    transition,
)

HAPPY_PATH = [
    MeetingState.DRAFT,
    MeetingState.UPLOADING,
    MeetingState.QUEUED,
    MeetingState.PROCESSING,
    MeetingState.AWAITING_SPEAKER_REVIEW,
    MeetingState.APPLYING_DECISIONS,
    MeetingState.GENERATING_MINUTES,
    MeetingState.READY,
]


def test_happy_path_is_fully_legal():
    for src, dst in zip(HAPPY_PATH, HAPPY_PATH[1:], strict=False):
        assert transition(src, dst) == dst


def test_cannot_skip_speaker_review():
    # 唯一人工停点：PROCESSING 不能直达纪要环节
    assert not can_transition(MeetingState.PROCESSING, MeetingState.APPLYING_DECISIONS)
    assert not can_transition(MeetingState.PROCESSING, MeetingState.GENERATING_MINUTES)
    assert not can_transition(MeetingState.PROCESSING, MeetingState.READY)


def test_awaiting_review_cannot_fail_only_confirm_or_cancel():
    allowed = TRANSITIONS[MeetingState.AWAITING_SPEAKER_REVIEW]
    assert allowed == frozenset({MeetingState.APPLYING_DECISIONS, MeetingState.CANCELED})


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        transition(MeetingState.DRAFT, MeetingState.READY)


def test_terminal_states_have_no_outgoing():
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()


def test_partial_ready_is_retryable_not_terminal():
    assert MeetingState.PARTIAL_READY not in TERMINAL_STATES
    assert can_transition(MeetingState.PARTIAL_READY, MeetingState.GENERATING_MINUTES)


def test_every_active_state_can_be_canceled():
    for state in ACTIVE_STATES:
        assert can_transition(state, MeetingState.CANCELED), state


def test_minutes_failure_goes_partial_ready():
    assert can_transition(MeetingState.GENERATING_MINUTES, MeetingState.PARTIAL_READY)


def test_transitions_cover_all_states():
    assert set(TRANSITIONS) == set(MeetingState)
