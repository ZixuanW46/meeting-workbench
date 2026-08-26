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


class MeetingResponse(BaseModel):
    id: str
    title: str
    state: str
    expected_speakers: int | None
    hotwords: list[str]
    created_at: datetime


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]
