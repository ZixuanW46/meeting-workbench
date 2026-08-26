from __future__ import annotations

import json
from typing import Self

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from meeting_api.models import Meeting, Person, SpeakerCluster, TranscriptSegment
from meeting_domain import (
    DecisionKind,
    MeetingState,
    ReviewIncomplete,
    SpeakerCard,
    SpeakerDecision,
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


class ReviewCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    suggested_person_id: str | None
    sample_clips: list[ReviewSample]
    text: str


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[ReviewCard]


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

        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()

        text_by_cluster: dict[str, list[str]] = {}
        for segment in segments:
            text_by_cluster.setdefault(segment.cluster_id, []).append(segment.text)

        return ReviewResponse(
            cards=[
                ReviewCard(
                    cluster_id=cluster.cluster_id,
                    suggested_person_id=cluster.suggested_person_id,
                    sample_clips=[
                        ReviewSample.model_validate(sample)
                        for sample in json.loads(cluster.sample_clips_json)
                    ],
                    text="\n".join(text_by_cluster.get(cluster.cluster_id, [])),
                )
                for cluster in clusters
            ]
        )


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
            resolve_person_id(cluster.cluster_id, frozenset())

        applying = transition(
            MeetingState(meeting.state),
            MeetingState.APPLYING_DECISIONS,
        )
        meeting.state = applying.value
        for cluster in clusters:
            person_id = final_person_ids[cluster.cluster_id]
            cluster.person_id = person_id
            cluster.is_unknown = person_id is None
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
