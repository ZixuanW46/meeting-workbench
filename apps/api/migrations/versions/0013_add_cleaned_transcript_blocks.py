"""add cleaned transcript blocks

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cleaned_transcript_blocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(length=32), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "block_index"),
    )
    op.create_index(
        op.f("ix_cleaned_transcript_blocks_meeting_id"),
        "cleaned_transcript_blocks",
        ["meeting_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cleaned_transcript_blocks_meeting_id"),
        table_name="cleaned_transcript_blocks",
    )
    op.drop_table("cleaned_transcript_blocks")
