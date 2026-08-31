from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, select

from meeting_api.models import HotwordEntry, Meeting, SpeakerCluster, TranscriptSegment
from meeting_api.schemas import (
    MeetingCreate,
    MeetingListResponse,
    MeetingResponse,
    MeetingTitleUpdate,
)
from meeting_api.storage import meeting_dir
from meeting_domain import RETRANSCRIBABLE_STATES, MeetingState, snapshot, transition

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
        rows = session.scalars(
            select(Meeting).order_by(Meeting.created_at.desc(), Meeting.id.desc())
        ).all()
        return MeetingListResponse(items=[_to_response(meeting) for meeting in rows])


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: str, request: Request) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        return _to_response(meeting)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting_title(
    meeting_id: str, payload: MeetingTitleUpdate, request: Request
) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

        meeting.title = payload.title
        session.commit()
        session.refresh(meeting)
        return _to_response(meeting)


@router.post("/{meeting_id}/retranscribe", response_model=MeetingResponse)
def retranscribe_meeting(meeting_id: str, request: Request) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

        # 不能只靠 transition() 判断：UPLOADING → QUEUED 也是合法边（上传完成），
        # 但重转写只允许从「转写已完成」的状态发起。
        current = MeetingState(meeting.state) if meeting.state in MeetingState else None
        if current not in RETRANSCRIBABLE_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="会议当前状态不允许重转写",
            )
        queued = transition(current, MeetingState.QUEUED)

        global_words = session.scalars(
            select(HotwordEntry.word).order_by(HotwordEntry.word, HotwordEntry.id)
        ).all()
        frozen = snapshot(global_words, json.loads(meeting.hotwords_json))
        meeting.hotword_snapshot_json = json.dumps(frozen, ensure_ascii=False)

        session.execute(
            delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        )
        session.execute(
            delete(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        )
        meeting.has_unconfirmed_speakers = False
        meeting.processing_step = None
        meeting.processing_error = None
        meeting.state = queued.value

        target_dir = meeting_dir(request.app.state.settings, meeting_id)
        for filename in ("transcript.txt", "minutes.md"):
            (target_dir / filename).unlink(missing_ok=True)

        session.commit()
        session.refresh(meeting)
        request.app.state.events.publish(meeting.id, meeting.state, meeting.processing_step)
        return _to_response(meeting)
