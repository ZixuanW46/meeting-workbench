from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from meeting_api.doctor import probe_cli
from meeting_api.routes.minutes import MINUTES_CLOUD_NOTE

router = APIRouter(prefix="/api/settings")


class MinutesCliSettingsResponse(BaseModel):
    claude_available: bool
    codex_available: bool
    note: str


@router.get("/minutes-cli", response_model=MinutesCliSettingsResponse)
def get_minutes_cli_settings() -> MinutesCliSettingsResponse:
    claude_available, _ = probe_cli("claude", ["/doctor"])
    codex_available, _ = probe_cli("codex", ["whoami"])
    return MinutesCliSettingsResponse(
        claude_available=claude_available,
        codex_available=codex_available,
        note=MINUTES_CLOUD_NOTE,
    )
