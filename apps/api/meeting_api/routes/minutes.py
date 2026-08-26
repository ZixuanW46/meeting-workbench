from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from meeting_api.models import Meeting
from meeting_api.storage import meeting_dir
from meeting_domain import MeetingState, transition

router = APIRouter(prefix="/api/meetings")

MINUTES_CLOUD_NOTE = "纪要文本会发送到 Claude/OpenAI 云端，音频不会上传"


class MinutesResponse(BaseModel):
    markdown: str
    note: str


class MinutesRetryResponse(BaseModel):
    state: str


@router.get("/{meeting_id}/minutes", response_model=MinutesResponse)
def get_minutes(meeting_id: str, request: Request) -> MinutesResponse:
    with request.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

    minutes_path = meeting_dir(request.app.state.settings, meeting_id) / "minutes.md"
    if not minutes_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="纪要尚未生成",
        )
    return MinutesResponse(
        markdown=minutes_path.read_text(encoding="utf-8"),
        note=MINUTES_CLOUD_NOTE,
    )


@router.post("/{meeting_id}/minutes/retry", response_model=MinutesRetryResponse)
def retry_minutes(meeting_id: str, request: Request) -> MinutesRetryResponse:
    with request.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        if meeting.state != MeetingState.PARTIAL_READY.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="只有纪要生成失败的会议可以重试",
            )
        meeting.state = transition(
            MeetingState(meeting.state), MeetingState.GENERATING_MINUTES
        ).value
        meeting.processing_error = None
        session.commit()
        request.app.state.events.publish(
            meeting.id,
            meeting.state,
            meeting.processing_step,
        )
        return MinutesRetryResponse(state=meeting.state)
