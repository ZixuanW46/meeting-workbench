"""本机纪要 CLI 适配器；只把逐字稿文本交给子进程。

逐字稿走 stdin 而不是 argv：长会议的逐字稿会超过单参数上限
（Linux MAX_ARG_STRLEN 约 128KB），argv 传参会直接 E2BIG。

逐字稿是不可信输入（会上任何人说的话都会进提示词），子进程必须收口：
- 在空的临时目录里跑，不继承仓库根目录，否则 claude 会读进 CLAUDE.md 与
  .claude/ 设置、codex 会把 AGENTS.md 当指令；
- 关掉全部内置工具与 MCP，纪要生成只需要「读 stdin、写 stdout」；
- 不把会话持久化到 CLI 自己的目录，逐字稿只留在 data/。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from typing import Protocol


class MinutesCliError(RuntimeError):
    """纪要 CLI 不可用、超时或执行失败。"""


DEFAULT_TIMEOUT_SECONDS = 120.0


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
    def __init__(
        self, *, executable: str = "claude", timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def build_command(self) -> list[str]:
        # -p 无位置参数时从 stdin 读提示词；禁止 --bare。
        # --tools "" 关掉全部内置工具，--disallowedTools 再兜一层；
        # --strict-mcp-config 且不给 --mcp-config = 不加载任何 MCP 服务器。
        return [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--disallowedTools",
            "Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch,Agent,NotebookEdit",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]

    def generate(self, transcript: str) -> str:
        output = _run_cli(self.build_command(), self.timeout_seconds, input_text=transcript)
        try:
            payload = json.loads(output)
            result = payload["result"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MinutesCliError("Claude CLI 返回了无效 JSON") from exc
        if payload.get("is_error"):
            raise MinutesCliError(f"Claude CLI 报告错误: {result}")
        if not isinstance(result, str) or not result.strip():
            raise MinutesCliError("Claude CLI 未返回纪要文本")
        return result


class CodexCliAdapter:
    def __init__(
        self, *, executable: str = "codex", timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def build_command(self) -> list[str]:
        # exec 的提示词参数为 "-" 时从 stdin 读；只读沙箱，禁止 --bare。
        # 子进程跑在空临时目录（见 _run_cli），不是 git 仓库，需跳过仓库检查；
        # --ephemeral 不落会话文件。
        return [
            self.executable,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "-",
        ]

    def generate(self, transcript: str) -> str:
        output = _run_cli(self.build_command(), self.timeout_seconds, input_text=transcript)
        if not output.strip():
            raise MinutesCliError("Codex CLI 未返回纪要文本")
        return output


class AutoMinutesAdapter:
    """真实运行的默认适配器：每次生成时按 PATH 探测本机 CLI。

    优先 claude；claude 执行失败（未登录、配额不足）且本机有 codex 时
    换通道再试一次；全部失败合并原因抛 MinutesCliError，让会议走
    PARTIAL_READY，绝不默默产出 fake 纪要。逐次探测保证用户装好 CLI
    后重试即可成功，无需重启服务。
    """

    def __init__(
        self,
        *,
        path: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # path 仅供测试注入假 PATH；None 时用进程环境变量。
        self.path = path
        self.timeout_seconds = timeout_seconds

    def _claude(self, executable: str) -> ClaudeCliAdapter:
        return ClaudeCliAdapter(executable=executable, timeout_seconds=self.timeout_seconds)

    def _codex(self, executable: str) -> CodexCliAdapter:
        return CodexCliAdapter(executable=executable, timeout_seconds=self.timeout_seconds)

    def resolve(self) -> ClaudeCliAdapter | CodexCliAdapter:
        claude = shutil.which("claude", path=self.path)
        if claude is not None:
            return self._claude(claude)
        codex = shutil.which("codex", path=self.path)
        if codex is not None:
            return self._codex(codex)
        raise MinutesCliError("本机未找到 claude 或 codex CLI，无法生成纪要")

    def generate(self, transcript: str) -> str:
        claude = shutil.which("claude", path=self.path)
        codex = shutil.which("codex", path=self.path)
        if claude is None and codex is None:
            raise MinutesCliError("本机未找到 claude 或 codex CLI，无法生成纪要")
        if claude is None:
            return self._codex(codex).generate(transcript)
        try:
            return self._claude(claude).generate(transcript)
        except MinutesCliError as claude_error:
            if codex is None:
                raise
            # claude 在 PATH 但执行失败（最常见是未登录）：换 codex 通道重试。
            try:
                return self._codex(codex).generate(transcript)
            except MinutesCliError as codex_error:
                raise MinutesCliError(
                    f"claude 失败：{claude_error}；codex 失败：{codex_error}"
                ) from codex_error


def resolve_minutes_adapter(
    backend: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> MinutesAdapter:
    """按配置选择纪要适配器（MW_MINUTES_BACKEND）。"""
    if backend == "auto":
        return AutoMinutesAdapter(timeout_seconds=timeout_seconds)
    if backend == "claude":
        return ClaudeCliAdapter(timeout_seconds=timeout_seconds)
    if backend == "codex":
        return CodexCliAdapter(timeout_seconds=timeout_seconds)
    if backend == "fake":
        return FakeMinutesAdapter()
    raise ValueError(f"未知的纪要后端: {backend}")


def _run_cli(command: list[str], timeout_seconds: float, *, input_text: str) -> str:
    # 每次调用一个空的临时目录做 cwd：子进程看不到仓库文件，跑完即清理。
    with tempfile.TemporaryDirectory(prefix="mw-cli-") as scratch:
        try:
            completed = subprocess.run(
                command,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                cwd=scratch,
            )
        except subprocess.TimeoutExpired as exc:
            raise MinutesCliError("纪要 CLI 执行超时") from exc
        except OSError as exc:
            raise MinutesCliError(f"纪要 CLI 无法启动: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "无错误输出"
        raise MinutesCliError(f"纪要 CLI 执行失败（{completed.returncode}）: {detail}")
    return completed.stdout
