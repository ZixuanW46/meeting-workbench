"""add voiceprints and speaker cluster quality

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "speaker_clusters",
        sa.Column("quality_score", sa.Float(), server_default="1.0", nullable=False),
    )
    op.create_table(
        "voiceprints",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("person_id", sa.String(length=32), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_voiceprints_person_id"),
        "voiceprints",
        ["person_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_voiceprints_person_id"), table_name="voiceprints")
    op.drop_table("voiceprints")
    op.drop_column("speaker_clusters", "quality_score")
