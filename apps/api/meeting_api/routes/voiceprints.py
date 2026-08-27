from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from meeting_api.models import Meeting, Person, Voiceprint

router = APIRouter(prefix="/api/voiceprints")


class VoiceprintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    person_id: str
    display_name: str
    # 模板出处与核对材料：会议标题（绝不是路径）、入库时间、该窗转写摘录、
    # 是否有试听切片。声纹库页据此支持逐条人工审核。
    created_at: str | None
    source_meeting_title: str | None
    snippet_text: str
    has_clip: bool


class VoiceprintListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VoiceprintResponse]


def _clip_path(request: Request, voiceprint_id: str):
    return request.app.state.settings.data_dir / "voiceprints" / f"{voiceprint_id}.wav"


@router.get("", response_model=VoiceprintListResponse)
def list_voiceprints(request: Request) -> VoiceprintListResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        rows = session.execute(
            select(Voiceprint, Person.display_name, Meeting.title)
            .join(Person, Person.id == Voiceprint.person_id)
            .join(Meeting, Meeting.id == Voiceprint.source_meeting_id, isouter=True)
            .order_by(Person.display_name, Voiceprint.id)
        ).all()
        return VoiceprintListResponse(
            items=[
                VoiceprintResponse(
                    id=voiceprint.id,
                    person_id=voiceprint.person_id,
                    display_name=display_name,
                    created_at=voiceprint.created_at.isoformat()
                    if voiceprint.created_at is not None
                    else None,
                    source_meeting_title=meeting_title,
                    snippet_text=voiceprint.snippet_text,
                    has_clip=_clip_path(request, voiceprint.id).is_file(),
                )
                for voiceprint, display_name, meeting_title in rows
            ]
        )


@router.get("/{voiceprint_id}/audio")
def get_voiceprint_audio(voiceprint_id: str, request: Request) -> FileResponse:
    with request.app.state.session_factory() as session:
        voiceprint = session.get(Voiceprint, voiceprint_id)
        if voiceprint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="声纹不存在")
    clip_path = _clip_path(request, voiceprint_id)
    if not clip_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该模板没有试听切片",
        )
    # 只回字节流；不带 Content-Disposition，避免文件名/路径信息进响应头。
    return FileResponse(clip_path, media_type="audio/wav")


@router.delete("/{voiceprint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voiceprint(voiceprint_id: str, request: Request) -> Response:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        voiceprint = session.get(Voiceprint, voiceprint_id)
        if voiceprint is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="声纹不存在",
            )
        session.delete(voiceprint)
        session.commit()
    # 模板删了切片就没有存在意义：连带清理，缺失容忍。
    _clip_path(request, voiceprint_id).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
