"""单进程会议进度事件与 SSE / 轮询端点。"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from meeting_api.models import Meeting
from meeting_api.schemas import ProgressResponse

router = APIRouter(prefix="/api/meetings")


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    state: str
    processing_step: str | None
    seq: int


class EventStore:
    """保存每场会议的进程内事件历史；进程重启后由数据库当前值补齐。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._events: dict[str, list[ProgressEvent]] = defaultdict(list)
        self._sequences: dict[str, int] = defaultdict(int)

    def publish(
        self,
        meeting_id: str,
        state: str,
        processing_step: str | None,
    ) -> ProgressEvent:
        with self._condition:
            return self._publish_locked(meeting_id, state, processing_step)

    def current(
        self,
        meeting_id: str,
        state: str,
        processing_step: str | None,
    ) -> ProgressEvent:
        """返回与数据库一致的最新事件；缺历史或值落后时补一个快照。"""
        with self._condition:
            return self._ensure_current_locked(meeting_id, state, processing_step)

    def iter_events(
        self,
        meeting_id: str,
        *,
        after_seq: int,
        state: str,
        processing_step: str | None,
    ) -> Iterator[str]:
        """先重放断点后的历史，再等待并推送后续事件。"""
        with self._condition:
            self._ensure_current_locked(
                meeting_id,
                state,
                processing_step,
                minimum_seq=after_seq + 1,
            )

        cursor = after_seq
        while True:
            with self._condition:
                pending = [
                    event for event in self._events[meeting_id] if event.seq > cursor
                ]
                while not pending:
                    self._condition.wait()
                    pending = [
                        event for event in self._events[meeting_id] if event.seq > cursor
                    ]

            for event in pending:
                cursor = event.seq
                yield _format_sse(event)

    def _ensure_current_locked(
        self,
        meeting_id: str,
        state: str,
        processing_step: str | None,
        *,
        minimum_seq: int = 1,
    ) -> ProgressEvent:
        history = self._events[meeting_id]
        if history:
            latest = history[-1]
            if latest.state == state and latest.processing_step == processing_step:
                return latest
        self._sequences[meeting_id] = max(self._sequences[meeting_id], minimum_seq - 1)
        return self._publish_locked(meeting_id, state, processing_step)

    def _publish_locked(
        self,
        meeting_id: str,
        state: str,
        processing_step: str | None,
    ) -> ProgressEvent:
        self._sequences[meeting_id] += 1
        event = ProgressEvent(
            state=state,
            processing_step=processing_step,
            seq=self._sequences[meeting_id],
        )
        self._events[meeting_id].append(event)
        self._condition.notify_all()
        return event


def _format_sse(event: ProgressEvent) -> str:
    data = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\ndata: {data}\n\n"


def _get_meeting(request: Request, meeting_id: str) -> Meeting:
    with request.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
        session.expunge(meeting)
        return meeting


@router.get("/{meeting_id}/events")
def get_events(
    meeting_id: str,
    request: Request,
    last_event_id: Annotated[
        int | None,
        Header(alias="Last-Event-ID", ge=0),
    ] = None,
) -> StreamingResponse:
    meeting = _get_meeting(request, meeting_id)
    event_store: EventStore = request.app.state.events
    stream = event_store.iter_events(
        meeting.id,
        after_seq=last_event_id or 0,
        state=meeting.state,
        processing_step=meeting.processing_step,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{meeting_id}/progress", response_model=ProgressResponse)
def get_progress(meeting_id: str, request: Request) -> ProgressResponse:
    meeting = _get_meeting(request, meeting_id)
    event_store: EventStore = request.app.state.events
    current = event_store.current(
        meeting.id,
        meeting.state,
        meeting.processing_step,
    )
    return ProgressResponse(**asdict(current))
