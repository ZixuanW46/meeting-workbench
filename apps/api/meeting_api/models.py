from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from meeting_api.db import Base
from meeting_domain import MeetingState


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(32), default=MeetingState.DRAFT.value)
    # 预计人数是先验，不是硬约束；None = 不确定
    expected_speakers: Mapped[int | None] = mapped_column(default=None)
    hotwords_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    hotword_snapshot_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    audio_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    audio_size: Mapped[int | None] = mapped_column(BigInteger, default=None)
    processing_step: Mapped[str | None] = mapped_column(String(32), default=None)
    processing_error: Mapped[str | None] = mapped_column(Text, default=None)
    has_unconfirmed_speakers: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(default=_now)


class HotwordEntry(Base):
    __tablename__ = "hotword_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    word: Mapped[str] = mapped_column(String(200), unique=True)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    display_name: Mapped[str] = mapped_column(String(200))


class Voiceprint(Base):
    __tablename__ = "voiceprints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    # 每人可有多条模板（上限与淘汰见 meeting_domain.plan_enrollment）。
    person_id: Mapped[str] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime | None] = mapped_column(default=_now)
    # 模板来源会议与该模板试听切片对应的转写摘录，供声纹库页人工核对。
    source_meeting_id: Mapped[str | None] = mapped_column(String(32), default=None)
    snippet_text: Mapped[str] = mapped_column(Text, default="", server_default="")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    cluster_id: Mapped[str] = mapped_column(String(32))


# 簇身份来源标记：写进 SpeakerCluster.assigned_via。
ASSIGNED_VIA_VOICEPRINT_NEAREST = "voiceprint_nearest"


class SpeakerCluster(Base):
    __tablename__ = "speaker_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[str] = mapped_column(String(32))
    # 该簇在切分产物里的累计发言秒数（碎簇合并后口径），供确认停点排序与展示。
    total_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    suggested_person_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # 建议档位：high=「较高」/ uncertain=「需判断」。定性两档，绝不存相似度数值。
    suggested_tier: Mapped[str | None] = mapped_column(String(16), default=None)
    sample_clips_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    # M10 fake 质量：默认合格；测试可显式降分，不引入真实 VAD。
    quality_score: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    # 簇声纹（匹配阶段写入），供「按声纹就近归属」在决定应用时复用。
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    # 身份来源：NULL=人工直接决定；voiceprint_nearest=用户授权的就近归属。
    assigned_via: Mapped[str | None] = mapped_column(String(32), default=None)
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("persons.id"), default=None
    )
    is_unknown: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
