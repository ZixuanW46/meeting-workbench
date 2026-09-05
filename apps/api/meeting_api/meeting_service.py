"""会议记录的构造与出参组装：新建会议与 Plaud 导入共用同一套规则。"""

from __future__ import annotations

import json
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meeting_api.meeting_date import resolve_meeting_date
from meeting_api.models import Meeting, Person, Project, SpeakerCluster
from meeting_api.schemas import MeetingCreate, MeetingResponse

type SpeakerSummary = tuple[list[str], int]

EMPTY_SPEAKER_SUMMARY: SpeakerSummary = ([], 0)

# 默认项目的出厂名；用户可以改名，所以代码里只认 Project.is_default 标记。
DEFAULT_PROJECT_NAME = "General"


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


def ensure_default_project(session: Session) -> Project:
    """保证库里有且只有一个默认项目；没有就建一个 General 追加到末尾。"""
    project = session.scalars(
        select(Project).where(Project.is_default.is_(True))
    ).first()
    if project is not None:
        return project
    max_position = session.scalar(select(func.max(Project.position)))
    project = Project(
        name=DEFAULT_PROJECT_NAME,
        position=0 if max_position is None else max_position + 1,
        is_default=True,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def default_project_id(session: Session) -> str:
    return ensure_default_project(session).id


def build_meeting(
    session: Session,
    payload: MeetingCreate,
    *,
    title: str,
    title_user_edited: bool,
    meeting_date: date | None,
    plaud_file_id: str | None = None,
) -> Meeting:
    """按创建请求造一条会议；标题与日期由调用方定（来源不同规则不同）。

    不给项目就落默认项目——会议永远有归属，没有「无项目」这个状态。
    """
    return Meeting(
        title=title,
        title_user_edited=title_user_edited,
        meeting_date=meeting_date,
        expected_speakers=payload.expected_speakers,
        language=payload.language,
        project_id=payload.project_id or default_project_id(session),
        hotwords_json=json.dumps(payload.hotwords, ensure_ascii=False),
        plaud_file_id=plaud_file_id,
    )


def speaker_summaries(
    session: Session, meeting_ids: list[str]
) -> dict[str, SpeakerSummary]:
    if not meeting_ids:
        return {}

    rows = session.execute(
        select(
            SpeakerCluster.meeting_id,
            SpeakerCluster.person_id,
            SpeakerCluster.total_seconds,
            Person.display_name,
        )
        .outerjoin(Person, Person.id == SpeakerCluster.person_id)
        .where(SpeakerCluster.meeting_id.in_(meeting_ids))
    ).all()
    by_meeting: dict[str, list[tuple[str | None, float, str | None]]] = {}
    for meeting_id, person_id, total_seconds, display_name in rows:
        by_meeting.setdefault(meeting_id, []).append(
            (person_id, total_seconds, display_name)
        )

    summaries: dict[str, SpeakerSummary] = {}
    for meeting_id, clusters in by_meeting.items():
        confirmed = [
            (person_id, total_seconds, display_name)
            for person_id, total_seconds, display_name in clusters
            if person_id is not None and display_name is not None
        ]
        if not confirmed:
            summaries[meeting_id] = ([], 0)
            continue

        seconds_by_person: dict[str, float] = {}
        names_by_person: dict[str, str] = {}
        for person_id, total_seconds, display_name in confirmed:
            seconds_by_person[person_id] = (
                seconds_by_person.get(person_id, 0.0) + total_seconds
            )
            names_by_person[person_id] = display_name
        speakers = [
            names_by_person[person_id]
            for person_id in sorted(
                seconds_by_person,
                key=lambda value: seconds_by_person[value],
                reverse=True,
            )
        ]
        unknown_count = sum(1 for person_id, _, _ in clusters if person_id is None)
        summaries[meeting_id] = (speakers, unknown_count)
    return summaries


def to_meeting_response(
    meeting: Meeting, speaker_summary: SpeakerSummary = EMPTY_SPEAKER_SUMMARY
) -> MeetingResponse:
    speakers, unknown_speaker_count = speaker_summary
    meeting_date, meeting_date_source = resolve_meeting_date(meeting)
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        state=meeting.state,
        expected_speakers=meeting.expected_speakers,
        language=meeting.language,
        project_id=meeting.project_id,
        project_name=meeting.project.name if meeting.project is not None else None,
        hotwords=json.loads(meeting.hotwords_json),
        created_at=meeting.created_at,
        meeting_date=meeting_date,
        meeting_date_source=meeting_date_source,
        speakers=speakers,
        unknown_speaker_count=unknown_speaker_count,
        plaud_file_id=meeting.plaud_file_id,
        processing_error=meeting.processing_error,
    )
