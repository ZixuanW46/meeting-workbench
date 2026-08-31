from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from meeting_api.models import HotwordEntry

router = APIRouter(prefix="/api/hotwords")


class HotwordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("word")
    @classmethod
    def word_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("词语不能为空")
        return stripped

    @field_validator("note", mode="before")
    @classmethod
    def empty_note_as_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class HotwordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def empty_note_as_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class HotwordResponse(BaseModel):
    id: str
    word: str
    note: str | None


class HotwordListResponse(BaseModel):
    items: list[HotwordResponse]


@router.get("", response_model=HotwordListResponse)
def list_hotwords(request: Request) -> HotwordListResponse:
    with request.app.state.session_factory() as session:
        entries = session.scalars(
            select(HotwordEntry).order_by(HotwordEntry.word, HotwordEntry.id)
        ).all()
        return HotwordListResponse(
            items=[
                HotwordResponse(id=entry.id, word=entry.word, note=entry.note)
                for entry in entries
            ]
        )


@router.post("", response_model=HotwordResponse, status_code=status.HTTP_201_CREATED)
def create_hotword(payload: HotwordCreate, request: Request) -> HotwordResponse:
    with request.app.state.session_factory() as session:
        entry = HotwordEntry(word=payload.word, note=payload.note)
        session.add(entry)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="词语已存在",
            ) from exc
        session.refresh(entry)
        return HotwordResponse(id=entry.id, word=entry.word, note=entry.note)


@router.patch("/{entry_id}", response_model=HotwordResponse)
def update_hotword_note(
    entry_id: str, payload: HotwordPatch, request: Request
) -> HotwordResponse:
    with request.app.state.session_factory() as session:
        entry = session.get(HotwordEntry, entry_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="词语不存在")
        entry.note = payload.note
        session.commit()
        return HotwordResponse(id=entry.id, word=entry.word, note=entry.note)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hotword(entry_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        entry = session.get(HotwordEntry, entry_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="词语不存在")
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
