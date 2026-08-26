from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from meeting_api.models import Meeting
from meeting_api.schemas import MeetingCreate, MeetingListResponse, MeetingResponse

router = APIRouter(prefix="/api/meetings")


def _to_response(meeting: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        state=meeting.state,
        expected_speakers=meeting.expected_speakers,
        hotwords=json.loads(meeting.hotwords_json),
        created_at=meeting.created_at,
    )


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def create_meeting(payload: MeetingCreate, request: Request) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(
            title=payload.title,
            expected_speakers=payload.expected_speakers,
            hotwords_json=json.dumps(payload.hotwords, ensure_ascii=False),
        )
        session.add(meeting)
        session.commit()
        session.refresh(meeting)
        return _to_response(meeting)


@router.get("", response_model=MeetingListResponse)
def list_meetings(request: Request) -> MeetingListResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        rows = session.scalars(select(Meeting).order_by(Meeting.created_at.desc())).all()
        return MeetingListResponse(items=[_to_response(meeting) for meeting in rows])


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: str, request: Request) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        return _to_response(meeting)
