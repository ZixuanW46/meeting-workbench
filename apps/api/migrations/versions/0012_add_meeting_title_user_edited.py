"""track user-edited meeting titles

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column(
            "title_user_edited",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("meetings", "title_user_edited")
