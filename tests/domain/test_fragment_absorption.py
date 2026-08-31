from __future__ import annotations

import math

from meeting_domain import plan_fragment_absorption


def _unit(x: float, y: float) -> tuple[float, float]:
    norm = math.hypot(x, y)
    return (x / norm, y / norm)


def test_real_distribution_fragments_absorb_into_closest_major():
    clusters = [
        ("S1", 420.0, _unit(1.0, 0.0)),
        ("S2", 360.0, _unit(0.0, 1.0)),
        ("S3", 240.0, _unit(-1.0, 0.0)),
    ]
    for index in range(5):
        clusters.append((f"F1_{index}", 3.0 + index, _unit(1.0, 0.08 + index * 0.01)))
        clusters.append((f"F2_{index}", 4.0 + index, _unit(0.06 + index * 0.01, 1.0)))
        clusters.append((f"F3_{index}", 5.0 + index, _unit(-1.0, 0.07 + index * 0.01)))

    plan = plan_fragment_absorption(clusters, max_fragment_seconds=20.0)

    assert len(plan) == 15
    assert all(key.startswith("F") for key in plan)
    assert set(plan.values()) <= {"S1", "S2", "S3"}
    assert {target for key, target in plan.items() if key.startswith("F1_")} == {"S1"}
    assert {target for key, target in plan.items() if key.startswith("F2_")} == {"S2"}
    assert {target for key, target in plan.items() if key.startswith("F3_")} == {"S3"}


def test_fragment_over_distance_threshold_is_kept():
    plan = plan_fragment_absorption(
        [
            ("S1", 60.0, (1.0, 0.0)),
            ("S9", 8.0, (0.0, 1.0)),
        ],
        max_fragment_seconds=20.0,
    )

    assert plan == {}


def test_fragment_without_embedding_is_kept():
    plan = plan_fragment_absorption(
        [
            ("S1", 60.0, (1.0, 0.0)),
            ("S9", 8.0, None),
            ("S8", 8.0, (0.0, 0.0)),
        ],
        max_fragment_seconds=20.0,
    )

    assert plan == {}


def test_no_major_cluster_returns_empty_plan():
    plan = plan_fragment_absorption(
        [
            ("S1", 12.0, (1.0, 0.0)),
            ("S2", 8.0, (1.0, 0.1)),
        ],
        max_fragment_seconds=20.0,
    )

    assert plan == {}


def test_total_equal_threshold_counts_as_major():
    plan = plan_fragment_absorption(
        [
            ("S1", 20.0, (1.0, 0.0)),
            ("S9", 8.0, (1.0, 0.1)),
        ],
        max_fragment_seconds=20.0,
    )

    assert plan == {"S9": "S1"}


def test_zero_threshold_disables_absorption():
    plan = plan_fragment_absorption(
        [
            ("S1", 60.0, (1.0, 0.0)),
            ("S9", 8.0, (1.0, 0.1)),
        ],
        max_fragment_seconds=0.0,
    )

    assert plan == {}


def test_tie_breaks_by_distance_total_seconds_then_cluster_id():
    plan = plan_fragment_absorption(
        [
            ("S1", 60.0, (1.0, 0.0)),
            ("S2", 90.0, (1.0, 0.0)),
            ("S3", 90.0, (1.0, 0.0)),
            ("S9", 8.0, (1.0, 0.0)),
        ],
        max_fragment_seconds=20.0,
    )

    assert plan == {"S9": "S2"}


def test_plan_keys_are_fragments_and_values_are_majors():
    clusters = [
        ("S1", 20.0, (1.0, 0.0)),
        ("S2", 19.999, (1.0, 0.01)),
        ("S3", 40.0, (0.0, 1.0)),
        ("S4", 10.0, (0.0, 1.0)),
    ]

    plan = plan_fragment_absorption(clusters, max_fragment_seconds=20.0)

    assert set(plan) == {"S2", "S4"}
    assert set(plan.values()) == {"S1", "S3"}
