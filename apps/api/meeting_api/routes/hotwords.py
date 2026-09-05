from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meeting_api.models import HotwordEntry, Project, ProjectHotword

router = APIRouter(prefix="/api/hotwords")

HOTWORD_NOT_FOUND = "词语不存在"
PROJECT_NOT_FOUND = "项目不存在"
MOVE_SAME_LAYER = "来源与目标相同"
DEFAULT_PROJECT_HOTWORDS_MANAGED = "General 自动叠加所有项目的热词，不单独维护"
# 一次移动的上限：够用又不至于把一个请求撑成长事务。
MOVE_IDS_LIMIT = 200


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


class HotwordLayer(BaseModel):
    """一层热词：project_id 为 null 表示全局词库。"""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None


class HotwordMoveRequest(BaseModel):
    # from 是 Python 关键字，字段名只能另起，靠 alias 对上接口。
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_layer: HotwordLayer = Field(alias="from")
    to_layer: HotwordLayer = Field(alias="to")
    ids: list[str] = Field(min_length=1, max_length=MOVE_IDS_LIMIT)


class HotwordMoveResponse(BaseModel):
    moved: int
    merged: int


def _require_movable_layer(session: Session, layer: HotwordLayer) -> None:
    """全局层永远可动；项目层要存在，且不能是默认项目（它不维护自己的词）。"""
    if layer.project_id is None:
        return
    project = session.get(Project, layer.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=PROJECT_NOT_FOUND
        )
    if project.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DEFAULT_PROJECT_HOTWORDS_MANAGED,
        )


def _layer_entries(
    session: Session, layer: HotwordLayer
) -> list[HotwordEntry | ProjectHotword]:
    if layer.project_id is None:
        return list(session.scalars(select(HotwordEntry)).all())
    return list(
        session.scalars(
            select(ProjectHotword).where(ProjectHotword.project_id == layer.project_id)
        ).all()
    )


@router.post("/move", response_model=HotwordMoveResponse)
def move_hotwords(payload: HotwordMoveRequest, request: Request) -> HotwordMoveResponse:
    """把若干词条从一层搬到另一层：目标已有同词就合并，否则新建。整单一个事务。"""
    source_layer = payload.from_layer
    target_layer = payload.to_layer
    if source_layer.project_id == target_layer.project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=MOVE_SAME_LAYER
        )

    with request.app.state.session_factory() as session:
        _require_movable_layer(session, source_layer)
        _require_movable_layer(session, target_layer)

        by_id = {entry.id: entry for entry in _layer_entries(session, source_layer)}
        # 同一个 id 给两遍只搬一次；任一 id 不在来源层就整单不动。
        wanted: list[str] = []
        for entry_id in payload.ids:
            if entry_id not in by_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=HOTWORD_NOT_FOUND
                )
            if entry_id not in wanted:
                wanted.append(entry_id)

        target_by_word = {
            entry.word: entry for entry in _layer_entries(session, target_layer)
        }
        moved = 0
        merged = 0
        for entry_id in wanted:
            entry = by_id[entry_id]
            existing = target_by_word.get(entry.word)
            if existing is not None:
                # 合并：目标没写注解才用来源的说法，写了就以目标为准。
                if existing.note is None:
                    existing.note = entry.note
                merged += 1
            else:
                created: HotwordEntry | ProjectHotword
                if target_layer.project_id is None:
                    created = HotwordEntry(word=entry.word, note=entry.note)
                else:
                    created = ProjectHotword(
                        project_id=target_layer.project_id,
                        word=entry.word,
                        note=entry.note,
                    )
                session.add(created)
                target_by_word[entry.word] = created
                moved += 1
            session.delete(entry)
        session.commit()
        return HotwordMoveResponse(moved=moved, merged=merged)


@router.patch("/{entry_id}", response_model=HotwordResponse)
def update_hotword_note(
    entry_id: str, payload: HotwordPatch, request: Request
) -> HotwordResponse:
    with request.app.state.session_factory() as session:
        entry = session.get(HotwordEntry, entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=HOTWORD_NOT_FOUND
            )
        entry.note = payload.note
        session.commit()
        return HotwordResponse(id=entry.id, word=entry.word, note=entry.note)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hotword(entry_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        entry = session.get(HotwordEntry, entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=HOTWORD_NOT_FOUND
            )
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
