"""add global hotword library and meeting snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-26

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hotword_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("word", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("word"),
    )
    op.add_column(
        "meetings",
        sa.Column(
            "hotword_snapshot_json",
            sa.Text(),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("meetings", "hotword_snapshot_json")
    op.drop_table("hotword_entries")
