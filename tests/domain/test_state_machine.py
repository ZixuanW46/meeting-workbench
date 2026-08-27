import pytest

from meeting_domain import (
    ACTIVE_STATES,
    REOPENABLE_REVIEW_STATES,
    RETRANSCRIBABLE_STATES,
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
    assert allowed == frozenset(
        {
            MeetingState.APPLYING_DECISIONS,
            MeetingState.QUEUED,
            MeetingState.CANCELED,
        }
    )


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        transition(MeetingState.DRAFT, MeetingState.READY)


def test_failed_and_canceled_are_the_only_terminal_states_and_have_no_outgoing():
    assert TERMINAL_STATES == frozenset({MeetingState.FAILED, MeetingState.CANCELED})
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()


@pytest.mark.parametrize(
    "state",
    [
        MeetingState.AWAITING_SPEAKER_REVIEW,
        MeetingState.READY,
        MeetingState.PARTIAL_READY,
    ],
)
def test_explicit_retranscription_can_requeue_completed_transcription_states(state):
    assert transition(state, MeetingState.QUEUED) == MeetingState.QUEUED


@pytest.mark.parametrize("state", [MeetingState.FAILED, MeetingState.CANCELED])
def test_terminal_states_cannot_be_retranscribed(state):
    assert not can_transition(state, MeetingState.QUEUED)


def test_retranscribable_states_are_exactly_the_completed_transcription_states():
    assert RETRANSCRIBABLE_STATES == frozenset(
        {
            MeetingState.AWAITING_SPEAKER_REVIEW,
            MeetingState.READY,
            MeetingState.PARTIAL_READY,
        }
    )
    # UPLOADING → QUEUED 是上传完成边，仍然合法，但不属于可重转写状态。
    assert can_transition(MeetingState.UPLOADING, MeetingState.QUEUED)
    assert MeetingState.UPLOADING not in RETRANSCRIBABLE_STATES


@pytest.mark.parametrize(
    "state", [MeetingState.READY, MeetingState.PARTIAL_READY]
)
def test_completed_states_can_reopen_speaker_review(state):
    # 事后想改说话人决定（补名字/合并）不该被迫整场重转写：
    # 已完成状态可以只重开确认停点，确认后重出纪要。
    assert (
        transition(state, MeetingState.AWAITING_SPEAKER_REVIEW)
        == MeetingState.AWAITING_SPEAKER_REVIEW
    )


def test_reopenable_review_states_are_exactly_the_completed_states():
    assert REOPENABLE_REVIEW_STATES == frozenset(
        {MeetingState.READY, MeetingState.PARTIAL_READY}
    )
    # PROCESSING → AWAITING 是主链完成边，不属于重开。
    assert MeetingState.PROCESSING not in REOPENABLE_REVIEW_STATES


def test_partial_ready_is_retryable_not_terminal():
    assert MeetingState.PARTIAL_READY not in TERMINAL_STATES
    assert can_transition(MeetingState.PARTIAL_READY, MeetingState.GENERATING_MINUTES)


def test_every_active_state_can_be_canceled():
    # READY 可由用户显式重转写，但不再属于可取消的处理中会议。
    for state in ACTIVE_STATES - {MeetingState.READY}:
        assert can_transition(state, MeetingState.CANCELED), state


def test_minutes_failure_goes_partial_ready():
    assert can_transition(MeetingState.GENERATING_MINUTES, MeetingState.PARTIAL_READY)


def test_transitions_cover_all_states():
    assert set(TRANSITIONS) == set(MeetingState)
