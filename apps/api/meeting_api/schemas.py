from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class MeetingCreate(BaseModel):
    # 选填：留空或空白 = 未命名，上传后取文件名、纪要后自动命名；填了就是用户命名。
    title: str | None = Field(default=None, max_length=200)
    # 会议发生日；不填则按音频文件名或创建日推断。
    meeting_date: date | None = None
    expected_speakers: int | None = Field(default=None, ge=1)
    # 会议语言：英文会议转写与清洗输出英文原文，纪要仍用中文撰写。
    language: Literal["zh", "en"] = "zh"
    hotwords: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def blank_title_as_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("hotwords")
    @classmethod
    def hotwords_clean(cls, value: list[str]) -> list[str]:
        # 去首尾空白、去空项、去重且保序；空列表合法
        cleaned: list[str] = []
        for word in value:
            stripped = word.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned


class MeetingUpdate(BaseModel):
    """PATCH 只改给出的字段：标题、会议日期、语言各自可选，但至少要给一个。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    meeting_date: date | None = None
    # 改语言不触发任何状态迁移，仅在下一次转写/重转写时生效。
    language: Literal["zh", "en"] | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set & {"title", "meeting_date", "language"}:
            raise ValueError("至少提供 title、meeting_date 或 language 之一")
        return self


class MeetingResponse(BaseModel):
    id: str
    title: str
    state: str
    expected_speakers: int | None
    language: Literal["zh", "en"]
    hotwords: list[str]
    created_at: datetime
    # 生效的会议日期与来源：user=用户填写 / filename=音频文件名 / created=创建日。
    meeting_date: date
    meeting_date_source: Literal["user", "filename", "created"]
    speakers: list[str]
    unknown_speaker_count: int
    # FAILED / PARTIAL_READY 的失败原因，给人看的一句话；不含服务器路径。
    processing_error: str | None = None


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]


class UploadResponse(BaseModel):
    size: int
    sha256: str


class ProgressResponse(BaseModel):
    state: str
    processing_step: str | None
    # 步骤内进度，如清洗「3/12」；没有就是 None。
    detail: str | None = None
    seq: int
