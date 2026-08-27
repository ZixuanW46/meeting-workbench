from __future__ import annotations

from io import BytesIO

from docx import Document
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.models import (
    ASSIGNED_VIA_VOICEPRINT_NEAREST,
    Meeting,
    Person,
    SpeakerCluster,
    TranscriptSegment,
)
from meeting_api.storage import meeting_dir
from meeting_domain import MeetingState

router = APIRouter(prefix="/api/meetings")

MARKDOWN_MEDIA_TYPE = "text/markdown"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TRANSCRIPT_EXPORT_STATES = {
    MeetingState.AWAITING_SPEAKER_REVIEW.value,
    MeetingState.APPLYING_DECISIONS.value,
    MeetingState.GENERATING_MINUTES.value,
    MeetingState.READY.value,
    MeetingState.PARTIAL_READY.value,
}
MINUTES_EXPORT_STATES = {
    MeetingState.READY.value,
    MeetingState.PARTIAL_READY.value,
}


def _get_meeting(session: Session, meeting_id: str) -> Meeting:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
    return meeting


def _attachment_headers(meeting_id: str, suffix: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="meeting-{meeting_id}-{suffix}"'}


def _build_export_transcript(session: Session, meeting_id: str) -> str:
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.start_seconds, TranscriptSegment.id)
    ).all()
    clusters = session.scalars(
        select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
    ).all()
    person_ids = {cluster.person_id for cluster in clusters if cluster.person_id}
    people = (
        {
            person.id: person.display_name
            for person in session.scalars(select(Person).where(Person.id.in_(person_ids)))
        }
        if person_ids
        else {}
    )
    labels: dict[str, str] = {}
    for cluster in clusters:
        label = people.get(cluster.person_id) or f"说话人{cluster.cluster_id}（未确认）"
        if (
            cluster.assigned_via == ASSIGNED_VIA_VOICEPRINT_NEAREST
            and cluster.person_id is not None
        ):
            # 就近归属的署名如实标注，与纪要口径一致。
            label = f"{label}（就近归属）"
        labels[cluster.cluster_id] = label
    lines = ["# 会议转写", ""]
    lines.extend(
        f"[{segment.start_seconds:.2f}-{segment.end_seconds:.2f}] "
        f"{labels.get(segment.cluster_id, f'说话人{segment.cluster_id}（未确认）')}："
        f"{segment.text}"
        for segment in segments
    )
    return "\n".join(lines)


def _read_minutes(request: Request, meeting_id: str) -> str:
    minutes_path = meeting_dir(request.app.state.settings, meeting_id) / "minutes.md"
    if not minutes_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="纪要尚未生成",
        )
    return minutes_path.read_text(encoding="utf-8")


def _require_export_state(meeting: Meeting, allowed_states: set[str]) -> None:
    if meeting.state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="会议当前状态不可导出该文件",
        )


@router.get("/{meeting_id}/export/transcript.md")
def export_transcript(meeting_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        meeting = _get_meeting(session, meeting_id)
        _require_export_state(meeting, TRANSCRIPT_EXPORT_STATES)
        markdown = _build_export_transcript(session, meeting_id)
    return Response(
        content=markdown,
        media_type=MARKDOWN_MEDIA_TYPE,
        headers=_attachment_headers(meeting_id, "transcript.md"),
    )


@router.get("/{meeting_id}/export/minutes.md")
def export_minutes_markdown(meeting_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        meeting = _get_meeting(session, meeting_id)
        _require_export_state(meeting, MINUTES_EXPORT_STATES)
    markdown = _read_minutes(request, meeting_id)
    return Response(
        content=markdown,
        media_type=MARKDOWN_MEDIA_TYPE,
        headers=_attachment_headers(meeting_id, "minutes.md"),
    )


@router.get("/{meeting_id}/export/minutes.docx")
def export_minutes_docx(meeting_id: str, request: Request) -> Response:
    with request.app.state.session_factory() as session:
        meeting = _get_meeting(session, meeting_id)
        _require_export_state(meeting, MINUTES_EXPORT_STATES)
    markdown = _read_minutes(request, meeting_id)

    document = Document()
    for line in markdown.split("\n"):
        document.add_paragraph(line)
    output = BytesIO()
    document.save(output)
    return Response(
        content=output.getvalue(),
        media_type=DOCX_MEDIA_TYPE,
        headers=_attachment_headers(meeting_id, "minutes.docx"),
    )
