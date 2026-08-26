"""词语库不可变快照规则。"""

from __future__ import annotations

from collections.abc import Iterable


def snapshot(
    global_words: Iterable[str],
    meeting_words: Iterable[str],
) -> tuple[str, ...]:
    """合并、去重并稳定排序，返回与输入容器无共享状态的值对象。"""
    return tuple(
        sorted(
            {
                stripped
                for word in (*global_words, *meeting_words)
                if (stripped := word.strip())
            }
        )
    )
