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

    @field_validator("word")
    @classmethod
    def word_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("词语不能为空")
        return stripped


class HotwordResponse(BaseModel):
    id: str
    word: str


class HotwordListResponse(BaseModel):
    items: list[HotwordResponse]


@router.get("", response_model=HotwordListResponse)
def list_hotwords(request: Request) -> HotwordListResponse:
    with request.app.state.session_factory() as session:
        entries = session.scalars(
            select(HotwordEntry).order_by(HotwordEntry.word, HotwordEntry.id)
        ).all()
        return HotwordListResponse(
            items=[HotwordResponse(id=entry.id, word=entry.word) for entry in entries]
        )


@router.post("", response_model=HotwordResponse, status_code=status.HTTP_201_CREATED)
def create_hotword(payload: HotwordCreate, request: Request) -> HotwordResponse:
    with request.app.state.session_factory() as session:
        entry = HotwordEntry(word=payload.word)
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
        return HotwordResponse(id=entry.id, word=entry.word)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hotword(entry_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        entry = session.get(HotwordEntry, entry_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="词语不存在")
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
