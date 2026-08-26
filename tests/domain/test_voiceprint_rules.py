from __future__ import annotations

import importlib

import pytest

from meeting_domain import DecisionKind, SpeakerDecision


def _voiceprint_rule():
    """把导入留在测试执行期，让 M10 实现前呈现清晰的缺实现红灯。"""
    module = importlib.import_module("meeting_domain.voiceprint")
    return module.VOICEPRINT_QUALITY_THRESHOLD, module.eligible_for_enrollment


@pytest.mark.parametrize(
    "kind",
    [
        DecisionKind.CONFIRM,
        DecisionKind.REASSIGN,
        DecisionKind.LINK_EXISTING,
        DecisionKind.NEW_PERSON,
    ],
)
def test_confirmed_identity_decisions_with_qualified_audio_are_eligible(kind):
    threshold, eligible_for_enrollment = _voiceprint_rule()
    decision = SpeakerDecision(cluster_id="S1", kind=kind)

    assert eligible_for_enrollment(decision, threshold) is True


@pytest.mark.parametrize(
    "kind",
    [DecisionKind.KEEP_UNKNOWN, DecisionKind.UNDECIDED_UNKNOWN],
)
@pytest.mark.parametrize("quality", [0.0, 1.0])
def test_unknown_decisions_are_never_eligible_regardless_of_quality(kind, quality):
    _, eligible_for_enrollment = _voiceprint_rule()
    decision = SpeakerDecision(cluster_id="S1", kind=kind)

    assert eligible_for_enrollment(decision, quality) is False


@pytest.mark.parametrize(
    "kind",
    [
        DecisionKind.CONFIRM,
        DecisionKind.REASSIGN,
        DecisionKind.LINK_EXISTING,
        DecisionKind.NEW_PERSON,
    ],
)
def test_confirmed_identity_below_quality_threshold_is_not_eligible(kind):
    threshold, eligible_for_enrollment = _voiceprint_rule()
    decision = SpeakerDecision(cluster_id="S1", kind=kind)

    assert eligible_for_enrollment(decision, threshold - 0.01) is False
