from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text
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


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    display_name: Mapped[str] = mapped_column(String(200))


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


class SpeakerCluster(Base):
    __tablename__ = "speaker_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[str] = mapped_column(String(32))
    suggested_person_id: Mapped[str | None] = mapped_column(String(32), default=None)
    sample_clips_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("persons.id"), default=None
    )
    is_unknown: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
