"""SQLite 连接必须开外键强制与 WAL：否则悬空 person_id 只能靠各处手工校验兜底。"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from meeting_api.models import Meeting, TranscriptSegment


def test_foreign_keys_are_enforced(client):
    with client.app.state.session_factory() as session:
        session.add(
            TranscriptSegment(
                meeting_id="no-such-meeting",
                start_seconds=0.0,
                end_seconds=1.0,
                text="悬空片段",
                cluster_id="S1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_journal_mode_is_wal_and_cascade_delete_works(client):
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1

    with client.app.state.session_factory() as session:
        meeting = Meeting(title="级联删除")
        session.add(meeting)
        session.flush()
        session.add(
            TranscriptSegment(
                meeting_id=meeting.id,
                start_seconds=0.0,
                end_seconds=1.0,
                text="片段",
                cluster_id="S1",
            )
        )
        session.commit()
        meeting_id = meeting.id

    with client.app.state.session_factory() as session:
        session.execute(text("DELETE FROM meetings WHERE id = :id"), {"id": meeting_id})
        session.commit()
        remaining = session.execute(
            text("SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = :id"),
            {"id": meeting_id},
        ).scalar()
        assert remaining == 0
