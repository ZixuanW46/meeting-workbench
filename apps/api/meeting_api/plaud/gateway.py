"""Plaud 网关：把 MCP 工具的文本返回翻译成领域数据结构。

工具返回的 `content[0].text` 是一段 JSON 文本，但尾部偶尔会跟提示语，
所以统一用 `json.JSONDecoder().raw_decode` 取第一个 JSON 值。
时间串形如 "2026-09-05T13:08:13"，**没有时区后缀但实际是 UTC**，按 UTC 解释。
"""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any, Protocol

from meeting_api.config import Settings
from meeting_api.plaud.errors import (
    PLAUD_NOT_LOGGED_IN_MESSAGE,
    PlaudAuthError,
    PlaudError,
    PlaudTimeoutError,
    PlaudUnavailableError,
)
from meeting_api.plaud.mcp_client import McpStdioClient, ToolResult

__all__ = [
    "FakePlaudGateway",
    "McpPlaudGateway",
    "PlaudAuthError",
    "PlaudError",
    "PlaudGateway",
    "PlaudRecording",
    "PlaudTimeoutError",
    "PlaudUnavailableError",
    "PlaudUser",
    "resolve_plaud_gateway",
]

# 未登录的判别只能靠文案：MCP 把 401 也包成普通的 isError 文本。
_AUTH_MARKERS = ("not authenticated", "unauthorized", "401")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class PlaudRecording:
    file_id: str
    name: str
    started_at: datetime  # 带时区，统一为 UTC
    duration_ms: int
    presigned_url: str | None = None


@dataclass(frozen=True)
class PlaudUser:
    nickname: str | None
    email: str | None


class PlaudGateway(Protocol):
    def available(self) -> bool: ...

    def current_user(self) -> PlaudUser: ...

    def list_recordings(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[list[PlaudRecording], bool]: ...

    def get_recording(self, file_id: str) -> PlaudRecording: ...

    def login(self) -> str: ...


def parse_plaud_datetime(raw: object) -> datetime | None:
    """解析 Plaud 时间串；没有时区后缀的一律按 UTC 解释。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _first_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    if not stripped:
        raise PlaudError("Plaud 返回了空响应")
    try:
        value, _ = decoder.raw_decode(stripped)
    except ValueError as exc:
        raise PlaudError(f"Plaud 返回无法解析的内容：{stripped[:120]}") from exc
    return value


def _as_int(raw: object) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def recording_from_payload(payload: Any) -> PlaudRecording:
    if not isinstance(payload, dict):
        raise PlaudError("Plaud 返回的录音数据格式不对")
    started_at = (
        parse_plaud_datetime(payload.get("start_at"))
        or parse_plaud_datetime(payload.get("created_at"))
        or _EPOCH
    )
    presigned_url = payload.get("presigned_url")
    return PlaudRecording(
        file_id=str(payload.get("id") or ""),
        name=str(payload.get("name") or ""),
        started_at=started_at,
        duration_ms=_as_int(payload.get("duration")),
        presigned_url=presigned_url if isinstance(presigned_url, str) and presigned_url else None,
    )


class McpPlaudGateway:
    """真实网关：每次调用起一个 plaud-mcp 子进程。"""

    def __init__(
        self,
        *,
        command: str,
        timeout_seconds: float = 60.0,
        login_timeout_seconds: float = 150.0,
        path: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._argv = shlex.split(command)
        self._timeout_seconds = timeout_seconds
        self._login_timeout_seconds = login_timeout_seconds
        self._path = path
        self._client = client or McpStdioClient(
            self._argv, timeout_seconds=timeout_seconds, path=path
        )

    def available(self) -> bool:
        """只看命令在不在 PATH，绝不为了探测起子进程。"""
        if not self._argv:
            return False
        return shutil.which(self._argv[0], path=self._path) is not None

    def _call(self, name: str, arguments: dict[str, Any], timeout_seconds: float) -> str:
        result: ToolResult = self._client.call_tool(
            name, arguments, timeout_seconds=timeout_seconds
        )
        if result.is_error:
            text = result.text.strip()
            if any(marker in text.lower() for marker in _AUTH_MARKERS):
                raise PlaudAuthError(PLAUD_NOT_LOGGED_IN_MESSAGE)
            raise PlaudError(text or "Plaud 返回了未知错误")
        return result.text

    def current_user(self) -> PlaudUser:
        payload = _first_json(self._call("get_current_user", {}, self._timeout_seconds))
        if not isinstance(payload, dict):
            raise PlaudError("Plaud 返回的账号数据格式不对")
        nickname = payload.get("nickname")
        email = payload.get("email")
        return PlaudUser(
            nickname=nickname if isinstance(nickname, str) and nickname else None,
            email=email if isinstance(email, str) and email else None,
        )

    def list_recordings(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[list[PlaudRecording], bool]:
        arguments: dict[str, Any] = {"page": page, "page_size": page_size}
        if query:
            arguments["query"] = query
        if date_from is not None:
            arguments["date_from"] = date_from.isoformat()
        if date_to is not None:
            arguments["date_to"] = date_to.isoformat()
        filtered = len(arguments) > 2

        payload = _first_json(self._call("list_files", arguments, self._timeout_seconds))
        if not isinstance(payload, dict):
            raise PlaudError("Plaud 返回的列表数据格式不对")
        rows = payload.get("data")
        items = [recording_from_payload(row) for row in rows] if isinstance(rows, list) else []
        # 带过滤时上游忽略分页，只用 truncated 表示「还有更多没扫到」。
        has_more = bool(payload.get("truncated")) if filtered else len(items) == page_size
        return items, has_more

    def get_recording(self, file_id: str) -> PlaudRecording:
        payload = _first_json(
            self._call("get_file", {"file_id": file_id}, self._timeout_seconds)
        )
        return recording_from_payload(payload)

    def login(self) -> str:
        """在服务器所在机器打开浏览器做 OAuth，返回 MCP 的原始文案。"""
        return self._call("login", {}, self._login_timeout_seconds).strip()


class FakePlaudGateway:
    """内存网关：测试与本地开发用，不起进程、不联网。"""

    def __init__(
        self,
        *,
        recordings: list[PlaudRecording] | None = None,
        user: PlaudUser | None = None,
        installed: bool = True,
        error: PlaudError | None = None,
        recording_queue: dict[str, list[PlaudRecording]] | None = None,
    ) -> None:
        self.recordings = list(recordings or [])
        # 每个 file_id 排队的定制返回：用完自动落回 recordings，用来模拟「先没有直链、再有」。
        self.recording_queue: dict[str, list[PlaudRecording]] = {
            key: list(value) for key, value in (recording_queue or {}).items()
        }
        self.get_recording_calls: list[str] = []
        self.user = user or PlaudUser(nickname="Plaud 用户", email="user@example.com")
        self.installed = installed
        self.error = error
        self.login_message = "Successfully authenticated with Plaud!"

    def _raise_if_configured(self) -> None:
        if self.error is not None:
            raise self.error

    def available(self) -> bool:
        return self.installed

    def current_user(self) -> PlaudUser:
        self._raise_if_configured()
        return self.user

    def list_recordings(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[list[PlaudRecording], bool]:
        self._raise_if_configured()
        matched = [
            recording
            for recording in self.recordings
            if _fake_matches(recording, query, date_from, date_to)
        ]
        if query or date_from is not None or date_to is not None:
            return matched, False
        start = (page - 1) * page_size
        window = matched[start : start + page_size]
        # 与真实网关一致：整页即认为后面还有。
        return window, len(window) == page_size

    def get_recording(self, file_id: str) -> PlaudRecording:
        self.get_recording_calls.append(file_id)
        self._raise_if_configured()
        queued = self.recording_queue.get(file_id)
        if queued:
            return replace(queued.pop(0))
        for recording in self.recordings:
            if recording.file_id == file_id:
                return replace(recording)
        raise PlaudError(f"Failed to get file: {file_id}")

    def login(self) -> str:
        if isinstance(self.error, PlaudAuthError):
            self.error = None
        self._raise_if_configured()
        return self.login_message


def _fake_matches(
    recording: PlaudRecording,
    query: str | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if query and query.lower() not in recording.name.lower():
        return False
    local_date = recording.started_at.astimezone().date()
    if date_from is not None and local_date < date_from:
        return False
    return not (date_to is not None and local_date > date_to)


def resolve_plaud_gateway(settings: Settings) -> PlaudGateway:
    if settings.plaud_backend == "fake":
        return FakePlaudGateway()
    return McpPlaudGateway(
        command=settings.plaud_mcp_command,
        timeout_seconds=settings.plaud_mcp_timeout_seconds,
        login_timeout_seconds=settings.plaud_login_timeout_seconds,
    )
