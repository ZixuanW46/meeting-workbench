"""纯领域逻辑：不依赖 FastAPI / SQLAlchemy / 任何模型运行时。

这里的规则（状态机、说话人确认、词库快照、声纹入库条件）必须全部由单测覆盖，
不允许把规则散落到 API 层或前端。
"""

from meeting_domain.fake_pipeline import FakeMeetingPipeline
from meeting_domain.hotwords import snapshot
from meeting_domain.speaker_review import (
    DecisionKind,
    ReviewIncomplete,
    SpeakerCard,
    SpeakerDecision,
    decision_field_error,
    has_unconfirmed_speakers,
    review_complete,
)
from meeting_domain.state import (
    ACTIVE_STATES,
    REOPENABLE_REVIEW_STATES,
    RETRANSCRIBABLE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    MeetingState,
    can_transition,
    transition,
)
from meeting_domain.voiceprint import (
    VOICEPRINT_HIGH_THRESHOLD,
    VOICEPRINT_QUALITY_THRESHOLD,
    VOICEPRINT_SUGGEST_THRESHOLD,
    SuggestionTier,
    VoiceprintMatch,
    cosine_similarity,
    eligible_for_enrollment,
    match_voiceprint,
)

__all__ = [
    "ACTIVE_STATES",
    "REOPENABLE_REVIEW_STATES",
    "RETRANSCRIBABLE_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "VOICEPRINT_HIGH_THRESHOLD",
    "VOICEPRINT_QUALITY_THRESHOLD",
    "VOICEPRINT_SUGGEST_THRESHOLD",
    "DecisionKind",
    "FakeMeetingPipeline",
    "InvalidTransition",
    "MeetingState",
    "ReviewIncomplete",
    "SpeakerCard",
    "SpeakerDecision",
    "SuggestionTier",
    "VoiceprintMatch",
    "can_transition",
    "cosine_similarity",
    "decision_field_error",
    "eligible_for_enrollment",
    "has_unconfirmed_speakers",
    "match_voiceprint",
    "review_complete",
    "snapshot",
    "transition",
]
