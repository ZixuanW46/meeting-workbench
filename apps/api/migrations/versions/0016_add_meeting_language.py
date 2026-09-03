"""add meeting language (zh / en)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 存量会议一律按中文；SQLite 加非空列必须带常量默认值。
    op.add_column(
        "meetings",
        sa.Column(
            "language",
            sa.String(length=8),
            server_default="zh",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("meetings", "language")
