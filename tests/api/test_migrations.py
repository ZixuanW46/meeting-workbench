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
        # 只看存量项目：0020 之后库里还会多一个默认项目。
        rows = connection.execute(
            "SELECT id, position FROM projects WHERE id IN ('id1', 'id2', 'id3')"
            " ORDER BY position"
        ).fetchall()
    assert rows == [("id1", 0), ("id2", 1), ("id3", 2)]

    _run(data_dir, "downgrade", "0017")
    assert "position" not in _columns(data_dir, "projects")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        remaining = {
            row[0]
            for row in connection.execute("SELECT id FROM projects").fetchall()
        }
    # 降级只改结构不回滚数据，所以只断言存量项目一个没丢。
    assert {"id1", "id2", "id3"} <= remaining

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


def test_default_project_migration_marks_merges_and_backfills(tmp_path):
    data_dir = tmp_path / "data"

    _run(data_dir, "upgrade", "0019")
    assert "is_default" not in _columns(data_dir, "projects")

    with sqlite3.connect(_db_path(data_dir)) as connection:
        # 存量库里已经有一个叫 General 的项目（大小写不敏感），它就是默认项目。
        connection.executemany(
            "INSERT INTO projects (id, name, created_at, position) VALUES (?, ?, ?, ?)",
            [
                ("p-general", "general", "2026-01-01 00:00:00", 0),
                ("p-other", "别的项目", "2026-01-01 00:00:00", 1),
            ],
        )
        connection.executemany(
            "INSERT INTO project_hotwords (id, project_id, word, note)"
            " VALUES (?, ?, ?, ?)",
            [
                ("h1", "p-general", "共同词", "项目的说法"),
                ("h2", "p-general", "保留词", "项目的说法"),
                ("h3", "p-general", "独有词", "项目的注解"),
                ("h4", "p-other", "别的项目的词", None),
            ],
        )
        connection.executemany(
            "INSERT INTO hotword_entries (id, word, note) VALUES (?, ?, ?)",
            [("g1", "共同词", None), ("g2", "保留词", "全局的说法")],
        )
        connection.executemany(
            "INSERT INTO meetings (id, title, state, created_at, project_id)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                ("m1", "没项目的会", "READY", "2026-01-01 00:00:00", None),
                ("m2", "有项目的会", "READY", "2026-01-01 00:00:00", "p-other"),
            ],
        )

    _run(data_dir, "upgrade", "head")
    assert "is_default" in _columns(data_dir, "projects")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        assert connection.execute(
            "SELECT id FROM projects WHERE is_default = 1"
        ).fetchall() == [("p-general",)]
        # 默认项目的词并进全局：全局无注解时取项目注解，有注解则保留全局说法。
        assert connection.execute(
            "SELECT word, note FROM hotword_entries ORDER BY word"
        ).fetchall() == sorted(
            [
                ("共同词", "项目的说法"),
                ("保留词", "全局的说法"),
                ("独有词", "项目的注解"),
            ]
        )
        # 并完就把默认项目下的词条删掉；别的项目原样保留。
        assert connection.execute(
            "SELECT id FROM project_hotwords ORDER BY id"
        ).fetchall() == [("h4",)]
        assert connection.execute(
            "SELECT id, project_id FROM meetings ORDER BY id"
        ).fetchall() == [("m1", "p-general"), ("m2", "p-other")]
        # 部分唯一索引：默认项目只能有一个。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO projects (id, name, created_at, position, is_default)"
                " VALUES (?, ?, ?, ?, ?)",
                ("p-second", "第二个默认", "2026-01-01 00:00:00", 2, 1),
            )

    _run(data_dir, "downgrade", "0019")
    assert "is_default" not in _columns(data_dir, "projects")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        assert connection.execute(
            "SELECT id FROM projects ORDER BY id"
        ).fetchall() == [("p-general",), ("p-other",)]

    _run(data_dir, "upgrade", "head")
    assert "is_default" in _columns(data_dir, "projects")
    assert "ux_projects_default" in _indexes(data_dir, "projects")


def test_default_project_migration_creates_general_when_missing(tmp_path):
    data_dir = tmp_path / "data"

    _run(data_dir, "upgrade", "0019")
    with sqlite3.connect(_db_path(data_dir)) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, created_at, position) VALUES (?, ?, ?, ?)",
            ("p-other", "别的项目", "2026-01-01 00:00:00", 5),
        )
        connection.execute(
            "INSERT INTO meetings (id, title, state, created_at, project_id)"
            " VALUES (?, ?, ?, ?, ?)",
            ("m1", "没项目的会", "READY", "2026-01-01 00:00:00", None),
        )

    _run(data_dir, "upgrade", "head")

    with sqlite3.connect(_db_path(data_dir)) as connection:
        created = connection.execute(
            "SELECT id, name, position FROM projects WHERE is_default = 1"
        ).fetchall()
        assert len(created) == 1
        project_id, name, position = created[0]
        assert name == "General"
        # 新建的默认项目追加到末尾。
        assert position == 6
        assert connection.execute(
            "SELECT project_id FROM meetings WHERE id = 'm1'"
        ).fetchone() == (project_id,)
