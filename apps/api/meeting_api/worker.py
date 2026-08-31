"""进程内单队列 worker：串行处理转写和纪要生成。"""

from __future__ import annotations

import json
import tempfile
import threading
import wave
from collections.abc import Sequence
from datetime import UTC, datetime
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
from meeting_api.minutes.prompt import (
    build_minutes_glossary,
    build_minutes_prompt,
    load_minutes_glossary,
    load_minutes_template,
    meeting_date_from_created_at,
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
    consolidate_fragment_clusters,
    get_diarization_backend,
    merge_adjacent_turns,
)
from meeting_api.pipeline.embedding import (
    EmbeddingBackend,
    TimeWindow,
    embedding_from_bytes,
    embedding_to_bytes,
    get_embedding_backend,
)
from meeting_api.pipeline.serial import SingleModelSlot
from meeting_api.storage import meeting_dir
from meeting_api.transcript_format import format_transcript_blocks
from meeting_domain import (
    MeetingState,
    SpeakerDecision,
    eligible_for_enrollment,
    match_voiceprint,
    plan_enrollment,
    select_spread_windows,
    snapshot,
    transition,
)

STEP_VALIDATING = "VALIDATING"
STEP_ASR = "ASR"
STEP_DIARIZATION = "DIARIZATION"
STEP_VOICEPRINT_MATCHING = "VOICEPRINT_MATCHING"
STEP_PREPARING_REVIEW = "PREPARING_REVIEW"
STEP_GENERATING_MINUTES = "GENERATING_MINUTES"

# 声纹模板的代表性试听切片上限（秒）：够人听出是谁，又不臃肿。
VOICEPRINT_CLIP_MAX_SECONDS = 10.0


def _best_clip_window(cluster: SpeakerCluster) -> TimeWindow | None:
    """取该簇最长的试听窗，截到切片上限。"""
    windows = [
        (clip["start_seconds"], clip["end_seconds"])
        for clip in json.loads(cluster.sample_clips_json)
    ]
    if not windows:
        return None
    start, end = max(windows, key=lambda window: window[1] - window[0])
    return (start, min(end, start + VOICEPRINT_CLIP_MAX_SECONDS))


def _cluster_windows(
    turns: Sequence[SpeakerSegment], cluster_id: str
) -> list[TimeWindow]:
    """匹配、入库、试听共用同一批簇内时间窗，三个口径必须一致。

    窗来自合并后的发言轮次（相邻亚秒碎段不再各占一条）并做分散取样：
    至多 5 段、覆盖会议不同时段，而不是只有开头的连续几段。
    """
    return select_spread_windows(
        [(turn.start, turn.end) for turn in turns if turn.cluster_id == cluster_id]
    )


def recover_interrupted_meetings(session_factory: sessionmaker[Session]) -> int:
    """进程退出时留在 PROCESSING 的任务无法续跑，启动时明确标记失败。"""
    with session_factory() as session:
        meetings = session.scalars(
            select(Meeting).where(Meeting.state == MeetingState.PROCESSING.value)
        ).all()
        for meeting in meetings:
            meeting.state = transition(
                MeetingState(meeting.state), MeetingState.FAILED
            ).value
            meeting.processing_error = "上次处理中断，已在本次启动时标记为失败"
        if meetings:
            session.commit()
        return len(meetings)


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
        models_dir = settings.data_dir / "models"
        self.asr_backend = asr_backend or get_asr_backend(
            settings.asr_backend, models_dir
        )
        self.diarization_backend = diarization_backend or get_diarization_backend(
            settings.diarization_backend, models_dir
        )
        self.embedding_backend = embedding_backend or get_embedding_backend(
            settings.embedding_backend, models_dir
        )
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
                # 真实音频的自动聚类几乎必产亚秒碎簇；并入最近主簇后再落库，
                # 否则确认包准备会因「凑不齐试听片段」整场失败。
                speaker_segments = consolidate_fragment_clusters(speaker_segments)
                # 发言轮次是逐轮重转写与试听/声纹时间窗的共同粒度。
                turns = merge_adjacent_turns(speaker_segments)
                asr_segments = self._retranscribe_blob_per_turn(
                    audio_path, asr_segments, turns, hotwords
                )
                self._persist_segments(session, meeting_id, asr_segments, speaker_segments)

                self._set_step(session, meeting, STEP_VOICEPRINT_MATCHING)
                self._apply_voiceprint_suggestions(
                    session, meeting_id, audio_path, turns
                )

                self._set_step(session, meeting, STEP_PREPARING_REVIEW)
                self._prepare_review_samples(session, meeting_id, turns)

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
            hotword_entries = [
                tuple(row)
                for row in session.execute(
                    select(HotwordEntry.word, HotwordEntry.note).order_by(
                        HotwordEntry.word, HotwordEntry.id
                    )
                )
            ]
            glossary = build_minutes_glossary(
                hotword_entries,
                load_minutes_glossary(self.settings.data_dir),
            )

            markdown = self.minutes_adapter.generate(
                build_minutes_prompt(
                    transcript,
                    template=load_minutes_template(self.settings.data_dir),
                    glossary=glossary,
                    meeting_date=meeting_date_from_created_at(meeting.created_at),
                )
            )
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
        labels: dict[str, str] = {}
        for cluster in clusters:
            label = people.get(cluster.person_id) or f"未知说话人（{cluster.cluster_id}）"
            labels[cluster.cluster_id] = label
        transcript = format_transcript_blocks(
            [
                (
                    segment.start_seconds,
                    segment.end_seconds,
                    labels.get(segment.cluster_id, segment.cluster_id),
                    segment.text,
                )
                for segment in segments
            ]
        )
        return transcript

    def _retranscribe_blob_per_turn(
        self,
        audio_path: Path,
        asr_segments: Sequence[AsrSegment],
        turns: Sequence[SpeakerSegment],
        hotwords: Sequence[str],
    ) -> Sequence[AsrSegment]:
        """粗粒度转写按发言轮次切音频重转写。

        Qwen3-ASR 只回整段文本（长音频会内部分块成少数巨型段），全部
        转写会被判给单一说话人；当转写粒度远粗于轮次粒度（段数 ×3 仍
        不及轮次数）时逐轮切片重转写，让每句话落在正确的簇上。音频
        不是可解析的 PCM wav（转码前的损坏文件等）时保留整段结果，
        不让会议失败。
        """
        if len(turns) <= 1 or len(asr_segments) * 3 > len(turns):
            return asr_segments
        with tempfile.TemporaryDirectory(prefix="mw-turns-") as scratch:
            pieces: list[tuple[SpeakerSegment, Path]] = []
            try:
                for index, turn in enumerate(turns):
                    piece_path = Path(scratch) / f"turn-{index:04d}.wav"
                    _write_wav_slice(audio_path, turn.start, turn.end, piece_path)
                    pieces.append((turn, piece_path))
            except (wave.Error, EOFError, OSError):
                return asr_segments

            retranscribed: list[AsrSegment] = []
            with self.model_slot.use(self.asr_backend) as asr:
                for turn, piece_path in pieces:
                    text = "".join(
                        piece.text
                        for piece in asr.transcribe(piece_path, hotwords=tuple(hotwords))
                    ).strip()
                    if text:
                        retranscribed.append(AsrSegment(turn.start, turn.end, text))
        return retranscribed or asr_segments

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

        totals: dict[str, float] = {}
        for segment in speaker_segments:
            totals[segment.cluster_id] = (
                totals.get(segment.cluster_id, 0.0) + segment.end - segment.start
            )
        session.add_all(
            SpeakerCluster(
                meeting_id=meeting_id,
                cluster_id=cluster_id,
                total_seconds=total,
            )
            for cluster_id, total in sorted(totals.items())
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
        turns: Sequence[SpeakerSegment],
    ) -> None:
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        for cluster in clusters:
            cluster.suggested_person_id = None
            cluster.suggested_tier = None

        voiceprints = session.scalars(
            select(Voiceprint)
            .join(Person, Person.id == Voiceprint.person_id)
            .order_by(Voiceprint.id)
        ).all()
        # 每人一组模板，匹配取组内最高余弦（顺序对取最大无影响）。
        enrolled: dict[str, list[tuple[float, ...]]] = {}
        for voiceprint in voiceprints:
            enrolled.setdefault(voiceprint.person_id, []).append(
                embedding_from_bytes(voiceprint.embedding)
            )
        # 簇声纹始终落库（空声纹库也落）：入库与「按声纹就近归属」在决定
        # 应用时直接复用，不必再加载声纹模型。
        with self.model_slot.use(self.embedding_backend) as embedding_backend:
            for cluster in clusters:
                windows = _cluster_windows(turns, cluster.cluster_id)
                if not windows:
                    continue
                candidate = embedding_backend.embed(audio_path, windows)
                cluster.embedding = embedding_to_bytes(candidate)
                if not enrolled:
                    continue
                # 这里只给建议；人工决定仍是唯一落名入口。
                match = match_voiceprint(candidate, enrolled)
                if match is not None:
                    cluster.suggested_person_id = match.person_id
                    cluster.suggested_tier = match.tier.value
        session.commit()

    def enroll_voiceprints(
        self,
        session: Session,
        meeting: Meeting,
        clusters: Sequence[SpeakerCluster],
        decisions: Sequence[SpeakerDecision],
    ) -> None:
        """在 M5 决定应用后，按多模板策略为符合领域规则的簇入库声纹。

        候选向量复用匹配阶段落库的簇声纹（缺失才现场补提）；与既有模板
        冗余则替换那条并刷新出处，否则追加，满上限淘汰最旧。每条模板
        同时留 ≤10s 试听切片与该窗的转写摘录，供声纹库页人工核对。
        """
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

        # 旧数据（0010 之前的会议重开确认）没有落库的簇声纹：现场补提一次。
        missing = [
            cluster for cluster in eligible_clusters if cluster.embedding is None
        ]
        if missing:
            with self.model_slot.use(self.embedding_backend) as embedding_backend:
                for cluster in missing:
                    windows: list[TimeWindow] = [
                        (clip["start_seconds"], clip["end_seconds"])
                        for clip in json.loads(cluster.sample_clips_json)
                    ]
                    if not windows:
                        continue
                    cluster.embedding = embedding_to_bytes(
                        embedding_backend.embed(audio_path, windows)
                    )
        eligible_clusters = [
            cluster for cluster in eligible_clusters if cluster.embedding is not None
        ]

        person_ids = {cluster.person_id for cluster in eligible_clusters}
        templates_by_person: dict[str, list[Voiceprint]] = {
            person_id: [] for person_id in person_ids if person_id is not None
        }
        for row in session.scalars(
            select(Voiceprint)
            .where(Voiceprint.person_id.in_(person_ids))
            # 最旧在前（0010 之前的存量行 created_at 为空，视为最旧）。
            .order_by(
                Voiceprint.created_at.is_(None).desc(),
                Voiceprint.created_at,
                Voiceprint.id,
            )
        ):
            templates_by_person[row.person_id].append(row)

        for cluster in eligible_clusters:
            person_id = cluster.person_id
            if person_id is None or cluster.embedding is None:  # 类型收窄
                continue
            candidate = embedding_from_bytes(cluster.embedding)
            rows = templates_by_person.setdefault(person_id, [])
            plan = plan_enrollment(
                [embedding_from_bytes(row.embedding) for row in rows], candidate
            )
            if plan.action == "skip":
                # 该人处于超限待裁决状态：暂停入库，等用户在声纹库页删到上限内。
                continue
            window = _best_clip_window(cluster)
            snippet = self._clip_snippet(
                session, meeting.id, cluster.cluster_id, window
            )
            blob = embedding_to_bytes(candidate)
            if plan.action == "replace" and rows:
                assert plan.replace_index is not None
                target = rows[plan.replace_index]
                target.embedding = blob
                target.created_at = datetime.now(UTC)
                target.source_meeting_id = meeting.id
                target.snippet_text = snippet
            else:
                target = Voiceprint(
                    person_id=person_id,
                    embedding=blob,
                    source_meeting_id=meeting.id,
                    snippet_text=snippet,
                )
                session.add(target)
                rows.append(target)
            session.flush()
            if window is not None:
                self._write_voiceprint_clip(audio_path, window, target.id)
        session.flush()

    def _write_voiceprint_clip(
        self, audio_path: Path, window: TimeWindow, voiceprint_id: str
    ) -> None:
        """留代表性切片供人工试听；音频不可按 PCM 切片时静默跳过，模板仍有效。"""
        target_dir = self.settings.data_dir / "voiceprints"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            _write_wav_slice(
                audio_path, window[0], window[1], target_dir / f"{voiceprint_id}.wav"
            )
        except (wave.Error, EOFError, OSError):
            pass

    @staticmethod
    def _clip_snippet(
        session: Session,
        meeting_id: str,
        cluster_id: str,
        window: TimeWindow | None,
    ) -> str:
        if window is None:
            return ""
        start, end = window
        texts = [
            segment.text
            for segment in session.scalars(
                select(TranscriptSegment)
                .where(
                    TranscriptSegment.meeting_id == meeting_id,
                    TranscriptSegment.cluster_id == cluster_id,
                )
                .order_by(TranscriptSegment.start_seconds)
            )
            if segment.start_seconds < end and segment.end_seconds > start
        ]
        joined = " ".join(texts)
        if len(joined) > 80:
            return f"{joined[:80]}…"
        return joined

    @staticmethod
    def _prepare_review_samples(
        session: Session,
        meeting_id: str,
        turns: Sequence[SpeakerSegment],
    ) -> None:
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
        for cluster in clusters:
            samples = [
                {"start_seconds": start, "end_seconds": end}
                for start, end in _cluster_windows(turns, cluster.cluster_id)
            ]
            # 单次发言者只有 1 个片段也合法；0 片段说明簇与片段已不一致，属数据错误。
            if len(samples) < 1:
                raise ValueError(f"说话人簇 {cluster.cluster_id} 没有任何试听片段")
            cluster.sample_clips_json = json.dumps(samples, ensure_ascii=False)
        session.commit()


def _write_wav_slice(source: Path, start: float, end: float, target: Path) -> None:
    """用标准库 wave 按秒切 PCM wav；非 PCM 或越界由调用方按不可切片处理。"""
    with wave.open(str(source), "rb") as reader:
        rate = reader.getframerate()
        start_frame = max(0, int(start * rate))
        end_frame = min(reader.getnframes(), int(end * rate))
        if end_frame <= start_frame:
            raise wave.Error("切片超出音频范围")
        reader.setpos(start_frame)
        frames = reader.readframes(end_frame - start_frame)
        with wave.open(str(target), "wb") as writer:
            writer.setnchannels(reader.getnchannels())
            writer.setsampwidth(reader.getsampwidth())
            writer.setframerate(rate)
            writer.writeframes(frames)


def _cluster_for_transcript(
    transcript: AsrSegment,
    speakers: Sequence[SpeakerSegment],
) -> str:
    def overlap(segment: SpeakerSegment) -> float:
        return max(0.0, min(transcript.end, segment.end) - max(transcript.start, segment.start))

    return max(speakers, key=overlap).cluster_id
