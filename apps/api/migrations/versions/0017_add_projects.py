"""add projects, project hotwords and meeting project attachment

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "project_hotwords",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("word", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_hotwords_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        # 同一项目内词语唯一；不同项目可以有同一个词。
        sa.UniqueConstraint("project_id", "word"),
    )
    op.create_index(
        "ix_project_hotwords_project_id", "project_hotwords", ["project_id"]
    )
    # SQLite 不能用 ALTER TABLE 单独新增外键，batch 模式会安全重建该表。
    # 存量会议一律「无项目」（NULL）。
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(
            sa.Column("project_id", sa.String(length=32), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_meetings_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_meetings_project_id", "meetings", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_meetings_project_id", table_name="meetings")
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.drop_constraint(
            "fk_meetings_project_id_projects", type_="foreignkey"
        )
        batch_op.drop_column("project_id")
    op.drop_index("ix_project_hotwords_project_id", table_name="project_hotwords")
    op.drop_table("project_hotwords")
    op.drop_table("projects")
