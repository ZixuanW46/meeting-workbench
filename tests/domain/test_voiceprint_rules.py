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


def _matching_rule():
    """余弦匹配规则在真实声纹修复落地前不存在：呈现清晰的缺实现红灯。"""
    module = importlib.import_module("meeting_domain.voiceprint")
    return module.match_voiceprint, module.SuggestionTier


def test_identical_vector_matches_with_high_tier():
    match_voiceprint, SuggestionTier = _matching_rule()

    match = match_voiceprint((1.0, 0.0), {"p1": [(1.0, 0.0)]})

    assert match is not None
    assert match.person_id == "p1"
    assert match.tier is SuggestionTier.HIGH


def test_cosine_at_high_threshold_is_still_high_tier():
    # (9,12) 与 (1,0) 的余弦恰为 0.6：档位边界含等于。
    match_voiceprint, SuggestionTier = _matching_rule()

    match = match_voiceprint((9.0, 12.0), {"p1": [(1.0, 0.0)]})

    assert match is not None
    assert match.tier is SuggestionTier.HIGH


def test_mid_band_cosine_matches_with_uncertain_tier():
    # (1,√3) 与 (1,0) 的余弦恰为 0.5：给建议但档位是「需判断」。
    match_voiceprint, SuggestionTier = _matching_rule()

    match = match_voiceprint((1.0, 3.0**0.5), {"p1": [(1.0, 0.0)]})

    assert match is not None
    assert match.person_id == "p1"
    assert match.tier is SuggestionTier.UNCERTAIN


def test_low_cosine_returns_no_match():
    # (1,4) 与 (1,0) 的余弦约 0.24：不足以打扰用户，宁可不建议。
    match_voiceprint, _ = _matching_rule()

    assert match_voiceprint((1.0, 4.0), {"p1": [(1.0, 0.0)]}) is None


def test_empty_voiceprint_library_returns_no_match():
    match_voiceprint, _ = _matching_rule()

    assert match_voiceprint((1.0, 0.0), {}) is None


def test_most_similar_person_wins():
    match_voiceprint, SuggestionTier = _matching_rule()

    match = match_voiceprint(
        (3.0, 4.0),
        {"p-cos-0.6": [(1.0, 0.0)], "p-cos-0.8": [(0.0, 1.0)]},
    )

    assert match is not None
    assert match.person_id == "p-cos-0.8"
    assert match.tier is SuggestionTier.HIGH


def test_dimension_mismatch_never_matches_nor_crashes():
    # 换声纹后端后库里可能留着旧维度向量：跳过而不是崩溃或乱配。
    match_voiceprint, _ = _matching_rule()

    assert match_voiceprint((1.0, 0.0), {"p1": [(1.0, 0.0, 0.0)]}) is None


def test_zero_norm_vectors_never_match():
    match_voiceprint, _ = _matching_rule()

    assert match_voiceprint((0.0, 0.0), {"p1": [(1.0, 0.0)]}) is None
    assert match_voiceprint((1.0, 0.0), {"p1": [(0.0, 0.0)]}) is None


def _template_rule():
    """多模板规则在实现前呈现清晰的缺实现红灯。"""
    module = importlib.import_module("meeting_domain.voiceprint")
    return module.plan_enrollment, module.TEMPLATE_CAP, module.TEMPLATE_REDUNDANCY_THRESHOLD


def test_match_takes_best_template_of_each_person():
    # 同一个人换了环境：多模板里只要有一条接得住就命中。
    match_voiceprint, SuggestionTier = _matching_rule()

    match = match_voiceprint(
        (1.0, 0.0),
        {"p1": [(1.0, 4.0), (1.0, 0.0)], "p2": [(0.0, 1.0)]},
    )

    assert match is not None
    assert match.person_id == "p1"
    assert match.tier is SuggestionTier.HIGH


def test_person_with_empty_template_list_never_matches():
    match_voiceprint, _ = _matching_rule()

    assert match_voiceprint((1.0, 0.0), {"p1": []}) is None


def test_plan_enrollment_appends_when_under_cap():
    plan_enrollment, _, _ = _template_rule()

    plan = plan_enrollment([(0.0, 1.0)], (1.0, 0.0))

    assert plan.action == "append"
    assert plan.replace_index is None


def test_plan_enrollment_appends_to_empty_library():
    plan_enrollment, _, _ = _template_rule()

    assert plan_enrollment([], (1.0, 0.0)).action == "append"


def test_plan_enrollment_replaces_redundant_template():
    # 与现有模板余弦 ≥0.9：没有信息增益，替换最相似那条以刷新录音条件。
    plan_enrollment, _, _ = _template_rule()

    plan = plan_enrollment(
        [(0.0, 1.0), (0.9, 0.4358898943540673)],  # 第二条与候选余弦恰为 0.9
        (1.0, 0.0),
    )

    assert plan.action == "replace"
    assert plan.replace_index == 1


def test_template_cap_is_five():
    _, cap, _ = _template_rule()

    assert cap == 5


def test_plan_enrollment_appends_overflow_slot_at_cap():
    # 满 5 条时第 6 条照常入库：淘汰哪条由用户在声纹库页试听后自己删，
    # 系统不做自动淘汰。
    plan_enrollment, cap, _ = _template_rule()
    existing = [(1.0, float(i * 4 + 1)) for i in range(cap)]

    plan = plan_enrollment(existing, (1.0, -20.0))

    assert plan.action == "append"


def test_plan_enrollment_skips_when_over_cap_until_user_prunes():
    # 已在超限状态（6 条）：暂停继续入库，等用户删到 5 条以内。
    plan_enrollment, cap, _ = _template_rule()
    existing = [(1.0, float(i * 4 + 1)) for i in range(cap + 1)]

    plan = plan_enrollment(existing, (1.0, -20.0))

    assert plan.action == "skip"
    assert plan.replace_index is None


def test_plan_enrollment_redundant_replace_still_works_over_cap():
    # 超限期间同环境重复确认仍然只是刷新那条，不新增行数。
    plan_enrollment, cap, _ = _template_rule()
    existing = [(1.0, float(i * 4 + 1)) for i in range(cap + 1)]

    plan = plan_enrollment(existing, existing[2])

    assert plan.action == "replace"
    assert plan.replace_index == 2


@pytest.mark.parametrize("quality", [0.0, 1.0])
def test_nearest_confirmed_is_never_enrolled(quality):
    # 就近归属的音频是声纹最弱的尾簇：不许进声纹库污染模板。
    _, eligible_for_enrollment = _voiceprint_rule()
    decision = SpeakerDecision(cluster_id="S9", kind=DecisionKind.NEAREST_CONFIRMED)

    assert eligible_for_enrollment(decision, quality) is False
