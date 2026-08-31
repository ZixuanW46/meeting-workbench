"""add notes to hotword entries

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hotword_entries", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("hotword_entries", "note")
