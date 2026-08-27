"""multipart 兼容上传与 tus 断点续传路由。"""

from __future__ import annotations

import base64
import binascii
import re
import shutil
import uuid
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from meeting_api.models import Meeting
from meeting_api.schemas import UploadResponse
from meeting_api.storage import (
    AudioTranscodeError,
    EmptyUploadError,
    clear_pending_uploads,
    create_pending_upload,
    get_pending_upload,
    remove_pending_upload,
    save_stream,
    transcode_audio_if_needed,
)
from meeting_domain import InvalidTransition, MeetingState, transition

router = APIRouter(prefix="/api/meetings")

TUS_VERSION = "1.0.0"
TUS_HEADERS = {"Tus-Resumable": TUS_VERSION, "Tus-Version": TUS_VERSION}
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _ensure_disk_space(
    request: Request,
    upload_size: int,
    *,
    headers: Mapping[str, str] | None = None,
) -> None:
    settings = request.app.state.settings
    free_bytes = shutil.disk_usage(settings.data_dir).free
    required_bytes = upload_size + settings.upload_disk_reserve_bytes
    if free_bytes < required_bytes:
        free_gib = free_bytes / 1024**3
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"磁盘空间不足，还剩 {free_gib:.2f} GB",
            headers=headers,
        )


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


def _parse_metadata_filename(request: Request) -> str | None:
    """从 tus Upload-Metadata 里解出 filename；解不出就返回 None（落盘时兜底为 audio）。

    tus 元数据格式：逗号分隔的「键 空格 base64 值」对，值可省略。
    """
    raw = request.headers.get("Upload-Metadata")
    if not raw:
        return None
    for pair in raw.split(","):
        parts = pair.strip().split(" ")
        if parts[0] != "filename" or len(parts) != 2:
            continue
        try:
            return base64.b64decode(parts[1], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
    return None


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

        _ensure_disk_space(request, file.size or 0)

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
            saved = transcode_audio_if_needed(
                request.app.state.settings,
                meeting.id,
                saved,
            )
        except EmptyUploadError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except AudioTranscodeError as exc:
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
        _ensure_disk_space(request, length, headers=TUS_HEADERS)
        current = MeetingState(meeting.state)
        if current is MeetingState.UPLOADING:
            # 上一次上传被放弃：作废旧分片、原地重新发起，不做状态迁移
            # （状态本来就是 UPLOADING），避免会议永远卡死。
            clear_pending_uploads(request.app.state.settings, meeting.id)
        else:
            try:
                meeting.state = transition(current, MeetingState.UPLOADING).value
            except InvalidTransition as exc:
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
            filename=_parse_metadata_filename(request),
        )
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
                    pending.filename,
                    stream,
                )
                try:
                    saved = transcode_audio_if_needed(
                        request.app.state.settings,
                        meeting.id,
                        saved,
                    )
                except AudioTranscodeError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=str(exc),
                        headers=TUS_HEADERS,
                    ) from exc
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
