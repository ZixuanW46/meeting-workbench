from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from meeting_api.models import Meeting

router = APIRouter(prefix="/api/meetings")


@router.get("")
def list_meetings(request: Request) -> dict[str, Any]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        rows = session.scalars(
            select(Meeting).order_by(Meeting.created_at.desc())
        ).all()
    return {
        "items": [
            {
                "id": m.id,
                "title": m.title,
                "state": m.state,
                "expected_speakers": m.expected_speakers,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
    }
