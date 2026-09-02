"""会议日期解析：纪要日期锚点与标题模板用会议发生日，不用记录创建时刻。

优先级：用户显式填写 > 音频文件名里的日期 > 创建当天（本机时区）。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from meeting_api.minutes.prompt import meeting_date_from_created_at
from meeting_api.models import Meeting

MeetingDateSource = Literal["user", "filename", "created"]

# 录音笔与手机导出常见：2026-08-31、2026_08_31、20260831、2026.08.31。
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")


def date_from_filename(filename: str | None) -> date | None:
    if not filename:
        return None
    for match in _FILENAME_DATE_RE.finditer(filename):
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def resolve_meeting_date(meeting: Meeting) -> tuple[date, MeetingDateSource]:
    if meeting.meeting_date is not None:
        return meeting.meeting_date, "user"
    from_filename = date_from_filename(meeting.audio_filename)
    if from_filename is not None:
        return from_filename, "filename"
    return meeting_date_from_created_at(meeting.created_at), "created"
