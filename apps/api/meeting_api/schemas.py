from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    expected_speakers: int | None = Field(default=None, ge=1)
    hotwords: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

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


class MeetingResponse(BaseModel):
    id: str
    title: str
    state: str
    expected_speakers: int | None
    hotwords: list[str]
    created_at: datetime


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]
