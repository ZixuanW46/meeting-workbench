"""add meeting plaud file id

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 来源 Plaud 云端录音的会议记下 file_id；存量会议留空。
    op.add_column(
        "meetings",
        sa.Column("plaud_file_id", sa.String(length=64), nullable=True),
    )
    # 唯一索引挡住同一条录音被导入两次；SQLite 的唯一索引允许多个 NULL，
    # 所以本地上传的会议不受影响。
    op.create_index(
        "ix_meetings_plaud_file_id",
        "meetings",
        ["plaud_file_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_meetings_plaud_file_id", table_name="meetings")
    # SQLite 删带索引的列必须走 batch（重建表）。
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.drop_column("plaud_file_id")
