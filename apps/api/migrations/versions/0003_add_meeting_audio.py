"""add meeting audio metadata

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("audio_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column("audio_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column("audio_size", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meetings", "audio_size")
    op.drop_column("meetings", "audio_sha256")
    op.drop_column("meetings", "audio_filename")
