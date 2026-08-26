"""add speaker review decisions and persons

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-26

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "meetings",
        sa.Column(
            "has_unconfirmed_speakers",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )
    # SQLite 不能用 ALTER TABLE 单独新增外键，batch 模式会安全重建该表。
    with op.batch_alter_table("speaker_clusters") as batch_op:
        batch_op.add_column(
            sa.Column("person_id", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("is_unknown", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.create_foreign_key(
            "fk_speaker_clusters_person_id_persons",
            "persons",
            ["person_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("speaker_clusters") as batch_op:
        batch_op.drop_constraint(
            "fk_speaker_clusters_person_id_persons",
            type_="foreignkey",
        )
        batch_op.drop_column("is_unknown")
        batch_op.drop_column("person_id")
    op.drop_column("meetings", "has_unconfirmed_speakers")
    op.drop_table("persons")
