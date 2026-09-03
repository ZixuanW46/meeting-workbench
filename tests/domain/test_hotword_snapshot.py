from meeting_domain.hotwords import snapshot, strip_hotword_echo


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


SNAPSHOT = ("Blue Education", "CUES", "Eddie", "Leo", "Will", "咖彼", "荣兴园", "见山")


def test_pure_hotword_echo_becomes_empty():
    # Qwen3-ASR 拿到极短或静音片段时会把系统提示里的热词表原样吐出来。
    echo = "Blue Education, CUES, Eddie, Leo, Will, 咖彼, 荣兴园, 见山。"
    assert strip_hotword_echo(echo, SNAPSHOT) == ""


def test_echo_embedded_in_sentence_is_removed_but_speech_kept():
    text = (
        "真的，基本上都耗在这个店里。"
        "Blue Education、CUES、Eddie、Leo、Will、咖彼、荣兴园、见山。"
        "如果你一天不在的话"
    )
    assert strip_hotword_echo(text, SNAPSHOT) == "真的，基本上都耗在这个店里。如果你一天不在的话"


def test_real_mentions_of_hotwords_are_untouched():
    # 真人提到一两个热词、或不按快照顺序连着提三个，都不是回声。
    sentence = "Will 和 Leo 明天去荣兴园。"
    assert strip_hotword_echo(sentence, SNAPSHOT) == sentence
    assert strip_hotword_echo("Will、Leo、Eddie 都到了", SNAPSHOT) == "Will、Leo、Eddie 都到了"


def test_three_consecutive_in_snapshot_order_is_the_threshold():
    assert strip_hotword_echo("CUES, Eddie, Leo", SNAPSHOT) == ""
    assert strip_hotword_echo("CUES, Eddie 来了", SNAPSHOT) == "CUES, Eddie 来了"


def test_snapshot_merges_any_number_of_word_groups():
    # 全局词库 + 项目热词 + 本场热词三层叠加，语义仍是合并去重稳定排序。
    frozen = snapshot(
        ["全局词", "共同词"],
        ["项目词", "共同词"],
        ["本场词", " 共同词 "],
    )

    assert frozen == ("全局词", "共同词", "本场词", "项目词")


def test_snapshot_accepts_single_group_and_no_group():
    assert snapshot() == ()
    assert snapshot(["只有一组", "只有一组"]) == ("只有一组",)
