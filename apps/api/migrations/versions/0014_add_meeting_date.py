"""add user-set meeting date

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-02

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("meeting_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "meeting_date")
