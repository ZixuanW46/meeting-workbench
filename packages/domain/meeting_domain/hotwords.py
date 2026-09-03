"""词语库不可变快照规则，以及 ASR 热词回声的清除规则。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence


def snapshot(*word_groups: Iterable[str]) -> tuple[str, ...]:
    """合并任意多层词表（全局词库 / 项目热词 / 本场热词）成不可变快照。

    去重、去首尾空白、稳定排序，返回与输入容器无共享状态的值对象。
    """
    return tuple(
        sorted(
            {
                stripped
                for group in word_groups
                for word in group
                if (stripped := word.strip())
            }
        )
    )


# 回声判定门槛：按快照顺序连着出现这么多个热词，人是不会这么说话的。
HOTWORD_ECHO_MIN_RUN = 3
_ECHO_SEPARATOR = re.compile(r"^[\s,，、;；/]*$")
_ECHO_TAIL = re.compile(r"^[\s。．.,，、;；]*")


def strip_hotword_echo(text: str, hotwords: Sequence[str]) -> str:
    """去掉 ASR 把热词表原样吐出来的片段，真人提到热词的句子原样保留。

    Qwen3-ASR 的热词走系统提示；拿到静音或极短音频时模型会把整张表按快照
    顺序念一遍。识别规则：连续 ≥3 个热词、彼此只隔分隔符、且在快照里的
    次序单调不减，就把这一串连同紧随的句号删掉。
    """
    if not text or len(hotwords) < HOTWORD_ECHO_MIN_RUN:
        return text
    order = {word: index for index, word in enumerate(hotwords)}
    # 长词优先匹配，避免「Will」吃掉「Willow」这类前缀重叠；按位置取不重叠的命中。
    longest_first = sorted(hotwords, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(word) for word in longest_first))
    matches = [(m.start(), m.end(), m.group(0)) for m in pattern.finditer(text)]
    if len(matches) < HOTWORD_ECHO_MIN_RUN:
        return text

    spans: list[tuple[int, int]] = []
    run_start = 0
    while run_start < len(matches):
        run_end = run_start
        while run_end + 1 < len(matches):
            prev_start, prev_stop, prev_word = matches[run_end]
            next_start, _, next_word = matches[run_end + 1]
            if not _ECHO_SEPARATOR.match(text[prev_stop:next_start]):
                break
            if order[next_word] < order[prev_word]:
                break
            run_end += 1
        if run_end - run_start + 1 >= HOTWORD_ECHO_MIN_RUN:
            first_start = matches[run_start][0]
            last_stop = matches[run_end][1]
            tail = _ECHO_TAIL.match(text[last_stop:])
            spans.append((first_start, last_stop + (tail.end() if tail else 0)))
        run_start = run_end + 1

    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, stop in spans:
        pieces.append(text[cursor:start])
        cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces).strip()
