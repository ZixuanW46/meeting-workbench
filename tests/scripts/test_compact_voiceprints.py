from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from meeting_api.db import init_db, make_engine, make_session_factory
from meeting_api.models import Meeting, Person, Voiceprint
from meeting_api.pipeline.embedding import embedding_to_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compact_voiceprints.py"


def test_compact_voiceprints_converges_and_is_idempotent(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    engine = make_engine(f"sqlite:///{data_dir / 'meeting-workbench.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)

    clip_dir = data_dir / "voiceprints"
    clip_dir.mkdir()
    with session_factory() as session:
        person = Person(display_name="王芳")
        meetings = [Meeting(title=f"来源会议 {index}") for index in range(7)]
        session.add(person)
        session.add_all(meetings)
        session.flush()
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        vectors = [
            (1.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
            (0.0, 1.0),
            (-1.0, 0.0),
            (0.0, -1.0),
            (0.6, 0.8),
        ]
        rows = [
            Voiceprint(
                person_id=person.id,
                embedding=embedding_to_bytes(vector),
                source_meeting_id=meetings[index].id,
                created_at=created_at + timedelta(seconds=index),
            )
            for index, vector in enumerate(vectors)
        ]
        session.add_all(rows)
        session.commit()
        person_id = person.id
        original_ids = [row.id for row in rows]
    for voiceprint_id in original_ids:
        (clip_dir / f"{voiceprint_id}.wav").write_bytes(b"clip")

    env = os.environ.copy()
    env["MW_DATA_DIR"] = str(data_dir)
    first = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0, first.stderr
    assert "删除模板" in first.stdout
    with session_factory() as session:
        remaining = session.scalars(
            select(Voiceprint)
            .where(Voiceprint.person_id == person_id)
            .order_by(Voiceprint.created_at)
        ).all()
    assert len(remaining) == 5
    remaining_ids = {row.id for row in remaining}
    deleted_ids = set(original_ids) - remaining_ids
    assert len(deleted_ids) == 2
    assert all(not (clip_dir / f"{voiceprint_id}.wav").exists() for voiceprint_id in deleted_ids)
    assert all((clip_dir / f"{voiceprint_id}.wav").is_file() for voiceprint_id in remaining_ids)

    second = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert second.returncode == 0, second.stderr
    assert "删除模板" not in second.stdout
