"""add speaker cluster suggested tier

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-27

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 建议档位：high=「较高」/ uncertain=「需判断」。定性两档，不存相似度数值。
    # 存量建议是旧字节匹配产物，留空即可；重新处理或重开确认会重算。
    op.add_column(
        "speaker_clusters",
        sa.Column("suggested_tier", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("speaker_clusters", "suggested_tier")
