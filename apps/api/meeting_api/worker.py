"""进程内单队列 worker：串行处理转写和纪要生成。"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from meeting_api.config import Settings
from meeting_api.events import EventStore
from meeting_api.minutes.adapter import (
    MinutesAdapter,
    MinutesCliError,
    resolve_minutes_adapter,
)
from meeting_api.models import (
    HotwordEntry,
    Meeting,
    Person,
    SpeakerCluster,
    TranscriptSegment,
    Voiceprint,
)
from meeting_api.pipeline.asr import AsrBackend, AsrSegment, get_asr_backend
from meeting_api.pipeline.diarization import (
    DiarizationBackend,
    SpeakerSegment,
    get_diarization_backend,
)
from meeting_api.pipeline.embedding import (
    EmbeddingBackend,
    embedding_to_bytes,
    get_embedding_backend,
)
from meeting_api.pipeline.serial import SingleModelSlot
from meeting_api.storage import meeting_dir
from meeting_domain import (
    MeetingState,
    SpeakerDecision,
    eligible_for_enrollment,
    snapshot,
    transition,
)

STEP_VALIDATING = "VALIDATING"
STEP_ASR = "ASR"
STEP_DIARIZATION = "DIARIZATION"
STEP_VOICEPRINT_MATCHING = "VOICEPRINT_MATCHING"
STEP_PREPARING_REVIEW = "PREPARING_REVIEW"
STEP_GENERATING_MINUTES = "GENERATING_MINUTES"


class Worker:
    """一次只拉取一场待处理会议；调用方可同步执行一轮。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        asr_backend: AsrBackend | None = None,
        diarization_backend: DiarizationBackend | None = None,
        embedding_backend: EmbeddingBackend | None = None,
        model_slot: SingleModelSlot | None = None,
        event_store: EventStore | None = None,
        minutes_adapter: MinutesAdapter | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.asr_backend = asr_backend or get_asr_backend("fake")
        self.diarization_backend = diarization_backend or get_diarization_backend("fake")
        self.embedding_backend = embedding_backend or get_embedding_backend("fake")
        self.model_slot = model_slot or SingleModelSlot()
        self.events = event_store or EventStore()
        self.minutes_adapter = minutes_adapter or resolve_minutes_adapter(
            settings.minutes_backend
        )
        self._process_lock = threading.Lock()

    def process_next(self) -> str | None:
        """处理最早排队的一场；无任务或本 worker 正忙时返回 None。"""
        if not self._process_lock.acquire(blocking=False):
            return None
        try:
            return self._process_one()
        finally:
            self._process_lock.release()

    def _process_one(self) -> str | None:
        with self.session_factory() as session:
            meeting = session.scalar(
                select(Meeting)
                .where(
                    Meeting.state.in_(
                        [
                            MeetingState.QUEUED.value,
                            MeetingState.GENERATING_MINUTES.value,
                        ]
                    )
                )
                .order_by(Meeting.created_at, Meeting.id)
                .limit(1)
            )
            if meeting is None:
                return None

            if meeting.state == MeetingState.GENERATING_MINUTES.value:
                return self._generate_minutes(session, meeting)

            meeting_id = meeting.id
            global_words = session.scalars(
                select(HotwordEntry.word).order_by(HotwordEntry.word, HotwordEntry.id)
            ).all()
            hotwords = snapshot(global_words, json.loads(meeting.hotwords_json))
            meeting.hotword_snapshot_json = json.dumps(hotwords, ensure_ascii=False)
            meeting.state = transition(
                MeetingState(meeting.state), MeetingState.PROCESSING
            ).value
            meeting.processing_step = STEP_VALIDATING
            meeting.processing_error = None
            session.commit()
            self._publish(meeting)

            try:
                audio_path = self._validate_audio(meeting)

                self._set_step(session, meeting, STEP_ASR)
                hotwords = tuple(json.loads(meeting.hotword_snapshot_json))
                with self.model_slot.use(self.asr_backend) as asr:
                    asr_segments = asr.transcribe(audio_path, hotwords=hotwords)

                self._set_step(session, meeting, STEP_DIARIZATION)
                # 离开上一个槽上下文后 ASR 已卸载，才能加载切分模型。
                with self.model_slot.use(self.diarization_backend) as diarization:
                    speaker_segments = diarization.diarize(
                        audio_path,
                        expected_speakers=meeting.expected_speakers,
                    )
                self._persist_segments(session, meeting_id, asr_segments, speaker_segments)

                self._set_step(session, meeting, STEP_VOICEPRINT_MATCHING)
                self._apply_voiceprint_suggestions(session, meeting_id, audio_path)

                self._set_step(session, meeting, STEP_PREPARING_REVIEW)
                self._prepare_review_samples(session, meeting_id, speaker_segments)

                meeting.state = transition(
                    MeetingState(meeting.state),
                    MeetingState.AWAITING_SPEAKER_REVIEW,
                ).value
                session.commit()
                self._publish(meeting)
            except Exception as exc:
                session.rollback()
                meeting = session.get(Meeting, meeting_id)
                if meeting is not None:
                    meeting.state = transition(
                        MeetingState(meeting.state), MeetingState.FAILED
                    ).value
                    meeting.processing_error = f"{type(exc).__name__}: {exc}"
                    session.commit()
                    self._publish(meeting)
            return meeting_id

    def _generate_minutes(self, session: Session, meeting: Meeting) -> str:
        meeting_id = meeting.id
        meeting.processing_step = STEP_GENERATING_MINUTES
        meeting.processing_error = None
        session.commit()
        self._publish(meeting)

        try:
            transcript = self._build_transcript(session, meeting_id)
            target_dir = meeting_dir(self.settings, meeting_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

            markdown = self.minutes_adapter.generate(transcript)
            if meeting.has_unconfirmed_speakers:
                markdown = f"含未确认说话人\n\n{markdown}"
            (target_dir / "minutes.md").write_text(markdown, encoding="utf-8")
            meeting.state = transition(
                MeetingState(meeting.state), MeetingState.READY
            ).value
            session.commit()
            self._publish(meeting)
        except MinutesCliError as exc:
            session.rollback()
            meeting = session.get(Meeting, meeting_id)
            if meeting is not None:
                meeting.state = transition(
                    MeetingState(meeting.state), MeetingState.PARTIAL_READY
                ).value
                meeting.processing_error = f"{type(exc).__name__}: {exc}"
                session.commit()
                self._publish(meeting)
        except Exception as exc:
            session.rollback()
            meeting = session.get(Meeting, meeting_id)
            if meeting is not None:
                meeting.state = transition(
                    MeetingState(meeting.state), MeetingState.FAILED
                ).value
                meeting.processing_error = f"{type(exc).__name__}: {exc}"
                session.commit()
                self._publish(meeting)
        return meeting_id

    @staticmethod
    def _build_transcript(session: Session, meeting_id: str) -> str:
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds, TranscriptSegment.id)
        ).all()
        if not segments:
            raise ValueError("会议没有逐字稿片段")

        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
        person_ids = {cluster.person_id for cluster in clusters if cluster.person_id}
        people = {
            person.id: person.display_name
            for person in session.scalars(select(Person).where(Person.id.in_(person_ids)))
        }
        labels = {
            cluster.cluster_id: people.get(cluster.person_id)
            or f"未知说话人（{cluster.cluster_id}）"
            for cluster in clusters
        }
        return "\n".join(
            f"[{segment.start_seconds:.2f}-{segment.end_seconds:.2f}] "
            f"{labels.get(segment.cluster_id, segment.cluster_id)}: {segment.text}"
            for segment in segments
        )

    def _validate_audio(self, meeting: Meeting) -> Path:
        if not meeting.audio_filename or not meeting.audio_size or not meeting.audio_sha256:
            raise ValueError("会议缺少完整的音频元数据")
        audio_path = meeting_dir(self.settings, meeting.id) / "raw" / meeting.audio_filename
        if not audio_path.is_file():
            raise FileNotFoundError("会议音频文件不存在")
        if audio_path.stat().st_size != meeting.audio_size:
            raise ValueError("会议音频大小与上传记录不一致")
        return audio_path

    def _set_step(self, session: Session, meeting: Meeting, step: str) -> None:
        meeting.processing_step = step
        session.commit()
        self._publish(meeting)

    def _publish(self, meeting: Meeting) -> None:
        self.events.publish(meeting.id, meeting.state, meeting.processing_step)

    @staticmethod
    def _persist_segments(
        session: Session,
        meeting_id: str,
        asr_segments: Sequence[AsrSegment],
        speaker_segments: Sequence[SpeakerSegment],
    ) -> None:
        if not asr_segments:
            raise ValueError("ASR 未产出转写片段")
        if not speaker_segments:
            raise ValueError("切分未产出说话人片段")

        cluster_ids = sorted({segment.cluster_id for segment in speaker_segments})
        session.add_all(
            SpeakerCluster(meeting_id=meeting_id, cluster_id=cluster_id)
            for cluster_id in cluster_ids
        )
        session.add_all(
            TranscriptSegment(
                meeting_id=meeting_id,
                start_seconds=segment.start,
                end_seconds=segment.end,
                text=segment.text,
                cluster_id=_cluster_for_transcript(segment, speaker_segments),
            )
            for segment in asr_segments
        )
        session.commit()

    def _apply_voiceprint_suggestions(
        self,
        session: Session,
        meeting_id: str,
        audio_path: Path,
    ) -> None:
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        for cluster in clusters:
            cluster.suggested_person_id = None

        voiceprints = session.scalars(
            select(Voiceprint)
            .join(Person, Person.id == Voiceprint.person_id)
            .order_by(Voiceprint.id)
        ).all()
        if voiceprints:
            person_by_embedding = {
                voiceprint.embedding: voiceprint.person_id for voiceprint in voiceprints
            }
            with self.model_slot.use(self.embedding_backend) as embedding_backend:
                for cluster in clusters:
                    candidate = embedding_to_bytes(
                        embedding_backend.embed(audio_path, cluster.cluster_id)
                    )
                    # 这里只给建议；人工决定仍是唯一落名入口。
                    cluster.suggested_person_id = person_by_embedding.get(candidate)
        session.commit()

    def enroll_voiceprints(
        self,
        session: Session,
        meeting: Meeting,
        clusters: Sequence[SpeakerCluster],
        decisions: Sequence[SpeakerDecision],
    ) -> None:
        """在 M5 决定应用后，为符合领域规则的簇生成或更新声纹。"""
        decision_by_cluster = {decision.cluster_id: decision for decision in decisions}
        eligible_clusters = [
            cluster
            for cluster in clusters
            if cluster.person_id is not None
            and eligible_for_enrollment(
                decision_by_cluster[cluster.cluster_id],
                cluster.quality_score,
            )
        ]
        if not eligible_clusters:
            return

        audio_path = self._validate_audio(meeting)
        person_ids = {cluster.person_id for cluster in eligible_clusters}
        existing_by_person = {
            voiceprint.person_id: voiceprint
            for voiceprint in session.scalars(
                select(Voiceprint).where(Voiceprint.person_id.in_(person_ids))
            )
        }
        with self.model_slot.use(self.embedding_backend) as embedding_backend:
            for cluster in eligible_clusters:
                person_id = cluster.person_id
                if person_id is None:  # 已由筛选排除，仅用于类型收窄。
                    continue
                blob = embedding_to_bytes(
                    embedding_backend.embed(audio_path, cluster.cluster_id)
                )
                voiceprint = existing_by_person.get(person_id)
                if voiceprint is None:
                    voiceprint = Voiceprint(person_id=person_id, embedding=blob)
                    session.add(voiceprint)
                    existing_by_person[person_id] = voiceprint
                else:
                    voiceprint.embedding = blob
        session.flush()

    @staticmethod
    def _prepare_review_samples(
        session: Session,
        meeting_id: str,
        speaker_segments: Sequence[SpeakerSegment],
    ) -> None:
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
        for cluster in clusters:
            samples = [
                {
                    "start_seconds": segment.start,
                    "end_seconds": segment.end,
                }
                for segment in speaker_segments
                if segment.cluster_id == cluster.cluster_id
            ][:3]
            if len(samples) < 2:
                raise ValueError(f"说话人簇 {cluster.cluster_id} 缺少足够的试听片段")
            cluster.sample_clips_json = json.dumps(samples, ensure_ascii=False)
        session.commit()


def _cluster_for_transcript(
    transcript: AsrSegment,
    speakers: Sequence[SpeakerSegment],
) -> str:
    def overlap(segment: SpeakerSegment) -> float:
        return max(0.0, min(transcript.end, segment.end) - max(transcript.start, segment.start))

    return max(speakers, key=overlap).cluster_id
