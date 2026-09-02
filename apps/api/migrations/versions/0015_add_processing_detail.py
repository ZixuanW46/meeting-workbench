"""add processing detail for sub-step progress

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-02

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings", sa.Column("processing_detail", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("meetings", "processing_detail")
