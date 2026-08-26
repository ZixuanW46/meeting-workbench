"""multipart 兼容上传与 tus 断点续传路由。"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from meeting_api.models import Meeting
from meeting_api.schemas import UploadResponse
from meeting_api.storage import (
    EmptyUploadError,
    create_pending_upload,
    get_pending_upload,
    remove_pending_upload,
    save_stream,
)
from meeting_domain import InvalidTransition, MeetingState, transition

router = APIRouter(prefix="/api/meetings")

TUS_VERSION = "1.0.0"
TUS_HEADERS = {"Tus-Resumable": TUS_VERSION, "Tus-Version": TUS_VERSION}
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _require_tus_version(request: Request) -> None:
    if request.headers.get("Tus-Resumable") != TUS_VERSION:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="不支持的 tus 版本",
            headers=TUS_HEADERS,
        )


def _parse_positive_header(request: Request, name: str) -> int:
    raw_value = request.headers.get(name)
    try:
        value = int(raw_value) if raw_value is not None else 0
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} 必须是整数",
            headers=TUS_HEADERS,
        ) from exc
    if value <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} 必须大于 0",
            headers=TUS_HEADERS,
        )
    return value


def _parse_offset(request: Request) -> int:
    raw_value = request.headers.get("Upload-Offset")
    try:
        value = int(raw_value) if raw_value is not None else -1
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Offset 必须是整数",
            headers=TUS_HEADERS,
        ) from exc
    if value < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Offset 不能小于 0",
            headers=TUS_HEADERS,
        )
    return value


def _pending_or_404(request: Request, meeting_id: str, upload_id: str):
    if not UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传不存在",
            headers=TUS_HEADERS,
        )
    pending = get_pending_upload(request.app.state.settings, meeting_id, upload_id)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传不存在",
            headers=TUS_HEADERS,
        )
    return pending


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
        meeting.state = uploading.value
        meeting.state = transition(uploading, MeetingState.QUEUED).value
        session.commit()

        return UploadResponse(size=saved.size, sha256=saved.sha256)


@router.post("/{meeting_id}/files/", status_code=status.HTTP_201_CREATED)
def create_tus_upload(meeting_id: str, request: Request) -> Response:
    _require_tus_version(request)
    length = _parse_positive_header(request, "Upload-Length")
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会议不存在",
                headers=TUS_HEADERS,
            )
        try:
            uploading = transition(MeetingState(meeting.state), MeetingState.UPLOADING)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前会议状态不允许上传音频",
                headers=TUS_HEADERS,
            ) from exc

        upload_id = uuid.uuid4().hex
        create_pending_upload(
            request.app.state.settings,
            meeting.id,
            upload_id,
            length,
        )
        meeting.state = uploading.value
        session.commit()

    location = request.url_for(
        "head_tus_upload",
        meeting_id=meeting_id,
        upload_id=upload_id,
    )
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers={**TUS_HEADERS, "Location": str(location)},
    )


@router.head("/{meeting_id}/files/{upload_id}", name="head_tus_upload")
def head_tus_upload(meeting_id: str, upload_id: str, request: Request) -> Response:
    _require_tus_version(request)
    pending = _pending_or_404(request, meeting_id, upload_id)
    return Response(
        headers={
            **TUS_HEADERS,
            "Upload-Offset": str(pending.offset),
            "Upload-Length": str(pending.length),
            "Cache-Control": "no-store",
        }
    )


@router.patch("/{meeting_id}/files/{upload_id}")
async def patch_tus_upload(
    meeting_id: str,
    upload_id: str,
    request: Request,
) -> Response:
    _require_tus_version(request)
    if request.headers.get("Content-Type") != "application/offset+octet-stream":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="PATCH 必须使用 application/offset+octet-stream",
            headers=TUS_HEADERS,
        )
    requested_offset = _parse_offset(request)
    pending = _pending_or_404(request, meeting_id, upload_id)
    if requested_offset != pending.offset:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload-Offset 与服务端进度不一致",
            headers={**TUS_HEADERS, "Upload-Offset": str(pending.offset)},
        )

    with request.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会议不存在",
                headers=TUS_HEADERS,
            )
        if meeting.state != MeetingState.UPLOADING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前会议状态不允许继续上传音频",
                headers=TUS_HEADERS,
            )

        offset = pending.offset
        with pending.path.open("ab") as output:
            async for chunk in request.stream():
                if offset + len(chunk) > pending.length:
                    output.truncate(pending.offset)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="上传内容超过 Upload-Length",
                        headers={**TUS_HEADERS, "Upload-Offset": str(pending.offset)},
                    )
                output.write(chunk)
                offset += len(chunk)

        if offset == pending.length:
            with pending.path.open("rb") as stream:
                saved = save_stream(
                    request.app.state.settings,
                    meeting.id,
                    "audio",
                    stream,
                )
            meeting.audio_filename = saved.filename
            meeting.audio_sha256 = saved.sha256
            meeting.audio_size = saved.size
            meeting.state = transition(
                MeetingState(meeting.state), MeetingState.QUEUED
            ).value
            session.commit()
            remove_pending_upload(
                request.app.state.settings,
                meeting.id,
                upload_id,
            )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={**TUS_HEADERS, "Upload-Offset": str(offset)},
    )
