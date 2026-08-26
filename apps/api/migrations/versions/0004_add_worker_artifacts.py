"""add worker artifacts and processing status

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("processing_step", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "meetings",
        sa.Column("processing_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(length=32), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcript_segments_meeting_id",
        "transcript_segments",
        ["meeting_id"],
    )
    op.create_table(
        "speaker_clusters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(length=32), nullable=False),
        sa.Column("cluster_id", sa.String(length=32), nullable=False),
        sa.Column("suggested_person_id", sa.String(length=32), nullable=True),
        sa.Column("sample_clips_json", sa.Text(), server_default="[]", nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_speaker_clusters_meeting_id",
        "speaker_clusters",
        ["meeting_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_speaker_clusters_meeting_id", table_name="speaker_clusters")
    op.drop_table("speaker_clusters")
    op.drop_index("ix_transcript_segments_meeting_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_column("meetings", "processing_error")
    op.drop_column("meetings", "processing_step")
