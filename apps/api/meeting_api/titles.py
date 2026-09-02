"""会议标题的自动命名规则。

创建时填了标题 = 用户命名，之后不再自动改；留空则占位，上传后取录音文件名，
纪要生成后套用「YY-MM-DD：主题」模板（见 worker._auto_title_from_minutes）。
"""

from __future__ import annotations

from pathlib import Path

from meeting_api.models import Meeting

DEFAULT_MEETING_TITLE = "未命名会议"
TITLE_MAX_LENGTH = 200


def apply_filename_title(meeting: Meeting, filename: str | None) -> None:
    """未命名且用户没改过标题时，用录音文件名（去扩展名）先顶上。"""
    if meeting.title_user_edited or meeting.title != DEFAULT_MEETING_TITLE or not filename:
        return
    stem = Path(filename).stem.strip()
    if stem:
        meeting.title = stem[:TITLE_MAX_LENGTH]
