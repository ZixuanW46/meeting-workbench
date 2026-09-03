"""项目与项目热词：会议的组织单位，同时是热词的第二层。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meeting_api.models import Meeting, Project, ProjectHotword

router = APIRouter(prefix="/api/projects")

PROJECT_NOT_FOUND = "项目不存在"
PROJECT_DUPLICATE = "项目已存在"
HOTWORD_NOT_FOUND = "词语不存在"
HOTWORD_DUPLICATE = "词语已存在"
PROJECT_ORDER_INVALID = "ids 必须包含全部项目且不重复"


def _strip_or_reject(value: str, message: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(message)
    return stripped


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        return _strip_or_reject(value, "项目名不能为空")


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        return _strip_or_reject(value, "项目名不能为空")


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    meeting_count: int
    hotword_count: int
    position: int


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]


class ProjectOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str]


class ProjectHotwordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("word")
    @classmethod
    def word_not_blank(cls, value: str) -> str:
        return _strip_or_reject(value, "词语不能为空")

    @field_validator("note", mode="before")
    @classmethod
    def empty_note_as_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProjectHotwordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def empty_note_as_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProjectHotwordResponse(BaseModel):
    id: str
    word: str
    note: str | None


class ProjectHotwordListResponse(BaseModel):
    items: list[ProjectHotwordResponse]


def _counts(session: Session, project_ids: list[str]) -> dict[str, tuple[int, int]]:
    if not project_ids:
        return {}
    meetings = dict(
        session.execute(
            select(Meeting.project_id, func.count(Meeting.id))
            .where(Meeting.project_id.in_(project_ids))
            .group_by(Meeting.project_id)
        ).all()
    )
    hotwords = dict(
        session.execute(
            select(ProjectHotword.project_id, func.count(ProjectHotword.id))
            .where(ProjectHotword.project_id.in_(project_ids))
            .group_by(ProjectHotword.project_id)
        ).all()
    )
    return {
        project_id: (meetings.get(project_id, 0), hotwords.get(project_id, 0))
        for project_id in project_ids
    }


def _to_response(project: Project, counts: tuple[int, int] = (0, 0)) -> ProjectResponse:
    meeting_count, hotword_count = counts
    return ProjectResponse(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        meeting_count=meeting_count,
        hotword_count=hotword_count,
        position=project.position,
    )


def _require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=PROJECT_NOT_FOUND
        )
    return project


def _list_projects(session: Session) -> ProjectListResponse:
    """列表统一按 (position, name, id) 排；position 相同时退回名字保证稳定。"""
    projects = session.scalars(
        select(Project).order_by(Project.position, Project.name, Project.id)
    ).all()
    counts = _counts(session, [project.id for project in projects])
    return ProjectListResponse(
        items=[
            _to_response(project, counts.get(project.id, (0, 0)))
            for project in projects
        ]
    )


@router.get("", response_model=ProjectListResponse)
def list_projects(request: Request) -> ProjectListResponse:
    with request.app.state.session_factory() as session:
        return _list_projects(session)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> ProjectResponse:
    with request.app.state.session_factory() as session:
        # 追加到末尾：取当前最大 position + 1，没有项目时从 0 开始。
        max_position = session.scalar(select(func.max(Project.position)))
        position = 0 if max_position is None else max_position + 1
        project = Project(name=payload.name, position=position)
        session.add(project)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=PROJECT_DUPLICATE
            ) from exc
        session.refresh(project)
        return _to_response(project)


@router.put("/order", response_model=ProjectListResponse)
def reorder_projects(
    payload: ProjectOrderRequest, request: Request
) -> ProjectListResponse:
    """按给定顺序重排项目。ids 必须恰好是全部现有项目 id 的一个排列。"""
    with request.app.state.session_factory() as session:
        existing = set(session.scalars(select(Project.id)).all())
        if len(set(payload.ids)) != len(payload.ids) or set(payload.ids) != existing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=PROJECT_ORDER_INVALID,
            )
        for position, project_id in enumerate(payload.ids):
            session.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(position=position)
            )
        session.commit()
        return _list_projects(session)


@router.patch("/{project_id}", response_model=ProjectResponse)
def rename_project(
    project_id: str, payload: ProjectPatch, request: Request
) -> ProjectResponse:
    with request.app.state.session_factory() as session:
        project = _require_project(session, project_id)
        project.name = payload.name
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=PROJECT_DUPLICATE
            ) from exc
        session.refresh(project)
        counts = _counts(session, [project.id]).get(project.id, (0, 0))
        return _to_response(project, counts)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, request: Request) -> Response:
    """删项目不删会议：先把该项目下的会议置为「无项目」，再删项目（热词级联删）。"""
    with request.app.state.session_factory() as session:
        project = _require_project(session, project_id)
        # 不依赖 SQLite 的外键开关：显式置空，语义一眼可见。
        session.execute(
            update(Meeting)
            .where(Meeting.project_id == project_id)
            .values(project_id=None)
        )
        session.delete(project)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/hotwords", response_model=ProjectHotwordListResponse)
def list_project_hotwords(
    project_id: str, request: Request
) -> ProjectHotwordListResponse:
    with request.app.state.session_factory() as session:
        _require_project(session, project_id)
        entries = session.scalars(
            select(ProjectHotword)
            .where(ProjectHotword.project_id == project_id)
            .order_by(ProjectHotword.word, ProjectHotword.id)
        ).all()
        return ProjectHotwordListResponse(
            items=[
                ProjectHotwordResponse(id=entry.id, word=entry.word, note=entry.note)
                for entry in entries
            ]
        )


@router.post(
    "/{project_id}/hotwords",
    response_model=ProjectHotwordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_hotword(
    project_id: str, payload: ProjectHotwordCreate, request: Request
) -> ProjectHotwordResponse:
    with request.app.state.session_factory() as session:
        _require_project(session, project_id)
        entry = ProjectHotword(
            project_id=project_id, word=payload.word, note=payload.note
        )
        session.add(entry)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=HOTWORD_DUPLICATE
            ) from exc
        session.refresh(entry)
        return ProjectHotwordResponse(id=entry.id, word=entry.word, note=entry.note)


def _require_project_hotword(
    session: Session, project_id: str, entry_id: str
) -> ProjectHotword:
    entry = session.get(ProjectHotword, entry_id)
    # 词条不属于该项目时按「不存在」处理，不泄露其他项目的词条。
    if entry is None or entry.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=HOTWORD_NOT_FOUND
        )
    return entry


@router.patch(
    "/{project_id}/hotwords/{entry_id}", response_model=ProjectHotwordResponse
)
def update_project_hotword_note(
    project_id: str,
    entry_id: str,
    payload: ProjectHotwordPatch,
    request: Request,
) -> ProjectHotwordResponse:
    with request.app.state.session_factory() as session:
        _require_project(session, project_id)
        entry = _require_project_hotword(session, project_id, entry_id)
        entry.note = payload.note
        session.commit()
        return ProjectHotwordResponse(id=entry.id, word=entry.word, note=entry.note)


@router.delete(
    "/{project_id}/hotwords/{entry_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_project_hotword(project_id: str, entry_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        _require_project(session, project_id)
        entry = _require_project_hotword(session, project_id, entry_id)
        session.delete(entry)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
