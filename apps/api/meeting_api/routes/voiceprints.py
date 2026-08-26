from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from meeting_api.models import Person, Voiceprint

router = APIRouter(prefix="/api/voiceprints")


class VoiceprintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    person_id: str
    display_name: str


@router.get("", response_model=list[VoiceprintResponse])
def list_voiceprints(request: Request) -> list[VoiceprintResponse]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        rows = session.execute(
            select(Voiceprint, Person.display_name)
            .join(Person, Person.id == Voiceprint.person_id)
            .order_by(Person.display_name, Voiceprint.id)
        ).all()
        return [
            VoiceprintResponse(
                id=voiceprint.id,
                person_id=voiceprint.person_id,
                display_name=display_name,
            )
            for voiceprint, display_name in rows
        ]


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
    return Response(status_code=status.HTTP_204_NO_CONTENT)
