"""纪要提示词：把逐字稿包成明确的任务指令再交给本机 CLI。

裸逐字稿会让 CLI 自由发挥（输出解释、评论运行环境、猜测身份）；
指令固定输出结构与边界。磁盘上的 transcript.txt 始终保存纯逐字稿。
"""

from __future__ import annotations

from pathlib import Path

MINUTES_PROMPT_INSTRUCTIONS = (
    "你是会议纪要助手。请根据下面的会议逐字稿，用中文输出一份 Markdown 会议纪要，"
    "结构依次为：一级标题（会议主题）、参会人、议题与结论、行动项（表格列：事项、"
    "负责人、时间；没有行动项就写「无」）。\n"
    "要求：只输出纪要正文，不要任何前后说明、致歉或对工具与运行环境的评论；"
    "不要编造逐字稿之外的事实；说话人身份未确认时按逐字稿中的标签（如「未知说话人"
    "（S1）」）引用，不要猜测真实姓名。\n"
)

# 就近归属的发言署名可信度低于人工确认：让模型对出自这些行的关键内容标（待核）。
NEAREST_NOTE = (
    "逐字稿中署名带「（就近归属）」的发言，其身份来自声纹就近归属、可信度低于"
    "人工确认；关键结论或行动项若出自这些发言，请在其后标注（待核）。\n"
)

# 兼容旧引用：完整默认头 = 指令 + 逐字稿引导行。
MINUTES_PROMPT_HEADER = f"{MINUTES_PROMPT_INSTRUCTIONS}\n会议逐字稿：\n"


def build_minutes_prompt(
    transcript: str,
    *,
    template: str | None = None,
    nearest_assigned: bool = False,
) -> str:
    """template 非空时覆盖默认指令头；逐字稿始终附在指令之后。

    nearest_assigned 表示逐字稿含「（就近归属）」署名，补一条措辞指令。
    """
    instructions = (
        f"{template.rstrip()}\n" if template is not None else MINUTES_PROMPT_INSTRUCTIONS
    )
    note = NEAREST_NOTE if nearest_assigned else ""
    return f"{instructions}{note}\n会议逐字稿：\n{transcript}"


def load_minutes_template(data_dir: Path) -> str | None:
    """读取 data_dir/minutes_prompt.md 作为自定义指令头；不存在或为空返回 None。

    用户借此不改代码即可调整纪要风格与结构；文件属本机数据，不入 git。
    """
    try:
        text = (data_dir / "minutes_prompt.md").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
