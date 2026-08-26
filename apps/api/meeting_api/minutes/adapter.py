"""本机纪要 CLI 适配器；只把逐字稿文本交给子进程。"""

from __future__ import annotations

import json
import subprocess
from typing import Protocol


class MinutesCliError(RuntimeError):
    """纪要 CLI 不可用、超时或执行失败。"""


class MinutesAdapter(Protocol):
    def generate(self, transcript: str) -> str: ...


class FakeMinutesAdapter:
    """测试默认适配器，不启动任何外部进程。"""

    def __init__(
        self,
        markdown: str = "# 会议纪要\n\n- fake 纪要内容",
        error: MinutesCliError | None = None,
    ) -> None:
        self.markdown = markdown
        self.error = error

    def generate(self, transcript: str) -> str:
        if self.error is not None:
            raise self.error
        if not transcript.strip():
            raise MinutesCliError("逐字稿为空")
        return self.markdown


class ClaudeCliAdapter:
    def __init__(self, *, executable: str = "claude", timeout_seconds: float = 120) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def build_command(self, transcript: str) -> list[str]:
        return [
            self.executable,
            "-p",
            transcript,
            "--output-format",
            "json",
            "--disallowedTools",
            "Read,Write,Edit,Glob,Grep,Bash",
        ]

    def generate(self, transcript: str) -> str:
        output = _run_cli(self.build_command(transcript), self.timeout_seconds)
        try:
            payload = json.loads(output)
            result = payload["result"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MinutesCliError("Claude CLI 返回了无效 JSON") from exc
        if not isinstance(result, str) or not result.strip():
            raise MinutesCliError("Claude CLI 未返回纪要文本")
        return result


class CodexCliAdapter:
    def __init__(self, *, executable: str = "codex", timeout_seconds: float = 120) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def build_command(self, transcript: str) -> list[str]:
        return [
            self.executable,
            "exec",
            transcript,
            "--sandbox",
            "read-only",
        ]

    def generate(self, transcript: str) -> str:
        output = _run_cli(self.build_command(transcript), self.timeout_seconds)
        if not output.strip():
            raise MinutesCliError("Codex CLI 未返回纪要文本")
        return output


def _run_cli(command: list[str], timeout_seconds: float) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MinutesCliError("纪要 CLI 执行超时") from exc
    except OSError as exc:
        raise MinutesCliError(f"纪要 CLI 无法启动: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "无错误输出"
        raise MinutesCliError(f"纪要 CLI 执行失败（{completed.returncode}）: {detail}")
    return completed.stdout
