from __future__ import annotations

import json
from typing import Literal, Self

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from meeting_api.models import (
    ASSIGNED_VIA_VOICEPRINT_NEAREST,
    Meeting,
    Person,
    SpeakerCluster,
    TranscriptSegment,
)
from meeting_api.pipeline.embedding import embedding_from_bytes
from meeting_api.speaker_labels import review_ordered_clusters
from meeting_domain import (
    REOPENABLE_REVIEW_STATES,
    DecisionKind,
    MeetingState,
    ReviewIncomplete,
    SpeakerCard,
    SpeakerDecision,
    SuggestionTier,
    cosine_similarity,
    decision_field_error,
    has_unconfirmed_speakers,
    review_complete,
    transition,
)
from meeting_domain.speaker_review import missing_decisions

router = APIRouter(prefix="/api/meetings")


class ReviewSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float
    end_seconds: float
    # 该时间窗内、同簇的逐段转写摘录；无覆盖时为空串。
    text: str = ""


class ReviewCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    # 该簇的累计发言秒数（事实数据，非置信度）：确认页排序与「累计发言」展示用。
    total_seconds: float
    suggested_person_id: str | None
    # 建议身份的显示名：定性表达，绝不附带数值置信度。
    suggested_display_name: str | None
    # 建议档位只有两档：high=「较高」/ uncertain=「需判断」；无建议时为 None。
    suggested_tier: Literal["high", "uncertain"] | None
    sample_clips: list[ReviewSample]
    text: str


class ReviewPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[ReviewCard]
    # 全局人员清单：供「换成其他人 / 从声纹库选择」下拉使用。
    people: list[ReviewPerson]


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    kind: DecisionKind
    person_id: str | None = None
    merge_into_cluster_id: str | None = None
    display_name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Self:
        # 字段级规则在领域层，API 只翻译成 422。
        error = decision_field_error(self.to_domain())
        if error is not None:
            raise ValueError(error)
        if self.display_name is not None:
            self.display_name = self.display_name.strip()
        return self

    def to_domain(self) -> SpeakerDecision:
        return SpeakerDecision(
            cluster_id=self.cluster_id,
            kind=self.kind,
            person_id=self.person_id,
            merge_into_cluster_id=self.merge_into_cluster_id,
            display_name=self.display_name,
        )


class ReviewDecisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DecisionPayload]


class ReviewDecisionsResponse(BaseModel):
    state: str
    has_unconfirmed_speakers: bool


@router.get("/{meeting_id}/review", response_model=ReviewResponse)
def get_review(meeting_id: str, request: Request) -> ReviewResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        if meeting.state != MeetingState.AWAITING_SPEAKER_REVIEW.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="会议当前不在说话人确认阶段",
            )

        # 主要说话人排最前：几十簇的真实录音里，人工确认从时长大的簇开始才可用。
        clusters = review_ordered_clusters(session, meeting_id)
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()

        text_by_cluster: dict[str, list[str]] = {}
        for segment in segments:
            text_by_cluster.setdefault(segment.cluster_id, []).append(segment.text)

        people = session.scalars(
            select(Person).order_by(Person.display_name, Person.id)
        ).all()
        name_by_id = {person.id: person.display_name for person in people}

        def clip_text(cluster_id: str, start: float, end: float) -> str:
            texts = [
                segment.text
                for segment in segments
                if segment.cluster_id == cluster_id
                and segment.start_seconds < end
                and segment.end_seconds > start
            ]
            joined = " ".join(texts)
            if len(joined) > 160:
                return f"{joined[:160]}…"
            return joined

        return ReviewResponse(
            cards=[
                ReviewCard(
                    cluster_id=cluster.cluster_id,
                    total_seconds=cluster.total_seconds,
                    suggested_person_id=cluster.suggested_person_id,
                    suggested_display_name=name_by_id.get(cluster.suggested_person_id)
                    if cluster.suggested_person_id is not None
                    else None,
                    suggested_tier=cluster.suggested_tier
                    if cluster.suggested_person_id is not None
                    else None,
                    sample_clips=[
                        ReviewSample(
                            start_seconds=sample["start_seconds"],
                            end_seconds=sample["end_seconds"],
                            text=clip_text(
                                cluster.cluster_id,
                                sample["start_seconds"],
                                sample["end_seconds"],
                            ),
                        )
                        for sample in json.loads(cluster.sample_clips_json)
                    ],
                    text="\n".join(text_by_cluster.get(cluster.cluster_id, [])),
                )
                for cluster in clusters
            ],
            people=[
                ReviewPerson(id=person.id, display_name=person.display_name)
                for person in people
            ],
        )


class ReviewReopenResponse(BaseModel):
    state: str


@router.post("/{meeting_id}/review/reopen", response_model=ReviewReopenResponse)
def reopen_review(meeting_id: str, request: Request) -> ReviewReopenResponse:
    """READY / PARTIAL_READY 重开说话人确认：复用转写与切分，确认后只重出纪要。"""
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        current = MeetingState(meeting.state)
        if current not in REOPENABLE_REVIEW_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前会议状态不允许重新确认说话人",
            )

        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
        for cluster in clusters:
            # 上一轮已确认的身份回填为建议：重开后可一键「确认建议」，
            # 最终身份仍由本轮用户决定产生。用户亲自确认过 → 档位「较高」。
            if cluster.person_id is not None:
                cluster.suggested_person_id = cluster.person_id
                cluster.suggested_tier = SuggestionTier.HIGH.value

        meeting.state = transition(
            current, MeetingState.AWAITING_SPEAKER_REVIEW
        ).value
        meeting.processing_error = None
        session.commit()

        request.app.state.events.publish(
            meeting.id, meeting.state, meeting.processing_step
        )
        return ReviewReopenResponse(state=meeting.state)


@router.post(
    "/{meeting_id}/review/decisions",
    response_model=ReviewDecisionsResponse,
)
def submit_decisions(
    meeting_id: str,
    payload: ReviewDecisionsRequest,
    request: Request,
) -> ReviewDecisionsResponse:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        if meeting.state != MeetingState.AWAITING_SPEAKER_REVIEW.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="会议当前不在说话人确认阶段",
            )

        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        cards = [
            SpeakerCard(cluster.cluster_id, cluster.suggested_person_id)
            for cluster in clusters
        ]
        domain_decisions = [decision.to_domain() for decision in payload.decisions]

        try:
            if not review_complete(cards, domain_decisions):
                raise ReviewIncomplete(missing_decisions(cards, domain_decisions))
        except ReviewIncomplete as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": str(exc),
                    "missing_cluster_ids": exc.missing_cluster_ids,
                },
            ) from exc

        cluster_by_id = {cluster.cluster_id: cluster for cluster in clusters}
        request_by_id = {decision.cluster_id: decision for decision in payload.decisions}
        final_person_ids: dict[str, str | None] = {}
        nearest_cluster_ids: list[str] = []

        for decision in payload.decisions:
            cluster = cluster_by_id[decision.cluster_id]
            if decision.kind == DecisionKind.CONFIRM:
                if cluster.suggested_person_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=f"说话人簇 {cluster.cluster_id} 没有可确认的建议身份",
                    )
                # SQLite 未开外键强制，这里必须自己保证建议身份真实存在。
                if session.get(Person, cluster.suggested_person_id) is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=f"建议身份不存在于人员表: {cluster.suggested_person_id}",
                    )
                final_person_ids[cluster.cluster_id] = cluster.suggested_person_id
            elif decision.kind in {
                DecisionKind.REASSIGN,
                DecisionKind.LINK_EXISTING,
            }:
                if session.get(Person, decision.person_id) is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=f"人员不存在: {decision.person_id}",
                    )
                final_person_ids[cluster.cluster_id] = decision.person_id
            elif decision.kind == DecisionKind.NEW_PERSON:
                person = Person(display_name=decision.display_name)
                session.add(person)
                session.flush()
                final_person_ids[cluster.cluster_id] = person.id
            elif decision.kind == DecisionKind.NEAREST_CONFIRMED:
                # 两阶段：先解析出全部已确认者，再做封闭集内的就近归属。
                nearest_cluster_ids.append(cluster.cluster_id)
            elif decision.kind in {
                DecisionKind.KEEP_UNKNOWN,
                DecisionKind.UNDECIDED_UNKNOWN,
            }:
                final_person_ids[cluster.cluster_id] = None

        def resolve_person_id(cluster_id: str, path: frozenset[str]) -> str | None:
            if cluster_id in final_person_ids:
                return final_person_ids[cluster_id]
            if cluster_id in path:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="说话人簇合并决定不能形成循环",
                )
            decision = request_by_id[cluster_id]
            target_id = decision.merge_into_cluster_id
            if target_id not in cluster_by_id or target_id == cluster_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"无效的合并目标: {target_id}",
                )
            resolved = resolve_person_id(target_id, path | {cluster_id})
            final_person_ids[cluster_id] = resolved
            return resolved

        for cluster in clusters:
            if cluster.cluster_id in nearest_cluster_ids:
                continue
            resolve_person_id(cluster.cluster_id, frozenset())

        if nearest_cluster_ids:
            anchors = [
                cluster
                for cluster in clusters
                if cluster.cluster_id not in nearest_cluster_ids
                and final_person_ids.get(cluster.cluster_id) is not None
                and cluster.embedding is not None
            ]
            if not anchors:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="就近归属需要本场至少一位已确认参会人",
                )
            for cluster_id in nearest_cluster_ids:
                cluster = cluster_by_id[cluster_id]
                if cluster.embedding is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=(
                            f"说话人簇 {cluster_id} 缺少簇声纹，"
                            "请先重转写后再使用就近归属"
                        ),
                    )
                candidate = embedding_from_bytes(cluster.embedding)
                best = max(
                    anchors,
                    key=lambda anchor: cosine_similarity(
                        candidate, embedding_from_bytes(anchor.embedding)
                    ),
                )
                final_person_ids[cluster_id] = final_person_ids[best.cluster_id]

        applying = transition(
            MeetingState(meeting.state),
            MeetingState.APPLYING_DECISIONS,
        )
        meeting.state = applying.value
        for cluster in clusters:
            person_id = final_person_ids[cluster.cluster_id]
            cluster.person_id = person_id
            cluster.is_unknown = person_id is None
            cluster.assigned_via = (
                ASSIGNED_VIA_VOICEPRINT_NEAREST
                if cluster.cluster_id in nearest_cluster_ids
                else None
            )
        meeting.has_unconfirmed_speakers = has_unconfirmed_speakers(domain_decisions)
        request.app.state.worker.enroll_voiceprints(
            session,
            meeting,
            clusters,
            domain_decisions,
        )
        generating = transition(applying, MeetingState.GENERATING_MINUTES)
        meeting.state = generating.value
        session.commit()

        request.app.state.events.publish(
            meeting.id,
            applying.value,
            meeting.processing_step,
        )
        request.app.state.events.publish(
            meeting.id,
            generating.value,
            meeting.processing_step,
        )
        return ReviewDecisionsResponse(
            state=meeting.state,
            has_unconfirmed_speakers=meeting.has_unconfirmed_speakers,
        )
