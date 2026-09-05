"""Plaud 网关：工具返回文本解析、UTC 无时区时间、raw_decode 容错、错误分类。

全部用桩客户端，不起子进程也不联网。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from meeting_api.config import Settings
from meeting_api.plaud.gateway import (
    FakePlaudGateway,
    McpPlaudGateway,
    PlaudAuthError,
    PlaudError,
    resolve_plaud_gateway,
)
from meeting_api.plaud.mcp_client import ToolResult


class _StubClient:
    """记录调用并按预设返回；模拟 MCP 客户端的 call_tool 签名。"""

    def __init__(self, results: dict[str, ToolResult]) -> None:
        self._results = results
        self.calls: list[tuple[str, dict, float | None]] = []

    def call_tool(self, name, arguments, *, timeout_seconds=None):
        self.calls.append((name, arguments, timeout_seconds))
        return self._results[name]


def _gateway(results: dict[str, ToolResult]) -> tuple[McpPlaudGateway, _StubClient]:
    stub = _StubClient(results)
    gateway = McpPlaudGateway(command="plaud-mcp", client=stub)
    return gateway, stub


def _text(payload: object, *, trailing: str = "") -> ToolResult:
    return ToolResult(text=json.dumps(payload, ensure_ascii=False) + trailing, is_error=False)


def test_list_recordings_reads_naive_timestamps_as_utc():
    gateway, stub = _gateway(
        {
            "list_files": _text(
                {
                    "type": "list",
                    "data": [
                        {
                            "id": "file-1",
                            "name": "2026-09-05 21:08:13",
                            "created_at": "2026-09-05T13:08:13",
                            "start_at": "2026-09-05T13:00:00",
                            "duration": 5232000,
                        }
                    ],
                    "page": 1,
                    "page_size": 20,
                }
            )
        }
    )

    items, has_more = gateway.list_recordings(
        page=1, page_size=20, query=None, date_from=None, date_to=None
    )

    assert len(items) == 1
    assert items[0].file_id == "file-1"
    assert items[0].name == "2026-09-05 21:08:13"
    # start_at 优先于 created_at，且无后缀的 ISO 串按 UTC 解释。
    assert items[0].started_at == datetime(2026, 9, 5, 13, 0, 0, tzinfo=UTC)
    assert items[0].duration_ms == 5232000
    assert has_more is False
    assert stub.calls[0][0] == "list_files"
    assert stub.calls[0][1] == {"page": 1, "page_size": 20}


def test_started_at_falls_back_to_created_at():
    gateway, _ = _gateway(
        {
            "list_files": _text(
                {"data": [{"id": "f", "name": "n", "created_at": "2026-09-05T13:08:13"}]}
            )
        }
    )

    items, _ = gateway.list_recordings(
        page=1, page_size=20, query=None, date_from=None, date_to=None
    )

    assert items[0].started_at == datetime(2026, 9, 5, 13, 8, 13, tzinfo=UTC)


def test_has_more_uses_full_page_without_filter_and_truncated_with_filter():
    full_page = _text({"data": [{"id": str(index), "name": "n"} for index in range(2)]})
    gateway, stub = _gateway({"list_files": full_page})

    _, has_more = gateway.list_recordings(
        page=1, page_size=2, query=None, date_from=None, date_to=None
    )
    assert has_more is True

    filtered_gateway, filtered_stub = _gateway(
        {"list_files": _text({"data": [{"id": "1", "name": "n"}], "truncated": True})}
    )
    _, filtered_has_more = filtered_gateway.list_recordings(
        page=1,
        page_size=20,
        query="周会",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 5),
    )

    assert filtered_has_more is True
    assert filtered_stub.calls[0][1] == {
        "page": 1,
        "page_size": 20,
        "query": "周会",
        "date_from": "2026-09-01",
        "date_to": "2026-09-05",
    }
    assert stub.calls[0][1] == {"page": 1, "page_size": 2}


def test_trailing_text_after_json_is_tolerated():
    payload = {"nickname": "Will", "email": "w@example.com"}
    gateway, _ = _gateway(
        {"get_current_user": _text(payload, trailing="\n提示：仅供参考")}
    )

    user = gateway.current_user()

    assert user.nickname == "Will"
    assert user.email == "w@example.com"


def test_unparsable_text_raises_plaud_error():
    gateway, _ = _gateway({"get_current_user": ToolResult(text="不是 JSON", is_error=False)})

    with pytest.raises(PlaudError):
        gateway.current_user()


@pytest.mark.parametrize(
    "message",
    ["Not authenticated", "API error: 401", "Failed: Unauthorized access"],
)
def test_authentication_failures_map_to_auth_error(message):
    gateway, _ = _gateway({"get_current_user": ToolResult(text=message, is_error=True)})

    with pytest.raises(PlaudAuthError):
        gateway.current_user()


def test_other_tool_errors_map_to_plaud_error():
    gateway, _ = _gateway(
        {"get_file": ToolResult(text="Failed to get file: API error: 500", is_error=True)}
    )

    with pytest.raises(PlaudError) as excinfo:
        gateway.get_recording("missing")

    assert not isinstance(excinfo.value, PlaudAuthError)
    assert "500" in str(excinfo.value)


def test_get_recording_carries_presigned_url_or_none():
    with_url, stub = _gateway(
        {
            "get_file": _text(
                {
                    "id": "file-1",
                    "name": "周会",
                    "start_at": "2026-09-05T13:00:00",
                    "duration": 1000,
                    "presigned_url": "https://example.invalid/audiofiles/file-1.mp3",
                }
            )
        }
    )
    recording = with_url.get_recording("file-1")
    assert recording.presigned_url == "https://example.invalid/audiofiles/file-1.mp3"
    # 每次调用都显式带上超时，客户端默认值只是兜底。
    assert stub.calls[0] == ("get_file", {"file_id": "file-1"}, 60.0)

    without_url, _ = _gateway({"get_file": _text({"id": "file-1", "name": "周会"})})
    assert without_url.get_recording("file-1").presigned_url is None


def test_login_returns_tool_text_and_uses_login_timeout():
    stub = _StubClient(
        {"login": ToolResult(text="Successfully authenticated with Plaud!", is_error=False)}
    )
    gateway = McpPlaudGateway(command="plaud-mcp", client=stub, login_timeout_seconds=150.0)

    assert gateway.login() == "Successfully authenticated with Plaud!"
    assert stub.calls[0][0] == "login"
    assert stub.calls[0][2] == 150.0


def test_available_only_looks_at_path(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "plaud-mcp"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)

    assert McpPlaudGateway(command="plaud-mcp", path=str(bin_dir)).available() is True
    assert McpPlaudGateway(command="plaud-mcp", path=str(tmp_path)).available() is False
    # 支持 `node /abs/path/index.js` 这类多段命令：只看第一段。
    assert (
        McpPlaudGateway(command="plaud-mcp --verbose", path=str(bin_dir)).available() is True
    )


def test_resolve_gateway_follows_backend_setting(tmp_path: Path):
    fake = resolve_plaud_gateway(Settings(data_dir=tmp_path, plaud_backend="fake"))
    real = resolve_plaud_gateway(
        Settings(data_dir=tmp_path, plaud_backend="mcp", plaud_mcp_command="node /tmp/index.js")
    )

    assert isinstance(fake, FakePlaudGateway)
    assert isinstance(real, McpPlaudGateway)


def test_plaud_settings_defaults(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)

    assert settings.plaud_backend == "mcp"
    assert settings.plaud_mcp_command == "plaud-mcp"
    assert settings.plaud_mcp_timeout_seconds == 60
    assert settings.plaud_login_timeout_seconds == 150
    assert settings.plaud_download_timeout_seconds == 900
