from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import StreamingResponse

from meeting_api.events import EventStore


def _create_meeting(client) -> str:
    response = client.post("/api/meetings", json={"title": "进度测试会议"})
    assert response.status_code == 201
    return response.json()["id"]


def _queue_meeting(client) -> str:
    meeting_id = _create_meeting(client)
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert response.status_code == 200
    return meeting_id


def _events_response(client, meeting_id: str, last_event_id: int | None = None):
    routes = []
    for registered in client.app.routes:
        nested_router = getattr(registered, "original_router", None)
        routes.extend(nested_router.routes if nested_router is not None else [registered])
    route = next(
        (
            route
            for route in routes
            if getattr(route, "path", None) == "/api/meetings/{meeting_id}/events"
        ),
        None,
    )
    assert route is not None, "SSE 事件路由尚未实现"
    request = Request(
        {
            "type": "http",
            "app": client.app,
            "method": "GET",
            "path": f"/api/meetings/{meeting_id}/events",
            "headers": [],
        }
    )
    return route.endpoint(
        meeting_id=meeting_id,
        request=request,
        last_event_id=last_event_id,
    )


def _parse_event(chunk: str | bytes) -> tuple[int, dict[str, object]]:
    text = chunk.decode() if isinstance(chunk, bytes) else chunk
    fields = dict(line.split(": ", 1) for line in text.strip().splitlines())
    return int(fields["id"]), json.loads(fields["data"])


def _request_sse(
    client,
    meeting_id: str,
    count: int,
    *,
    last_event_id: int | None = None,
) -> tuple[int, dict[str, str], list[tuple[int, dict[str, object]]]]:
    async def request():
        request_sent = False
        enough_events = asyncio.Event()
        status_code = 0
        response_headers: dict[str, str] = {}
        events: list[tuple[int, dict[str, object]]] = []

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await enough_events.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = {
                    key.decode(): value.decode() for key, value in message["headers"]
                }
            elif message["type"] == "http.response.body" and message.get("body"):
                events.append(_parse_event(message["body"]))
                if len(events) >= count:
                    enough_events.set()
                    await asyncio.sleep(0)

        headers = []
        if last_event_id is not None:
            headers.append((b"last-event-id", str(last_event_id).encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": f"/api/meetings/{meeting_id}/events",
            "raw_path": f"/api/meetings/{meeting_id}/events".encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
        await client.app(scope, receive, send)
        return status_code, response_headers, events

    return asyncio.run(request())


def _read_events(
    response: StreamingResponse,
    count: int,
    *,
    after_first: Callable[[], None] | None = None,
) -> list[tuple[int, dict[str, object]]]:
    async def consume() -> list[tuple[int, dict[str, object]]]:
        events = []
        try:
            for index in range(count):
                events.append(_parse_event(await anext(response.body_iterator)))
                if index == 0 and after_first is not None:
                    after_first()
        finally:
            await response.body_iterator.aclose()
        return events

    return asyncio.run(consume())


def test_sse_returns_json_progress_events_with_monotonic_ids(client):
    meeting_id = _queue_meeting(client)
    client.app.state.worker.process_next()

    status_code, headers, events = _request_sse(client, meeting_id, 3)

    assert status_code == 200
    assert headers["content-type"].startswith("text/event-stream")
    ids = [event_id for event_id, _ in events]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    for event_id, data in events:
        assert data.keys() == {"state", "processing_step", "seq"}
        assert data["seq"] == event_id


def test_sse_reconnect_only_returns_events_after_last_event_id(client):
    meeting_id = _queue_meeting(client)
    client.app.state.worker.process_next()

    _, _, first_events = _request_sse(client, meeting_id, 2)
    last_seen = first_events[-1][0]

    _, _, replayed = _request_sse(
        client,
        meeting_id,
        2,
        last_event_id=last_seen,
    )

    assert replayed
    assert all(event_id > last_seen for event_id, _ in replayed)


def test_progress_polling_returns_current_value(client):
    meeting_id = _queue_meeting(client)
    client.app.state.worker.process_next()

    response = client.get(f"/api/meetings/{meeting_id}/progress")

    assert response.status_code == 200
    assert response.json().keys() == {"state", "processing_step", "seq"}
    assert response.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    assert response.json()["processing_step"] == "PREPARING_REVIEW"
    assert isinstance(response.json()["seq"], int)


def test_worker_progress_change_is_read_from_an_open_event_stream(client):
    meeting_id = _queue_meeting(client)
    response = _events_response(client, meeting_id)

    events = _read_events(
        response,
        2,
        after_first=client.app.state.worker.process_next,
    )

    assert events[0][1]["state"] == "QUEUED"
    assert events[1][0] > events[0][0]
    assert events[1][1] == {
        "state": "PROCESSING",
        "processing_step": "VALIDATING",
        "seq": events[1][0],
    }


def test_events_and_progress_return_404_for_missing_meeting(client):
    progress = client.get("/api/meetings/not-found/progress")
    assert progress.status_code == 404

    events = client.get("/api/meetings/not-found/events")
    assert events.status_code == 404


def _next_chunk(stream, timeout: float = 2.0) -> str:
    """在子线程里取下一个 chunk；超时未返回视为生成器永久阻塞。"""
    result: list[str] = []
    thread = threading.Thread(target=lambda: result.append(next(stream)), daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "SSE 生成器阻塞未在超时内返回"
    return result[0]


def test_sse_stream_yields_keepalive_when_idle_instead_of_blocking_forever():
    # 客户端断开后，卡在 condition.wait() 的线程池线程必须能在
    # 一个心跳间隔内返回，否则每个断开的连接都会永久占用一个线程。
    store = EventStore(heartbeat_seconds=0.05)
    store.publish("m1", "AWAITING_SPEAKER_REVIEW", "PREPARING_REVIEW")
    stream = store.iter_events(
        "m1",
        after_seq=0,
        state="AWAITING_SPEAKER_REVIEW",
        processing_step="PREPARING_REVIEW",
    )

    first_id, _ = _parse_event(_next_chunk(stream))
    assert first_id == 1

    assert _next_chunk(stream) == ": keep-alive\n\n"


def test_sse_reconnect_with_stale_last_event_id_after_restart_gets_fresh_snapshot():
    # 模拟进程重启：seq 从 1 重新开始，而客户端还带着重启前的 Last-Event-ID: 7。
    # 必须把 seq 抬过断点补一条快照，否则该客户端会把后续事件全部过滤掉。
    store = EventStore(heartbeat_seconds=0.05)
    store.publish("m1", "PROCESSING", "ASR")

    stream = store.iter_events("m1", after_seq=7, state="PROCESSING", processing_step="ASR")

    event_id, data = _parse_event(_next_chunk(stream))
    assert event_id == 8
    assert data == {"state": "PROCESSING", "processing_step": "ASR", "seq": 8}
