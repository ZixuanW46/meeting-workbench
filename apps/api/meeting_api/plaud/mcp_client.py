"""最小 MCP stdio 客户端：起进程 → initialize → initialized → tools/call → 关进程。

不做长驻进程：每次工具调用起一个新的 MCP server，用完即关（实测启动 + 握手约 0.2 s）。
逐行读 stdout，解析不了的行和 id 不匹配的消息一律跳过（server 会发通知）；
stderr 是 pino JSON 日志，只留末尾一小段用于报错。
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from os import environ
from typing import IO, Any

from meeting_api.plaud.errors import (
    PLAUD_NOT_INSTALLED_MESSAGE,
    PLAUD_TIMEOUT_MESSAGE,
    PlaudError,
    PlaudTimeoutError,
    PlaudUnavailableError,
)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "meeting-workbench", "version": "0.1.0"}
DEFAULT_TIMEOUT_SECONDS = 60.0
# 子进程只透传这两个变量本体，其余按前缀放行。
_PASSTHROUGH_ENV = ("PATH", "HOME")
_PASSTHROUGH_PREFIXES = ("MW_", "PLAUD_")
_STDERR_TAIL_BYTES = 2048
_TERMINATE_GRACE_SECONDS = 3.0

_INITIALIZE_ID = 1
_CALL_ID = 2


@dataclass(frozen=True)
class ToolResult:
    text: str
    is_error: bool


def child_env() -> dict[str, str]:
    """子进程环境：PATH、HOME（MCP 要读 ~/.plaud）与 MW_/PLAUD_ 前缀变量。"""
    env = {name: environ[name] for name in _PASSTHROUGH_ENV if name in environ}
    for name, value in environ.items():
        if name.startswith(_PASSTHROUGH_PREFIXES):
            env[name] = value
    return env


class McpStdioClient:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        path: str | None = None,
    ) -> None:
        self._argv = list(argv)
        self._timeout_seconds = timeout_seconds
        self._path = path

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        if not self._argv:
            raise PlaudUnavailableError(PLAUD_NOT_INSTALLED_MESSAGE)
        executable = shutil.which(self._argv[0], path=self._path)
        if executable is None:
            raise PlaudUnavailableError(PLAUD_NOT_INSTALLED_MESSAGE)

        timeout = timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        deadline = time.monotonic() + timeout
        # 空临时目录做 cwd：MCP server 看不到仓库文件，跑完即清理。
        with tempfile.TemporaryDirectory(prefix="mw-plaud-") as scratch:
            try:
                process = subprocess.Popen(
                    [executable, *self._argv[1:]],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=scratch,
                    env=child_env(),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise PlaudUnavailableError(f"{PLAUD_NOT_INSTALLED_MESSAGE}：{exc}") from exc
            try:
                return self._session(process, name, arguments, deadline)
            finally:
                _shutdown(process)

    def _session(
        self,
        process: subprocess.Popen[str],
        name: str,
        arguments: Mapping[str, Any],
        deadline: float,
    ) -> ToolResult:
        lines: queue.Queue[str | None] = queue.Queue()
        stderr_tail: list[str] = []
        _spawn_reader(process.stdout, lines)
        _spawn_stderr_collector(process.stderr, stderr_tail)

        self._send(
            process,
            stderr_tail,
            {
                "jsonrpc": "2.0",
                "id": _INITIALIZE_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            },
        )
        self._await(lines, _INITIALIZE_ID, deadline, stderr_tail)
        self._send(
            process,
            stderr_tail,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        self._send(
            process,
            stderr_tail,
            {
                "jsonrpc": "2.0",
                "id": _CALL_ID,
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            },
        )
        return _to_tool_result(self._await(lines, _CALL_ID, deadline, stderr_tail))

    def _send(
        self,
        process: subprocess.Popen[str],
        stderr_tail: list[str],
        payload: Mapping[str, Any],
    ) -> None:
        stdin = process.stdin
        if stdin is None:
            raise PlaudError(_failure_detail("Plaud MCP 无法写入请求", stderr_tail))
        try:
            stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise PlaudError(
                _failure_detail(f"Plaud MCP 进程意外退出：{exc}", stderr_tail)
            ) from exc

    def _await(
        self,
        lines: queue.Queue[str | None],
        expected_id: int,
        deadline: float,
        stderr_tail: list[str],
    ) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PlaudTimeoutError(PLAUD_TIMEOUT_MESSAGE)
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise PlaudTimeoutError(PLAUD_TIMEOUT_MESSAGE) from exc
            if line is None:
                raise PlaudError(
                    _failure_detail("Plaud MCP 进程意外退出", stderr_tail)
                )
            message = _parse_line(line)
            if message is None or message.get("id") != expected_id:
                # 解析不了的日志行、通知、以及别的请求的响应，一律跳过。
                continue
            error = message.get("error")
            if error is not None:
                raise PlaudError(f"Plaud MCP 返回错误：{error}")
            return message


def _parse_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        message = json.loads(stripped)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def _to_tool_result(message: Mapping[str, Any]) -> ToolResult:
    result = message.get("result")
    if not isinstance(result, dict):
        raise PlaudError("Plaud MCP 响应缺少 result")
    text = ""
    for block in result.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            text = block["text"]
            break
    return ToolResult(text=text, is_error=bool(result.get("isError")))


def _spawn_reader(stream: IO[str] | None, lines: queue.Queue[str | None]) -> None:
    def pump() -> None:
        try:
            if stream is not None:
                for line in stream:
                    lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            lines.put(None)

    threading.Thread(target=pump, name="plaud-mcp-stdout", daemon=True).start()


def _spawn_stderr_collector(stream: IO[str] | None, tail: list[str]) -> None:
    """持续排空 stderr，避免 pino 日志写满管道把 server 卡死；只留末尾一小段。"""

    def drain() -> None:
        try:
            if stream is not None:
                for line in stream:
                    tail.append(line)
                    while sum(len(item) for item in tail) > _STDERR_TAIL_BYTES and len(tail) > 1:
                        tail.pop(0)
        except (OSError, ValueError):
            pass

    threading.Thread(target=drain, name="plaud-mcp-stderr", daemon=True).start()


def _failure_detail(message: str, stderr_tail: list[str]) -> str:
    detail = "".join(stderr_tail).strip()
    return f"{message}：{detail}" if detail else message


def _shutdown(process: subprocess.Popen[str]) -> None:
    """先关 stdin 让 server 自己退出，超时就 kill；绝不留孤儿进程。"""
    if process.poll() is None and process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
