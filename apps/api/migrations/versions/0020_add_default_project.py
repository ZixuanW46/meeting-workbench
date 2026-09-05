"""add default project flag and drop the no-project state

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-06

"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

DEFAULT_PROJECT_NAME = "General"


def _default_project_id(connection: sa.Connection) -> str:
    """已有 General（大小写不敏感）就用它，否则新建一个追加到末尾。"""
    row = connection.execute(
        sa.text(
            "SELECT id FROM projects WHERE lower(name) = lower(:name)"
            " ORDER BY position, id LIMIT 1"
        ),
        {"name": DEFAULT_PROJECT_NAME},
    ).fetchone()
    if row is not None:
        connection.execute(
            sa.text("UPDATE projects SET is_default = 1 WHERE id = :id"),
            {"id": row[0]},
        )
        return str(row[0])

    max_position = connection.execute(sa.text("SELECT MAX(position) FROM projects")).scalar()
    project_id = uuid.uuid4().hex
    connection.execute(
        sa.text(
            "INSERT INTO projects (id, name, created_at, position, is_default)"
            " VALUES (:id, :name, :created_at, :position, 1)"
        ),
        {
            "id": project_id,
            "name": DEFAULT_PROJECT_NAME,
            "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
            "position": 0 if max_position is None else max_position + 1,
        },
    )
    return project_id


def _merge_hotwords_into_global(connection: sa.Connection, project_id: str) -> None:
    """默认项目不再维护自己的热词：存量词条并进全局词库后删掉。"""
    rows = connection.execute(
        sa.text(
            "SELECT word, note FROM project_hotwords WHERE project_id = :id"
            " ORDER BY word, id"
        ),
        {"id": project_id},
    ).fetchall()
    for word, note in rows:
        existing = connection.execute(
            sa.text("SELECT id, note FROM hotword_entries WHERE word = :word"),
            {"word": word},
        ).fetchone()
        if existing is None:
            connection.execute(
                sa.text(
                    "INSERT INTO hotword_entries (id, word, note)"
                    " VALUES (:id, :word, :note)"
                ),
                {"id": uuid.uuid4().hex, "word": word, "note": note},
            )
        elif existing[1] is None and note is not None:
            # 全局已有同词：保留全局的说法，只有全局没写注解时才用项目的。
            connection.execute(
                sa.text("UPDATE hotword_entries SET note = :note WHERE id = :id"),
                {"note": note, "id": existing[0]},
            )
    connection.execute(
        sa.text("DELETE FROM project_hotwords WHERE project_id = :id"),
        {"id": project_id},
    )


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
    )
    # 部分唯一索引：默认项目最多一个，其余行的 is_default = 0 不受约束。
    op.create_index(
        "ux_projects_default",
        "projects",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )

    connection = op.get_bind()
    project_id = _default_project_id(connection)
    _merge_hotwords_into_global(connection, project_id)
    # 「无项目」的会议一律回填到默认项目。
    connection.execute(
        sa.text("UPDATE meetings SET project_id = :id WHERE project_id IS NULL"),
        {"id": project_id},
    )


def downgrade() -> None:
    # 只回滚结构：并过的词与回填的归属留在原地，不做数据回滚。
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_index("ux_projects_default")
        batch_op.drop_column("is_default")
