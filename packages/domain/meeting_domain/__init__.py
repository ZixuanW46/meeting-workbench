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
    RETRANSCRIBABLE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    MeetingState,
    can_transition,
    transition,
)
from meeting_domain.voiceprint import (
    VOICEPRINT_QUALITY_THRESHOLD,
    eligible_for_enrollment,
)

__all__ = [
    "ACTIVE_STATES",
    "RETRANSCRIBABLE_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "VOICEPRINT_QUALITY_THRESHOLD",
    "DecisionKind",
    "FakeMeetingPipeline",
    "InvalidTransition",
    "MeetingState",
    "ReviewIncomplete",
    "SpeakerCard",
    "SpeakerDecision",
    "can_transition",
    "decision_field_error",
    "eligible_for_enrollment",
    "has_unconfirmed_speakers",
    "review_complete",
    "snapshot",
    "transition",
]
