"""multi template voiceprints and cluster embedding provenance

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-28

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 多模板声纹：去掉 person_id 唯一约束（SQLite 列级 UNIQUE 是内部自动索引，
    # 只能整表重建去除），并补 入库时间/来源会议/转写摘录 三列。
    # 存量单模板行原样保留为该人的第一条模板（旧行无试听切片与摘录）。
    op.rename_table("voiceprints", "voiceprints_single")
    # SQLite 重命名表时索引跟随旧表但保留原名，先删掉才能给新表建同名索引。
    op.drop_index("ix_voiceprints_person_id", table_name="voiceprints_single")
    op.create_table(
        "voiceprints",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "person_id",
            sa.String(length=32),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("source_meeting_id", sa.String(length=32), nullable=True),
        sa.Column("snippet_text", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_voiceprints_person_id", "voiceprints", ["person_id"])
    op.execute(
        "INSERT INTO voiceprints (id, person_id, embedding, snippet_text) "
        "SELECT id, person_id, embedding, '' FROM voiceprints_single"
    )
    op.drop_table("voiceprints_single")

    # 确认停点的「按声纹就近归属」需要簇声纹与归属来源：
    # embedding 在声纹匹配阶段写入；assigned_via 记录身份来源
    # （NULL=人工直接决定，voiceprint_nearest=用户授权的就近归属）。
    op.add_column(
        "speaker_clusters", sa.Column("embedding", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "speaker_clusters", sa.Column("assigned_via", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("speaker_clusters", "assigned_via")
    op.drop_column("speaker_clusters", "embedding")

    # 回到单模板：每人只保留最早入库的一条。
    op.rename_table("voiceprints", "voiceprints_multi")
    op.drop_index("ix_voiceprints_person_id", table_name="voiceprints_multi")
    op.create_table(
        "voiceprints",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "person_id",
            sa.String(length=32),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_voiceprints_person_id", "voiceprints", ["person_id"])
    op.execute(
        "INSERT INTO voiceprints (id, person_id, embedding) "
        "SELECT id, person_id, embedding FROM voiceprints_multi "
        "WHERE id IN (SELECT MIN(id) FROM voiceprints_multi GROUP BY person_id)"
    )
    op.drop_table("voiceprints_multi")
