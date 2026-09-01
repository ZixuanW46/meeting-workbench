from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from meeting_api.models import Voiceprint


def voiceprint_clip_path(data_dir: Path, voiceprint_id: str) -> Path:
    return data_dir / "voiceprints" / f"{voiceprint_id}.wav"


def delete_voiceprint_with_clip(
    session: Session, voiceprint: Voiceprint, data_dir: Path
) -> None:
    voiceprint_id = voiceprint.id
    session.delete(voiceprint)
    session.flush()
    voiceprint_clip_path(data_dir, voiceprint_id).unlink(missing_ok=True)
