from meeting_domain.hotwords import snapshot


def test_snapshot_deduplicates_and_has_stable_sorted_immutable_value():
    first = snapshot(
        ["术语乙", "共同词", "术语乙"],
        ["本场词", "共同词"],
    )
    second = snapshot(
        ["共同词", "术语乙"],
        ["共同词", "本场词"],
    )

    assert first == second == ("共同词", "本场词", "术语乙")
    assert isinstance(first, tuple)


def test_snapshot_has_value_semantics_and_does_not_share_global_list():
    global_words = ["原有全局词"]
    frozen = snapshot(global_words, ["本场词"])

    global_words.append("事后新增词")

    assert frozen == ("原有全局词", "本场词")
