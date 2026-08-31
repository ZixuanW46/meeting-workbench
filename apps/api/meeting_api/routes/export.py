from __future__ import annotations

import re
from io import BytesIO

from docx import Document
from docx.document import Document as DocumentObject
from docx.shared import Pt
from docx.text.paragraph import Paragraph
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.models import (
    Meeting,
    TranscriptSegment,
)
from meeting_api.speaker_labels import public_speaker_labels
from meeting_api.storage import meeting_dir
from meeting_api.transcript_format import format_transcript_blocks
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
INLINE_BOLD_PATTERN = re.compile(r"(\*\*[^*]+\*\*)")
LIST_ITEM_PATTERN = re.compile(r"^(?P<nested>  )?- (?P<content>.*)$")
TASK_PATTERN = re.compile(r"^\[(?P<checked>[ xX])\] (?P<content>.*)$")


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
    labels = public_speaker_labels(session, meeting_id)
    transcript = format_transcript_blocks(
        [
            (
                segment.start_seconds,
                segment.end_seconds,
                labels.get(segment.cluster_id, "说话人"),
                segment.text,
            )
            for segment in segments
        ]
    )
    return "\n".join(["# 会议转写", "", transcript])


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


def _add_markdown_runs(paragraph: Paragraph, text: str) -> None:
    for part in INLINE_BOLD_PATTERN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        else:
            paragraph.add_run(part)


def _render_minutes_docx(document: DocumentObject, markdown: str) -> None:
    previous: Paragraph | None = None
    for line in markdown.splitlines():
        if not line.strip():
            if previous is not None:
                previous.paragraph_format.space_after = Pt(8)
            continue

        if line.startswith("## "):
            paragraph = document.add_paragraph(style="Heading 2")
            content = line[3:]
        elif line.startswith("# "):
            paragraph = document.add_paragraph(style="Heading 1")
            content = line[2:]
        elif match := LIST_ITEM_PATTERN.match(line):
            paragraph = document.add_paragraph(
                style="List Bullet 2" if match.group("nested") else "List Bullet"
            )
            content = match.group("content")
            if task := TASK_PATTERN.match(content):
                checkbox = "☑" if task.group("checked").lower() == "x" else "☐"
                paragraph.add_run(f"{checkbox} ")
                content = task.group("content")
        else:
            paragraph = document.add_paragraph()
            content = line

        _add_markdown_runs(paragraph, content)
        previous = paragraph


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
    _render_minutes_docx(document, markdown)
    output = BytesIO()
    document.save(output)
    return Response(
        content=output.getvalue(),
        media_type=DOCX_MEDIA_TYPE,
        headers=_attachment_headers(meeting_id, "minutes.docx"),
    )
