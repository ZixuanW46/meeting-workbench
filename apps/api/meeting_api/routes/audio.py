"""M8 最小只读音频流：给前端试听用，整文件返回（Range 留到以后）。"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from meeting_api.models import Meeting
from meeting_api.storage import meeting_dir

router = APIRouter(prefix="/api/meetings")


@router.get("/{meeting_id}/audio")
def get_audio(meeting_id: str, request: Request) -> FileResponse:
    with request.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        audio_filename = meeting.audio_filename

    if not audio_filename:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="会议还没有上传音频",
        )
    audio_path = meeting_dir(request.app.state.settings, meeting_id) / "raw" / audio_filename
    if not audio_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="会议音频文件缺失",
        )
    media_type = mimetypes.guess_type(audio_filename)[0] or "application/octet-stream"
    # 只回字节流；不带 Content-Disposition，避免文件名/路径信息进响应头。
    return FileResponse(audio_path, media_type=media_type)
