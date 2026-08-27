from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from meeting_api.doctor import cli_available
from meeting_api.routes.minutes import MINUTES_CLOUD_NOTE

router = APIRouter(prefix="/api/settings")


class MinutesCliSettingsResponse(BaseModel):
    claude_available: bool
    codex_available: bool
    note: str


@router.get("/minutes-cli", response_model=MinutesCliSettingsResponse)
def get_minutes_cli_settings() -> MinutesCliSettingsResponse:
    return MinutesCliSettingsResponse(
        claude_available=cli_available("claude"),
        codex_available=cli_available("codex"),
        note=MINUTES_CLOUD_NOTE,
    )
