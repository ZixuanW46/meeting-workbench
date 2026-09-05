"""迁移往返验证：在临时库上跑 upgrade → downgrade → upgrade，确认可逆。

用子进程跑 alembic 并把 MW_DATA_DIR 指到 tmp_path，绝不碰 data/ 下的真库。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(data_dir: Path, command: str, target: str) -> None:
    env = os.environ.copy()
    env["MW_DATA_DIR"] = str(data_dir)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _db_path(data_dir: Path) -> Path:
    return data_dir / "meeting-workbench.sqlite3"


def _columns(data_dir: Path, table: str) -> set[str]:
    with sqlite3.connect(_db_path(data_dir)) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_project_position_migration_backfills_and_round_trips(tmp_path):
    data_dir = tmp_path / "data"

    _run(data_dir, "upgrade", "0017")
    assert "position" not in _columns(data_dir, "projects")

    # 存量项目：故意让插入顺序和 (name, id) 排序不一致。
    with sqlite3.connect(_db_path(data_dir)) as connection:
        connection.executemany(
            "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
            [
                ("id3", "Gamma", "2026-01-01 00:00:00"),
                ("id1", "Alpha", "2026-01-01 00:00:00"),
                ("id2", "Beta", "2026-01-01 00:00:00"),
            ],
        )

    _run(data_dir, "upgrade", "head")
    assert "position" in _columns(data_dir, "projects")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        rows = connection.execute(
            "SELECT id, position FROM projects ORDER BY position"
        ).fetchall()
    assert rows == [("id1", 0), ("id2", 1), ("id3", 2)]

    _run(data_dir, "downgrade", "0017")
    assert "position" not in _columns(data_dir, "projects")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        remaining = connection.execute(
            "SELECT id FROM projects ORDER BY id"
        ).fetchall()
    assert remaining == [("id1",), ("id2",), ("id3",)]

    _run(data_dir, "upgrade", "head")
    assert "position" in _columns(data_dir, "projects")


def _indexes(data_dir: Path, table: str) -> set[str]:
    with sqlite3.connect(_db_path(data_dir)) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA index_list({table})")}


def test_meeting_plaud_file_id_migration_round_trips(tmp_path):
    data_dir = tmp_path / "data"

    _run(data_dir, "upgrade", "0018")
    assert "plaud_file_id" not in _columns(data_dir, "meetings")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        connection.execute(
            "INSERT INTO meetings (id, title, state, created_at) VALUES (?, ?, ?, ?)",
            ("m1", "存量会议", "READY", "2026-01-01 00:00:00"),
        )

    _run(data_dir, "upgrade", "head")
    assert "plaud_file_id" in _columns(data_dir, "meetings")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        # 存量会议保留，新列为空。
        assert connection.execute(
            "SELECT plaud_file_id FROM meetings WHERE id = 'm1'"
        ).fetchone() == (None,)
        # 唯一：同一条 Plaud 录音只能导入一次；未导入的会议可以有任意多个 NULL。
        connection.executemany(
            "INSERT INTO meetings (id, title, state, created_at, plaud_file_id)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                ("m2", "本地会议", "READY", "2026-01-01 00:00:00", None),
                ("m3", "Plaud 会议", "QUEUED", "2026-01-01 00:00:00", "rec-1"),
            ],
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO meetings (id, title, state, created_at, plaud_file_id)"
                " VALUES (?, ?, ?, ?, ?)",
                ("m4", "重复导入", "QUEUED", "2026-01-01 00:00:00", "rec-1"),
            )

    _run(data_dir, "downgrade", "0018")
    assert "plaud_file_id" not in _columns(data_dir, "meetings")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        remaining = connection.execute("SELECT id FROM meetings ORDER BY id").fetchall()
    assert remaining == [("m1",), ("m2",), ("m3",)]

    _run(data_dir, "upgrade", "head")
    assert "plaud_file_id" in _columns(data_dir, "meetings")
    assert "ix_meetings_plaud_file_id" in _indexes(data_dir, "meetings")
