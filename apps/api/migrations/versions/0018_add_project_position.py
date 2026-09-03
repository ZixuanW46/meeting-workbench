"""add user defined ordering to projects

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    # 存量项目按原先的展示顺序（name, id）回填 0,1,2…，升级前后看到的顺序一致。
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id FROM projects ORDER BY name, id")
    ).fetchall()
    for index, (project_id,) in enumerate(rows):
        connection.execute(
            sa.text("UPDATE projects SET position = :position WHERE id = :id"),
            {"position": index, "id": project_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("position")
