"""Plaud 导入路由：状态、登录、录音列表、导入闭环。

下载走本机 127.0.0.1 上的临时 http.server，测试全程不访问公网。
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meeting_api.config import Settings
from meeting_api.main import create_app
from meeting_api.models import Meeting
from meeting_api.plaud.download import download_to_meeting, filename_from_url
from meeting_api.plaud.gateway import (
    PlaudAuthError,
    PlaudError,
    PlaudRecording,
    PlaudTimeoutError,
    PlaudUnavailableError,
    PlaudUser,
)
from meeting_api.plaud.progress import ImportProgressRegistry

AUDIO_BYTES = b"RIFF\x00\x01plaud-downloaded-audio"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MW_WORKER_DISABLED", "1")
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/test.sqlite3",
        minutes_backend="fake",
        asr_backend="fake",
        diarization_backend="fake",
        embedding_backend="fake",
        plaud_backend="fake",
        # 直链重试逻辑照跑，但别让测试真的睡过去。
        plaud_presigned_url_retry_seconds=0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@contextmanager
def _audio_server(payload: bytes = AUDIO_BYTES) -> Iterator[str]:
    """在 127.0.0.1 上起一个只服务单个文件的临时 HTTP 服务，返回 base URL。"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定的方法名
            if not self.path.startswith("/audiofiles/"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "binary/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _recording(
    file_id: str = "rec-1",
    *,
    name: str = "客户访谈",
    started_at: datetime = datetime(2026, 9, 5, 18, 0, 0, tzinfo=UTC),
    duration_ms: int = 5232000,
    presigned_url: str | None = None,
) -> PlaudRecording:
    return PlaudRecording(
        file_id=file_id,
        name=name,
        started_at=started_at,
        duration_ms=duration_ms,
        presigned_url=presigned_url,
    )


def _gateway(client: TestClient):
    return client.app.state.plaud_gateway


def _meeting_dir(client: TestClient, meeting_id: str) -> Path:
    return client.app.state.settings.data_dir / "meetings" / meeting_id


def test_status_reports_missing_command(client):
    _gateway(client).installed = False

    response = client.get("/api/plaud/status")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["logged_in"] is False
    assert body["user"] is None
    assert "未安装" in body["message"]


def test_status_reports_logged_out(client):
    _gateway(client).error = PlaudAuthError("Plaud 未登录，请先登录")

    body = client.get("/api/plaud/status").json()

    assert body["available"] is True
    assert body["logged_in"] is False
    assert body["user"] is None
    assert body["message"] == "Plaud 未登录，请先登录"


def test_status_reports_logged_in_user(client):
    _gateway(client).user = PlaudUser(nickname="Will", email="will@example.com")

    body = client.get("/api/plaud/status").json()

    assert body == {
        "available": True,
        "logged_in": True,
        "user": {"nickname": "Will", "email": "will@example.com"},
        "message": None,
    }


def test_status_reports_upstream_failure_without_5xx(client):
    _gateway(client).error = PlaudError("连接超时")

    response = client.get("/api/plaud/status")

    assert response.status_code == 200
    assert response.json()["logged_in"] is False
    assert "Plaud 服务异常" in response.json()["message"]


def test_login_returns_message_and_flips_logged_in(client):
    gateway = _gateway(client)
    gateway.error = PlaudAuthError("Plaud 未登录，请先登录")

    response = client.post("/api/plaud/login")

    assert response.status_code == 200
    assert response.json()["logged_in"] is True
    assert "Plaud" in response.json()["message"]
    assert client.get("/api/plaud/status").json()["logged_in"] is True


def test_login_without_command_returns_503(client):
    _gateway(client).installed = False

    response = client.post("/api/plaud/login")

    assert response.status_code == 503
    assert "未安装" in response.json()["detail"]


def test_recordings_paginate_and_backfill_imported_meeting_id(client):
    gateway = _gateway(client)
    with _audio_server() as base:
        gateway.recordings = [
            _recording("rec-0", name="录音 0"),
            _recording("rec-1", name="录音 1", presigned_url=f"{base}/audiofiles/rec-1.wav"),
            _recording("rec-2", name="录音 2"),
        ]
        imported = client.post(
            "/api/plaud/import", json={"plaud_file_id": "rec-1", "hotwords": []}
        )
        assert imported.status_code == 201, imported.text

    body = client.get("/api/plaud/recordings?page=1&page_size=10").json()

    assert [item["file_id"] for item in body["items"]] == ["rec-0", "rec-1", "rec-2"]
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["has_more"] is False
    assert body["filtered"] is False
    assert body["items"][0]["started_at"].endswith("+00:00")
    assert body["items"][0]["duration_ms"] == 5232000
    assert body["items"][0]["imported_meeting_id"] is None
    assert body["items"][1]["imported_meeting_id"] == imported.json()["id"]


def test_recordings_has_more_when_page_is_full(client):
    _gateway(client).recordings = [_recording(f"rec-{index}") for index in range(25)]

    body = client.get("/api/plaud/recordings?page=1&page_size=10").json()

    assert len(body["items"]) == 10
    assert body["has_more"] is True

    last = client.get("/api/plaud/recordings?page=3&page_size=10").json()
    assert len(last["items"]) == 5
    assert last["has_more"] is False


def test_recordings_query_is_trimmed_and_marks_filtered(client):
    _gateway(client).recordings = [
        _recording("rec-1", name="周会纪要"),
        _recording("rec-2", name="客户访谈"),
    ]

    body = client.get("/api/plaud/recordings?query=%20周会%20").json()

    assert [item["file_id"] for item in body["items"]] == ["rec-1"]
    assert body["filtered"] is True

    blank = client.get("/api/plaud/recordings?query=%20%20").json()
    assert blank["filtered"] is False
    assert len(blank["items"]) == 2


def test_recordings_rejects_out_of_range_page_size(client):
    assert client.get("/api/plaud/recordings?page_size=5").status_code == 422
    assert client.get("/api/plaud/recordings?page_size=101").status_code == 422
    assert client.get("/api/plaud/recordings?page=0").status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (PlaudUnavailableError("Plaud MCP 未安装（npm i -g @plaud-ai/mcp）"), 503, "未安装"),
        (PlaudAuthError("Plaud 未登录，请先登录"), 503, "未登录"),
        (PlaudTimeoutError("Plaud 请求超时"), 504, "超时"),
        (PlaudError("上游 500"), 502, "Plaud 服务异常"),
    ],
)
def test_recordings_maps_gateway_errors(client, error, expected_status, expected_detail):
    _gateway(client).error = error

    response = client.get("/api/plaud/recordings")

    assert response.status_code == expected_status
    assert expected_detail in response.json()["detail"]


def test_import_downloads_audio_and_queues_meeting(client, tmp_path):
    started_at = datetime(2026, 9, 5, 18, 0, 0, tzinfo=UTC)
    with _audio_server() as base:
        _gateway(client).recordings = [
            _recording(
                "rec-1",
                name="客户访谈",
                started_at=started_at,
                presigned_url=f"{base}/audiofiles/rec-1.wav",
            )
        ]
        response = client.post(
            "/api/plaud/import",
            json={"plaud_file_id": "rec-1", "language": "en", "hotwords": ["声纹"]},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "QUEUED"
    assert body["plaud_file_id"] == "rec-1"
    assert body["language"] == "en"
    assert body["hotwords"] == ["声纹"]
    # 会议日期取录音开始时间的「本机本地日期」，不是 UTC 日期。
    assert body["meeting_date"] == started_at.astimezone().date().isoformat()
    # 响应里不得出现任何服务器路径。
    assert str(tmp_path) not in response.text

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, body["id"])
        assert meeting is not None
        assert meeting.audio_filename == "rec-1.wav"
        assert meeting.audio_size == len(AUDIO_BYTES)
        assert meeting.audio_sha256 == hashlib.sha256(AUDIO_BYTES).hexdigest()
        assert meeting.plaud_file_id == "rec-1"

    raw = _meeting_dir(client, body["id"]) / "raw" / "rec-1.wav"
    assert raw.read_bytes() == AUDIO_BYTES
    # 列表与详情都要透出 plaud_file_id。
    assert client.get("/api/meetings").json()["items"][0]["plaud_file_id"] == "rec-1"
    assert client.get(f"/api/meetings/{body['id']}").json()["plaud_file_id"] == "rec-1"


def test_import_title_rules(client):
    cases = [
        # 用户填了标题：用它，且算用户命名。
        ({"title": "季度复盘"}, "2026-09-05 21:08:13", "季度复盘", True),
        # Plaud 里没改过名（设备默认名）：占位，交给自动命名接管。
        ({}, "2026-09-05 21:08:13", "2026-09-05 21:08:13", False),
        # 用户在 Plaud 里改过名：尊重它，不再自动改名。
        ({}, "客户访谈", "客户访谈", True),
    ]
    for index, (extra, plaud_name, expected_title, expected_edited) in enumerate(cases):
        file_id = f"rec-{index}"
        with _audio_server() as base:
            _gateway(client).recordings = [
                _recording(
                    file_id,
                    name=plaud_name,
                    presigned_url=f"{base}/audiofiles/{file_id}.wav",
                )
            ]
            response = client.post(
                "/api/plaud/import", json={"plaud_file_id": file_id, **extra}
            )

        assert response.status_code == 201, response.text
        assert response.json()["title"] == expected_title
        with client.app.state.session_factory() as session:
            meeting = session.get(Meeting, response.json()["id"])
            assert meeting is not None
            assert meeting.title_user_edited is expected_edited


def test_import_uses_payload_meeting_date_when_given(client):
    with _audio_server() as base:
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/audiofiles/rec-1.wav")
        ]
        response = client.post(
            "/api/plaud/import",
            json={"plaud_file_id": "rec-1", "meeting_date": "2026-08-31"},
        )

    assert response.status_code == 201
    assert response.json()["meeting_date"] == "2026-08-31"
    assert response.json()["meeting_date_source"] == "user"


def test_import_rejects_duplicate_recording(client):
    with _audio_server() as base:
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/audiofiles/rec-1.wav")
        ]
        assert (
            client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"}).status_code
            == 201
        )
        duplicate = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "该 Plaud 录音已导入"


def test_import_without_presigned_url_returns_422(client):
    gateway = _gateway(client)
    gateway.recordings = [_recording("rec-1", presigned_url=None)]

    response = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert response.status_code == 422
    assert response.json()["detail"] == "这条录音的音频暂不可下载，请稍后再试"
    # 每次都没直链才判死：首次 + 配置的重试次数。
    expected_calls = 1 + client.app.state.settings.plaud_presigned_url_retries
    assert gateway.get_recording_calls == ["rec-1"] * expected_calls
    with client.app.state.session_factory() as session:
        assert session.query(Meeting).count() == 0


def test_import_retries_when_presigned_url_missing_then_succeeds(client):
    """云端偶发少了直链，重试一次就有——不该把用户挡在 422 上。"""
    gateway = _gateway(client)
    with _audio_server() as base:
        gateway.recording_queue = {
            "rec-1": [
                _recording("rec-1", presigned_url=None),
                _recording("rec-1", presigned_url=f"{base}/audiofiles/rec-1.wav"),
            ]
        }
        response = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert response.status_code == 201, response.text
    assert gateway.get_recording_calls == ["rec-1", "rec-1"]
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, response.json()["id"])
        assert meeting is not None
        assert meeting.plaud_file_id == "rec-1"
        assert meeting.state == "QUEUED"


def test_import_cleans_up_meeting_when_download_fails(client):
    with _audio_server() as base:
        # 服务器只认 /audiofiles/ 前缀，其它路径一律 404。
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/missing/rec-1.wav")
        ]
        response = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert response.status_code == 502
    assert "Plaud" in response.json()["detail"]
    with client.app.state.session_factory() as session:
        assert session.query(Meeting).count() == 0
    meetings_root = client.app.state.settings.data_dir / "meetings"
    assert not meetings_root.exists() or not any(meetings_root.iterdir())


def test_import_requires_non_empty_file_id(client):
    assert client.post("/api/plaud/import", json={}).status_code == 422
    assert (
        client.post("/api/plaud/import", json={"plaud_file_id": "  "}).status_code == 422
    )


def test_import_maps_gateway_auth_error(client):
    _gateway(client).error = PlaudAuthError("Plaud 未登录，请先登录")

    response = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert response.status_code == 503
    assert "未登录" in response.json()["detail"]


def test_import_without_project_lands_in_the_default_project(client):
    """不选项目的导入落默认项目，和新建会议同一套规则。"""
    with _audio_server() as base:
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/audiofiles/rec-1.wav")
        ]
        response = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert response.status_code == 201, response.text
    projects = client.get("/api/projects").json()["items"]
    (default_project,) = [item for item in projects if item["is_default"]]
    assert response.json()["project_id"] == default_project["id"]
    assert response.json()["project_name"] == default_project["name"]


def test_import_rejects_unknown_project(client):
    response = client.post(
        "/api/plaud/import", json={"plaud_file_id": "rec-1", "project_id": "nope"}
    )

    assert response.status_code == 404


def test_filename_from_url_keeps_basename_and_defaults_to_mp3():
    assert filename_from_url("https://x.invalid/audiofiles/abc123.mp3", "abc123") == "abc123.mp3"
    assert filename_from_url("https://x.invalid/audiofiles/abc123?x=1", "abc123") == "abc123.mp3"
    assert filename_from_url("https://x.invalid/", "abc123") == "abc123.mp3"
    # 路径里的目录穿越必须被抹掉。
    assert filename_from_url("https://x.invalid/a/../..", "abc123") == "abc123.mp3"


def test_import_progress_unknown_file_id_returns_404(client):
    response = client.get("/api/plaud/import-progress/rec-unknown")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_import_progress_reports_done_after_successful_import(client):
    with _audio_server() as base:
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/audiofiles/rec-1.wav")
        ]
        imported = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert imported.status_code == 201, imported.text
    body = client.get("/api/plaud/import-progress/rec-1").json()

    assert body == {
        "file_id": "rec-1",
        "phase": "done",
        "bytes_done": len(AUDIO_BYTES),
        "bytes_total": len(AUDIO_BYTES),
        "meeting_id": imported.json()["id"],
        "error": None,
    }


def test_import_progress_reports_failure_with_response_detail(client):
    with _audio_server() as base:
        # 服务器只认 /audiofiles/ 前缀，其它路径一律 404 → 导入以 502 收场。
        _gateway(client).recordings = [
            _recording("rec-1", presigned_url=f"{base}/missing/rec-1.wav")
        ]
        failed = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert failed.status_code == 502
    body = client.get("/api/plaud/import-progress/rec-1").json()

    assert body["phase"] == "failed"
    assert body["error"] == failed.json()["detail"]
    assert body["meeting_id"] is None


def test_import_progress_reports_failure_when_no_presigned_url(client):
    _gateway(client).recordings = [_recording("rec-1", presigned_url=None)]

    failed = client.post("/api/plaud/import", json={"plaud_file_id": "rec-1"})

    assert failed.status_code == 422
    body = client.get("/api/plaud/import-progress/rec-1").json()
    assert body["phase"] == "failed"
    assert body["error"] == failed.json()["detail"]


def test_progress_registry_evicts_finished_entries_after_retention():
    now = [1000.0]
    registry = ImportProgressRegistry(retention_seconds=120.0, clock=lambda: now[0])

    registry.start("rec-1")
    registry.finish("rec-1", "meeting-1")

    now[0] += 119.0
    entry = registry.get("rec-1")
    assert entry is not None
    assert entry.phase == "done"
    assert entry.meeting_id == "meeting-1"

    now[0] += 2.0
    assert registry.get("rec-1") is None
    # 已清理的条目不会被后续回调复活。
    assert registry.update("rec-1", bytes_done=5) is None


def test_progress_registry_keeps_in_flight_entries_past_retention():
    now = [0.0]
    registry = ImportProgressRegistry(
        retention_seconds=120.0, stale_seconds=3600.0, clock=lambda: now[0]
    )
    registry.start("rec-1")
    registry.update("rec-1", phase="downloading", bytes_done=1024)

    now[0] += 600.0
    entry = registry.get("rec-1")
    assert entry is not None
    assert entry.phase == "downloading"
    assert entry.bytes_done == 1024

    now[0] += 3601.0
    assert registry.get("rec-1") is None


def test_download_to_meeting_reports_final_progress(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(data_dir=data_dir, plaud_backend="fake")
    calls: list[tuple[int, int | None]] = []

    with _audio_server() as base:
        saved = download_to_meeting(
            settings,
            "meeting-1",
            f"{base}/audiofiles/rec-1.wav",
            "rec-1.wav",
            on_progress=lambda done, total: calls.append((done, total)),
        )

    total = len(AUDIO_BYTES)
    assert saved.size == total
    assert calls[-1] == (total, total)
    assert all(done <= total for done, _ in calls)
