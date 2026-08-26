from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    expected_speakers: int | None = None
    hotwords: list[str] = Field(default_factory=list)


class MeetingResponse(BaseModel):
    id: str
    title: str
    state: str
    expected_speakers: int | None
    hotwords: list[str]
    created_at: datetime


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]
