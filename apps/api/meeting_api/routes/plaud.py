"""Plaud 云端录音：状态 / 登录 / 列表 / 导入。

导入复用现有「上传 → 转码 → QUEUED」管道，只是音频来自 Plaud 预签名直链而不是浏览器。
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from datetime import date
from typing import Annotated, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.config import Settings
from meeting_api.meeting_service import (
    build_meeting,
    require_project,
    to_meeting_response,
)
from meeting_api.models import Meeting
from meeting_api.plaud.download import download_to_meeting, filename_from_url
from meeting_api.plaud.errors import (
    PLAUD_NOT_INSTALLED_MESSAGE,
    PLAUD_NOT_LOGGED_IN_MESSAGE,
    PLAUD_TIMEOUT_MESSAGE,
    PlaudAuthError,
    PlaudError,
    PlaudTimeoutError,
    PlaudUnavailableError,
)
from meeting_api.plaud.gateway import PlaudGateway, PlaudRecording
from meeting_api.plaud.progress import ImportProgressRegistry
from meeting_api.schemas import (
    MeetingResponse,
    PlaudImportProgressResponse,
    PlaudImportRequest,
    PlaudLoginResponse,
    PlaudRecordingListResponse,
    PlaudRecordingResponse,
    PlaudStatusResponse,
    PlaudUserResponse,
)
from meeting_api.storage import (
    AudioTranscodeError,
    EmptyUploadError,
    meeting_dir,
    transcode_audio_if_needed,
)
from meeting_api.titles import DEFAULT_MEETING_TITLE, TITLE_MAX_LENGTH
from meeting_domain import MeetingState, transition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaud")

# 录音笔没改过名时用的设备默认名，如 "2026-09-05 21:08:13"：不算用户命名。
_DEVICE_DEFAULT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _gateway(request: Request) -> PlaudGateway:
    return request.app.state.plaud_gateway


def _progress(request: Request) -> ImportProgressRegistry:
    return request.app.state.plaud_import_progress


def _http_error(exc: Exception) -> HTTPException | None:
    """把 Plaud / 落盘异常翻成 HTTP 错误；认不出的返回 None，交给调用方原样抛。"""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PlaudUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PLAUD_NOT_INSTALLED_MESSAGE,
        )
    if isinstance(exc, PlaudAuthError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PLAUD_NOT_LOGGED_IN_MESSAGE,
        )
    if isinstance(exc, PlaudTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=PLAUD_TIMEOUT_MESSAGE
        )
    if isinstance(exc, PlaudError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Plaud 服务异常：{exc}"
        )
    if isinstance(exc, EmptyUploadError | AudioTranscodeError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    return None


def _raise_http_error(exc: Exception) -> NoReturn:
    mapped = _http_error(exc)
    if mapped is None:
        raise exc
    raise mapped from exc


def _get_recording(gateway: PlaudGateway, file_id: str) -> PlaudRecording:
    try:
        return gateway.get_recording(file_id)
    except Exception as exc:
        _raise_http_error(exc)


def _fetch_downloadable_recording(
    gateway: PlaudGateway, file_id: str, *, attempts: int, delay_seconds: float
) -> PlaudRecording:
    """取到带直链的录音就返回；云端偶发少 presigned_url，隔一小会儿再问一次。

    最后一次仍没有直链就把它原样交回，由调用方决定报什么错。
    """
    total = max(1, attempts)
    recording = _get_recording(gateway, file_id)
    for attempt in range(1, total):
        if recording.presigned_url:
            break
        logger.warning(
            "Plaud 录音 %s 第 %d/%d 次没拿到直链，%.1fs 后重试",
            file_id,
            attempt,
            total,
            delay_seconds,
        )
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        recording = _get_recording(gateway, file_id)
    return recording


def _require_available(gateway: PlaudGateway) -> None:
    if not gateway.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PLAUD_NOT_INSTALLED_MESSAGE,
        )


@router.get("/status", response_model=PlaudStatusResponse)
def plaud_status(request: Request) -> PlaudStatusResponse:
    """探测用，Plaud 出任何问题都以文案呈现，不抛 4xx/5xx。"""
    gateway = _gateway(request)
    if not gateway.available():
        return PlaudStatusResponse(
            available=False, logged_in=False, user=None, message=PLAUD_NOT_INSTALLED_MESSAGE
        )
    try:
        user = gateway.current_user()
    except PlaudAuthError:
        return PlaudStatusResponse(
            available=True, logged_in=False, user=None, message=PLAUD_NOT_LOGGED_IN_MESSAGE
        )
    except PlaudTimeoutError:
        return PlaudStatusResponse(
            available=True, logged_in=False, user=None, message=PLAUD_TIMEOUT_MESSAGE
        )
    except PlaudError as exc:
        return PlaudStatusResponse(
            available=True, logged_in=False, user=None, message=f"Plaud 服务异常：{exc}"
        )
    return PlaudStatusResponse(
        available=True,
        logged_in=True,
        user=PlaudUserResponse(nickname=user.nickname, email=user.email),
        message=None,
    )


@router.post("/login", response_model=PlaudLoginResponse)
def plaud_login(request: Request) -> PlaudLoginResponse:
    """在服务器所在机器上打开浏览器做 OAuth；最长等 plaud_login_timeout_seconds。"""
    gateway = _gateway(request)
    _require_available(gateway)
    try:
        message = gateway.login()
    except Exception as exc:
        _raise_http_error(exc)
    try:
        gateway.current_user()
    except PlaudError:
        return PlaudLoginResponse(logged_in=False, message=message)
    return PlaudLoginResponse(logged_in=True, message=message)


@router.get("/recordings", response_model=PlaudRecordingListResponse)
def list_plaud_recordings(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 20,
    query: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> PlaudRecordingListResponse:
    gateway = _gateway(request)
    _require_available(gateway)
    keyword = (query or "").strip() or None
    try:
        items, has_more = gateway.list_recordings(
            page=page,
            page_size=page_size,
            query=keyword,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as exc:
        _raise_http_error(exc)

    imported = _imported_meeting_ids(request, [item.file_id for item in items])
    return PlaudRecordingListResponse(
        items=[
            PlaudRecordingResponse(
                file_id=item.file_id,
                name=item.name,
                started_at=item.started_at,
                duration_ms=item.duration_ms,
                imported_meeting_id=imported.get(item.file_id),
            )
            for item in items
        ],
        page=page,
        page_size=page_size,
        has_more=has_more,
        filtered=keyword is not None or date_from is not None or date_to is not None,
    )


def _imported_meeting_ids(request: Request, file_ids: list[str]) -> dict[str, str]:
    if not file_ids:
        return {}
    with request.app.state.session_factory() as session:
        rows = session.execute(
            select(Meeting.plaud_file_id, Meeting.id).where(
                Meeting.plaud_file_id.in_(file_ids)
            )
        ).all()
    return {file_id: meeting_id for file_id, meeting_id in rows}


def resolve_import_title(
    payload: PlaudImportRequest, recording: PlaudRecording
) -> tuple[str, bool]:
    """标题三条规则：用户填写 > Plaud 里改过的名字 > 设备默认名（留给自动命名接管）。"""
    if payload.title:
        return payload.title[:TITLE_MAX_LENGTH], True
    name = (recording.name or "").strip()
    if not name:
        return DEFAULT_MEETING_TITLE, False
    return name[:TITLE_MAX_LENGTH], _DEVICE_DEFAULT_NAME.fullmatch(name) is None


@router.post(
    "/import", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED
)
def import_plaud_recording(payload: PlaudImportRequest, request: Request) -> MeetingResponse:
    progress = _progress(request)
    file_id = payload.plaud_file_id

    with request.app.state.session_factory() as session:
        if payload.project_id is not None:
            require_project(session, payload.project_id)
        if session.scalar(select(Meeting.id).where(Meeting.plaud_file_id == file_id)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="该 Plaud 录音已导入"
            )

        # 从这里开始整段下载都在同一个请求里同步跑，前端靠 import-progress 轮询看进度；
        # 任何一条出错路径都要把进度落到 failed，不能停在 downloading。
        progress.start(file_id)
        try:
            return _download_and_queue(session, request, payload, progress=progress)
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            progress.fail(file_id, str(detail))
            raise


def _download_and_queue(
    session: Session,
    request: Request,
    payload: PlaudImportRequest,
    *,
    progress: ImportProgressRegistry,
) -> MeetingResponse:
    settings = request.app.state.settings
    gateway = _gateway(request)
    file_id = payload.plaud_file_id

    recording = _fetch_downloadable_recording(
        gateway,
        file_id,
        attempts=settings.plaud_presigned_url_retries + 1,
        delay_seconds=settings.plaud_presigned_url_retry_seconds,
    )
    if not recording.presigned_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="这条录音的音频暂不可下载，请稍后再试",
        )

    title, title_user_edited = resolve_import_title(payload, recording)
    meeting = build_meeting(
        session,
        payload,
        title=title,
        title_user_edited=title_user_edited,
        # 录音时间是 UTC，会议日期要按本机时区落到「那天」。
        meeting_date=payload.meeting_date or recording.started_at.astimezone().date(),
        plaud_file_id=file_id,
    )
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    meeting_id = meeting.id

    def report(bytes_done: int, bytes_total: int | None) -> None:
        progress.update(file_id, bytes_done=bytes_done, bytes_total=bytes_total)

    try:
        uploading = transition(MeetingState(meeting.state), MeetingState.UPLOADING)
        meeting.state = uploading.value
        session.commit()

        progress.update(file_id, phase="downloading", bytes_done=0)
        saved = download_to_meeting(
            settings,
            meeting_id,
            recording.presigned_url,
            filename_from_url(recording.presigned_url, file_id),
            on_progress=report,
        )
        progress.update(file_id, phase="finalizing")
        saved = transcode_audio_if_needed(settings, meeting_id, saved)
        meeting.audio_filename = saved.filename
        meeting.audio_sha256 = saved.sha256
        meeting.audio_size = saved.size
        # 文件名是哈希，别拿它当标题（所以不调 apply_filename_title）。
        meeting.state = transition(uploading, MeetingState.QUEUED).value
        session.commit()
    except Exception as exc:
        session.rollback()
        _discard_meeting(session, settings, meeting_id)
        _raise_http_error(exc)

    session.refresh(meeting)
    response = to_meeting_response(meeting)
    progress.finish(file_id, meeting_id)
    return response


@router.get("/import-progress/{file_id}", response_model=PlaudImportProgressResponse)
def plaud_import_progress(file_id: str, request: Request) -> PlaudImportProgressResponse:
    """导入在途/刚结束时的下载进度；终态多留 120 s 再过期。"""
    entry = _progress(request).get(file_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="没有该 Plaud 导入的进度"
        )
    return PlaudImportProgressResponse(
        file_id=entry.file_id,
        phase=entry.phase,
        bytes_done=entry.bytes_done,
        bytes_total=entry.bytes_total,
        meeting_id=entry.meeting_id,
        error=entry.error,
    )


def _discard_meeting(session: Session, settings: Settings, meeting_id: str) -> None:
    """导入没走完就把刚建的会议连同目录一起删掉，不给用户留半截记录。"""
    meeting = session.get(Meeting, meeting_id)
    if meeting is not None:
        session.delete(meeting)
        session.commit()
    shutil.rmtree(meeting_dir(settings, meeting_id), ignore_errors=True)
