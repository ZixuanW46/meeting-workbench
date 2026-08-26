"""multipart 音频上传路由。

tus 替换点：M11 只换这个 router。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from meeting_api.models import Meeting
from meeting_api.schemas import UploadResponse
from meeting_api.storage import EmptyUploadError, save_stream
from meeting_domain import InvalidTransition, MeetingState, transition

router = APIRouter(prefix="/api/meetings")


@router.post("/{meeting_id}/upload", response_model=UploadResponse)
def upload_audio(
    meeting_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> UploadResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")

        try:
            uploading = transition(MeetingState(meeting.state), MeetingState.UPLOADING)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前会议状态不允许上传音频",
            ) from exc
        meeting.state = uploading.value

        try:
            saved = save_stream(
                request.app.state.settings,
                meeting.id,
                file.filename,
                file.file,
            )
        except EmptyUploadError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        meeting.audio_filename = saved.filename
        meeting.audio_sha256 = saved.sha256
        meeting.audio_size = saved.size
        meeting.state = transition(uploading, MeetingState.QUEUED).value
        session.commit()

        return UploadResponse(size=saved.size, sha256=saved.sha256)
