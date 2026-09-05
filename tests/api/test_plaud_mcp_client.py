"""Plaud MCP stdio 客户端：握手、噪声容错、超时 kill、命令缺失。

测试用一个 Python 写的假 MCP server 顶替 `plaud-mcp`，全程不联网、不碰 ~/.plaud。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from meeting_api.plaud.errors import PlaudError, PlaudTimeoutError, PlaudUnavailableError
from meeting_api.plaud.mcp_client import McpStdioClient

# 假 server：按 PLAUD_TEST_MODE 切换行为，收到的请求逐行落到 PLAUD_TEST_LOG。
# 变量必须带 PLAUD_ 前缀，否则按设计不会透传给子进程。
FAKE_SERVER = '''
import json
import os
import sys
import time

mode = os.environ.get("PLAUD_TEST_MODE", "ok")
log_path = os.environ.get("PLAUD_TEST_LOG")
pid_path = os.environ.get("PLAUD_TEST_PIDFILE")
if pid_path:
    with open(pid_path, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()


def record(message):
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(message) + "\\n")


if mode == "hang":
    while True:
        time.sleep(3600)

if mode == "exit":
    sys.stderr.write("plaud-mcp 崩了\\n")
    sys.exit(1)

# pino 日志走 stderr，正常情况下应被完全忽略。
sys.stderr.write('{"level":30,"msg":"plaud mcp started"}\\n')
sys.stderr.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    record(message)
    method = message.get("method")
    if method == "initialize":
        # 夹一行不是 JSON 的噪声，客户端必须跳过。
        sys.stdout.write("plaud-mcp ready\\n")
        sys.stdout.flush()
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2024-11-05"}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/call":
        # 一条无 id 的通知 + 一条 id 不匹配的响应，都必须被跳过。
        send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}})
        other = {"content": [{"type": "text", "text": "别的响应"}]}
        send({"jsonrpc": "2.0", "id": 4242, "result": other})
        if mode == "tool_error":
            send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "content": [{"type": "text", "text": "Failed: API error: 401 Unauthorized"}],
                    "isError": True,
                },
            })
        else:
            payload = json.dumps({"type": "list", "data": [], "tool": message["params"]["name"]})
            send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"content": [{"type": "text", "text": payload}]},
            })
'''


def _client(tmp_path: Path, **kwargs) -> McpStdioClient:
    script = tmp_path / "fake_plaud_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return McpStdioClient([sys.executable, str(script)], **kwargs)


def test_call_tool_completes_handshake_and_skips_noise(tmp_path, monkeypatch):
    log = tmp_path / "requests.jsonl"
    monkeypatch.setenv("PLAUD_TEST_LOG", str(log))

    result = _client(tmp_path).call_tool("list_files", {"page": 1})

    assert result.is_error is False
    assert json.loads(result.text)["tool"] == "list_files"

    requests = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [message.get("method") for message in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert requests[0]["params"]["protocolVersion"] == "2024-11-05"
    assert "id" not in requests[1]
    assert requests[2]["params"] == {"name": "list_files", "arguments": {"page": 1}}


def test_call_tool_surfaces_is_error_without_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUD_TEST_MODE", "tool_error")

    result = _client(tmp_path).call_tool("get_current_user", {})

    assert result.is_error is True
    assert "401" in result.text


def test_timeout_raises_and_kills_the_child_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUD_TEST_MODE", "hang")
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("PLAUD_TEST_PIDFILE", str(pid_file))

    started = time.monotonic()
    with pytest.raises(PlaudTimeoutError):
        _client(tmp_path, timeout_seconds=0.5).call_tool("list_files", {})

    assert time.monotonic() - started < 10
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_server_exit_before_handshake_raises_plaud_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAUD_TEST_MODE", "exit")

    with pytest.raises(PlaudError) as excinfo:
        _client(tmp_path).call_tool("list_files", {})

    assert not isinstance(excinfo.value, PlaudTimeoutError)


def test_missing_command_raises_unavailable():
    client = McpStdioClient(["mw-definitely-missing-plaud-mcp"])

    with pytest.raises(PlaudUnavailableError):
        client.call_tool("list_files", {})


def test_child_env_is_limited_to_path_home_and_prefixed_vars(tmp_path, monkeypatch):
    # 子进程只该看到 PATH / HOME / MW_ / PLAUD_ 前缀变量，别的环境变量一律不透传。
    monkeypatch.setenv("MW_PLAUD_MARKER", "keep")
    monkeypatch.setenv("PLAUD_API_BASE", "keep")
    monkeypatch.setenv("SOME_SECRET_TOKEN", "drop")
    dump = tmp_path / "env.json"
    script = tmp_path / "dump_env.py"
    script.write_text(
        "import json, os, sys\n"
        f"open({str(dump)!r}, 'w').write(json.dumps(dict(os.environ)))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )

    with pytest.raises(PlaudError):
        McpStdioClient([sys.executable, str(script)]).call_tool("list_files", {})

    child_env = json.loads(dump.read_text(encoding="utf-8"))
    assert child_env.get("MW_PLAUD_MARKER") == "keep"
    assert child_env.get("PLAUD_API_BASE") == "keep"
    assert "SOME_SECRET_TOKEN" not in child_env
    assert "PATH" in child_env and "HOME" in child_env
