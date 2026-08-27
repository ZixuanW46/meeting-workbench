from meeting_domain import REVIEW_CLIP_LIMIT, select_spread_windows


def test_clip_limit_is_five():
    # 产品口径：每位说话人最多 5 条试听片段。
    assert REVIEW_CLIP_LIMIT == 5


def test_few_windows_are_all_kept_in_time_order():
    windows = [(10.0, 12.0), (0.0, 2.0), (5.0, 6.0)]

    assert select_spread_windows(windows) == [(0.0, 2.0), (5.0, 6.0), (10.0, 12.0)]


def test_empty_input_returns_empty():
    assert select_spread_windows([]) == []


def test_dense_head_does_not_monopolize_selection():
    # 真机踩过的坑：取「前 N 段」时片段全挤在开头几秒，
    # 用户听不出后半场是不是同一个人。分桶取样必须覆盖到尾部。
    windows = [(float(i), float(i) + 1.0) for i in range(30)]

    picked = select_spread_windows(windows)

    assert picked == [
        (0.0, 1.0),
        (6.0, 7.0),
        (12.0, 13.0),
        (18.0, 19.0),
        (24.0, 25.0),
    ]


def test_longest_window_wins_within_each_bucket():
    windows = [
        (0.0, 1.0),
        (2.0, 5.0),  # 桶 1 最长
        (10.0, 11.0),
        (11.5, 12.0),
        (20.0, 21.0),
        (22.0, 26.0),  # 桶 4 最长
        (29.0, 30.0),
    ]

    picked = select_spread_windows(windows)

    assert (2.0, 5.0) in picked
    assert (22.0, 26.0) in picked
    assert (11.5, 12.0) not in picked  # 同桶里输给更长的 (10,11)
    assert len(picked) == 5


def test_empty_buckets_are_backfilled_by_duration():
    # 发言集中在头尾两处、中间时段没人说话：空桶按时长补齐，仍出满 limit 条。
    windows = [
        (0.0, 4.0),
        (1.0, 2.0),
        (2.5, 3.0),
        (100.0, 106.0),
        (107.0, 108.0),
        (109.0, 109.5),
    ]

    picked = select_spread_windows(windows)

    assert len(picked) == 5
    assert (0.0, 4.0) in picked
    assert (100.0, 106.0) in picked
    # 补齐时优先较长片段：0.5s 残段是最后才轮到的。
    assert (109.0, 109.5) not in picked


def test_output_is_chronological_and_deduplicated():
    windows = [(float(i) * 3, float(i) * 3 + 2.0) for i in range(12)]

    picked = select_spread_windows(windows)

    assert picked == sorted(picked)
    assert len(picked) == len(set(picked)) == 5


def test_custom_limit_is_respected():
    windows = [(float(i) * 2, float(i) * 2 + 1.0) for i in range(10)]

    assert len(select_spread_windows(windows, limit=3)) == 3
