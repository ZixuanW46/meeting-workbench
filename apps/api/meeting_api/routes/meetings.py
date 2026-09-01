from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from meeting_api.models import (
    HotwordEntry,
    Meeting,
    Person,
    SpeakerCluster,
    TranscriptSegment,
    Voiceprint,
)
from meeting_api.schemas import (
    MeetingCreate,
    MeetingListResponse,
    MeetingResponse,
    MeetingTitleUpdate,
)
from meeting_api.storage import meeting_dir
from meeting_domain import RETRANSCRIBABLE_STATES, MeetingState, snapshot, transition

router = APIRouter(prefix="/api/meetings")


type SpeakerSummary = tuple[list[str], int]

BUSY_MEETING_STATES: frozenset[MeetingState] = frozenset(
    {
        MeetingState.QUEUED,
        MeetingState.PROCESSING,
        MeetingState.APPLYING_DECISIONS,
        MeetingState.GENERATING_MINUTES,
    }
)


def _speaker_summaries(
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


def _to_response(
    meeting: Meeting, speaker_summary: SpeakerSummary = ([], 0)
) -> MeetingResponse:
    speakers, unknown_speaker_count = speaker_summary
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        state=meeting.state,
        expected_speakers=meeting.expected_speakers,
        hotwords=json.loads(meeting.hotwords_json),
        created_at=meeting.created_at,
        speakers=speakers,
        unknown_speaker_count=unknown_speaker_count,
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
        summaries = _speaker_summaries(session, [meeting.id for meeting in rows])
        return MeetingListResponse(
            items=[_to_response(meeting, summaries.get(meeting.id, ([], 0))) for meeting in rows]
        )


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: str, request: Request) -> MeetingResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        return _to_response(
            meeting, _speaker_summaries(session, [meeting.id]).get(meeting.id, ([], 0))
        )


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
        meeting.title_user_edited = True
        session.commit()
        session.refresh(meeting)
        summary = _speaker_summaries(session, [meeting.id]).get(meeting.id, ([], 0))
        return _to_response(meeting, summary)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str, request: Request) -> Response:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

        current = MeetingState(meeting.state) if meeting.state in MeetingState else None
        if current in BUSY_MEETING_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="处理中的会议不能删除",
            )

        session.execute(
            update(Voiceprint)
            .where(Voiceprint.source_meeting_id == meeting_id)
            .values(source_meeting_id=None)
        )
        session.execute(
            delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
        )
        session.execute(
            delete(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        )
        session.delete(meeting)
        session.commit()

    shutil.rmtree(meeting_dir(request.app.state.settings, meeting_id), ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
