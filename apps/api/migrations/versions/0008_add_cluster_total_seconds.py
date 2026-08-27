"""add speaker cluster total seconds

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-27

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "speaker_clusters",
        sa.Column("total_seconds", sa.Float(), server_default="0", nullable=False),
    )
    # 存量会议没有留切分产物，用逐段转写时长求和近似回填，重开确认时排序仍可用。
    op.execute(
        """
        UPDATE speaker_clusters SET total_seconds = COALESCE(
            (
                SELECT SUM(t.end_seconds - t.start_seconds)
                FROM transcript_segments AS t
                WHERE t.meeting_id = speaker_clusters.meeting_id
                  AND t.cluster_id = speaker_clusters.cluster_id
            ),
            0
        )
        """
    )


def downgrade() -> None:
    op.drop_column("speaker_clusters", "total_seconds")
