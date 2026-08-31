"""纪要提示词：把逐字稿包成明确的任务指令再交给本机 CLI。

裸逐字稿会让 CLI 自由发挥（输出解释、评论运行环境、猜测身份）；
指令固定输出结构与边界。磁盘上的 transcript.txt 始终保存纯逐字稿。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path

MINUTES_PROMPT_INSTRUCTIONS = """你是会议纪要助手。请根据下面的会议逐字稿，用中文输出一份 Markdown 会议纪要，结构与信息密度仿照 PLAUD 纪要，依次包含：

一、一级标题：格式「YY-MM-DD：主题概括」（如「26-08-31：见山社团落地与升学辅导试点」），日期用附带的会议日期锚点换算成两位年；没有锚点且逐字稿也确认不了日期时只写主题。主题是一句凝练的内容概括，不写「会议纪要」四个字本身。

二、`**参会人员：**` 一行：罗列逐字稿中实际发言的人，每人只列一次；未确认身份的按原样引用（如「未知说话人（S2）」），不得猜测或改名；只被提及而未发言的人名后加「（提及）」。

三、开篇总览：一段 2～4 句、不带小标题的段落，说清本次会议围绕什么展开、覆盖哪几块议题、最重要的共识或产出是什么。

四、`## 议程时间轴`：依据逐字稿时间戳把会议划成 4～8 个阶段，每行一条，格式 `- mm:ss–mm:ss 阶段主题`（逐字稿时间戳已是分秒，超一小时为 h:mm:ss，直接取用）。

五、各议题详情：每个议题一个 `## 议题名` 二级标题，通常 3～6 个，超过 90 分钟的长会可放宽到 5～8 个——按实际信息量伸缩，不要让会议后半段的讨论被挤进一个大议题里过度压缩。相近的子话题（如同一产品的复盘与内测、同一人的回归与分工）并进同一议题，在要点层再分，不要为每个小话题另开二级标题。标题用「现状复盘与新机会」「反思与展望」这类主题短语。议题内是大纲式要点列表：
- 每个议题 3～6 条要点，每条以 `**要点小标题：**` 开头，后接提炼后的陈述——结论先行、事实跟上，保留具体数字、金额、日期、报价、比例等细节；人名、机构、渠道、账号名等具体线索同样保留，不要泛化成「某资源」「相关渠道」。
- 同一价格、日期或方案在会中被多次修改时，以会议最终认定的口径写入要点，不要把演进过程抹平成一个区间；早期版本仅在对比有意义时用括号简要带过（如「面试单节 2800 元（此前拟 2600）」）。但被提出后仍悬而未决的备选方案及其具体数字（如更高档定价选项、可能的提价空间），不要当作旧版本丢弃——写进对应要点或「待决问题与风险」。
- 写纪要体，不写发言流水账：不要每条都「某某表示」「某某提到」，说话人只在关键承诺、明确分歧或鲜明个人立场时点名。
- 多人各自的表态、并列的方案或渠道、成套的机制条款（如股权结构的各方安排、分档解锁规则），必须收进一条要点、用缩进子要点每项一行铺开（最多嵌一层），例如：
  `- **现有股权结构：** 各方安排：`
  `  - Will 与 Leo：自始基本平分。`
  `  - 张张：文旅线 5%，另有按营收分档解锁的激励。`
  不要把这类并列项各写成一条顶层要点，更不要把几套条款挤进同一条要点。
- 有分歧、悬而未决或语焉不详之处如实写「尚未确定」「存在疑问」，不要抹平。
- 该议题有明确结论或决定时，末尾加一条 `**结论：**`。

六、`## 后续跟进`：行动项按负责人分组，`**@负责人**` 独立一行，下面列 `- [ ] 事项（截止：日期，逐字稿未提就写「待定」）`；听不出负责人的事项统一归入 `**@待认领**`。整场会没有任何行动项就只写「无」。

七、`## 待决问题与风险`：罗列会上明确提出、但散会时仍没有结论、负责人或时间点的问题与风险，每条一行、写清悬在哪里（如「付款主体是学校还是学生未定」「导师质控流程尚无方案」）；只收录逐字稿里真实出现过的疑问或风险，不要自行推演，没有就写「无」。

硬性要求：
- 只输出纪要正文，不要任何前后说明、致歉或对工具与运行环境的评论。
- 通篇凝练、信息密度高；除关键表态外不逐句转述发言，不堆砌直接引语。
- 能从逐字稿内容确定会议日期时，把「明天」「下周二」这类相对时间换算成绝对日期（换算没把握就保留原词）。
- 逐字稿由语音转写而来，难免存在近音错词：撰写前请结合上下文和附带的公司术语表（如有）做适度纠正；把握不准的保留原词，不要为纠错改动事实或数字。
- 不得编造逐字稿之外的事实、数字、日期或负责人；拿不准的信息宁可省略或标注「待核」。
- 说话人身份未确认时一律按逐字稿中的标签引用，不要猜测真实姓名。
"""

# 兼容旧引用：完整默认头 = 指令 + 逐字稿引导行。
MINUTES_PROMPT_HEADER = f"{MINUTES_PROMPT_INSTRUCTIONS}\n会议逐字稿：\n"


def build_minutes_prompt(
    transcript: str,
    *,
    template: str | None = None,
    glossary: str | None = None,
    meeting_date: date | None = None,
) -> str:
    """template 非空时覆盖默认指令头；逐字稿始终附在指令之后。"""
    instructions = (
        f"{template.rstrip()}\n" if template is not None else MINUTES_PROMPT_INSTRUCTIONS
    )
    date_block = (
        f"会议日期：{meeting_date.isoformat()}（{_weekday_label(meeting_date)}）。"
        "标题日期与「明天」「下周二」等相对时间换算以此为锚点。"
        "若该日期与逐字稿内容明显矛盾，以逐字稿为准。\n"
        if meeting_date is not None
        else ""
    )
    glossary_block = (
        "公司术语表（逐字稿为语音识别产物，其中的近音误写请按下表纠正为标准写法；"
        f"注解仅供理解，不要照抄进纪要）：\n{glossary.rstrip()}\n"
        if glossary
        else ""
    )
    return f"{instructions}{date_block}{glossary_block}\n会议逐字稿：\n{transcript}"


def meeting_date_from_created_at(
    created_at: datetime,
    *,
    target_tz: tzinfo | None = None,
) -> date:
    """从会议创建时间取会议日期；SQLite 读回 naive 时按 UTC 解释。"""
    aware_created_at = (
        created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
    )
    return aware_created_at.astimezone(target_tz).date()


def _weekday_label(value: date) -> str:
    return ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[value.weekday()]


def build_minutes_glossary(
    hotword_entries: Sequence[tuple[str, str | None]],
    file_glossary: str | None,
) -> str | None:
    """组合词库注解与用户自由补充；两者都空时不渲染术语表块。"""
    hotword_lines = [
        f"- {word}：{note.strip()}" if note and note.strip() else f"- {word}"
        for word, note in hotword_entries
    ]
    parts = [part for part in ["\n".join(hotword_lines), file_glossary] if part]
    return "\n\n".join(parts) if parts else None


def load_minutes_template(data_dir: Path) -> str | None:
    """读取 data_dir/minutes_prompt.md 作为自定义指令头；不存在或为空返回 None。

    用户借此不改代码即可调整纪要风格与结构；文件属本机数据，不入 git。
    """
    try:
        text = (data_dir / "minutes_prompt.md").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def load_minutes_glossary(data_dir: Path) -> str | None:
    """读取 data_dir/minutes_glossary.md 作为公司术语表；不存在或为空返回 None。

    用户借此维护专有名词与注解；文件属本机数据，不入 git。
    """
    try:
        text = (data_dir / "minutes_glossary.md").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
