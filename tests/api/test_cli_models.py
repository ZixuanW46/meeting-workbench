"""清洗与纪要分别钉死模型；清洗块上限与超时可配。

helper 内联（tests/ 下不能跨文件 import）。
"""

from __future__ import annotations

from pathlib import Path

from meeting_api.config import Settings
from meeting_api.minutes.adapter import (
    AutoMinutesAdapter,
    ClaudeCliAdapter,
    CodexCliAdapter,
    resolve_minutes_adapter,
)
from meeting_api.worker import Worker


def _write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_claude_command_pins_model_only_when_configured():
    plain = ClaudeCliAdapter().build_command()
    assert "--model" not in plain

    pinned = ClaudeCliAdapter(model="fable").build_command()
    assert pinned[pinned.index("--model") + 1] == "fable"
    # 钉模型不能动安全开关。
    assert "--strict-mcp-config" in pinned and "--bare" not in pinned


def test_codex_command_pins_model_and_reasoning_effort():
    plain = CodexCliAdapter().build_command()
    assert "-m" not in plain and not any("model_reasoning_effort" in arg for arg in plain)

    pinned = CodexCliAdapter(model="gpt-5.6-luna", reasoning_effort="medium").build_command()
    assert pinned[pinned.index("-m") + 1] == "gpt-5.6-luna"
    assert pinned[pinned.index("-c") + 1] == "model_reasoning_effort=medium"
    # 提示词仍从 stdin 读（"-" 必须是最后一个参数），沙箱仍只读。
    assert pinned[-1] == "-"
    assert pinned[pinned.index("--sandbox") + 1] == "read-only"


def test_claude_adapter_passes_model_flag_to_real_process(tmp_path):
    # 假 claude 把收到的参数原样吐回来，验证 --model 真的进了 argv。
    fake = _write_script(
        tmp_path / "claude",
        'printf \'{"result": "args:%s"}\' "$*"',
    )
    adapter = ClaudeCliAdapter(executable=str(fake), model="opus")

    assert "--model opus" in adapter.generate("逐字稿")


def test_codex_adapter_passes_model_and_effort_to_real_process(tmp_path):
    fake = _write_script(tmp_path / "codex", 'printf \'args:%s\' "$*"')
    adapter = CodexCliAdapter(
        executable=str(fake), model="gpt-5.6-sol", reasoning_effort="medium"
    )

    output = adapter.generate("逐字稿")
    assert "-m gpt-5.6-sol" in output
    assert "-c model_reasoning_effort=medium" in output


def test_auto_adapter_hands_role_models_to_whichever_cli_it_resolves(tmp_path):
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "")
    codex_only = tmp_path / "codex-only"
    codex_only.mkdir()
    _write_script(codex_only / "codex", "")

    auto = AutoMinutesAdapter(
        path=str(both),
        claude_model="fable",
        codex_model="gpt-5.6-sol",
        codex_reasoning_effort="medium",
    )
    resolved = auto.resolve()
    assert isinstance(resolved, ClaudeCliAdapter)
    assert resolved.model == "fable"

    auto = AutoMinutesAdapter(
        path=str(codex_only),
        claude_model="fable",
        codex_model="gpt-5.6-sol",
        codex_reasoning_effort="medium",
    )
    resolved = auto.resolve()
    assert isinstance(resolved, CodexCliAdapter)
    assert resolved.model == "gpt-5.6-sol"
    assert resolved.reasoning_effort == "medium"


def test_resolve_minutes_adapter_forwards_models_for_each_backend():
    claude = resolve_minutes_adapter("claude", timeout_seconds=1, claude_model="opus")
    assert isinstance(claude, ClaudeCliAdapter) and claude.model == "opus"

    codex = resolve_minutes_adapter(
        "codex", timeout_seconds=1, codex_model="gpt-5.6-luna", codex_reasoning_effort="low"
    )
    assert isinstance(codex, CodexCliAdapter)
    assert codex.model == "gpt-5.6-luna" and codex.reasoning_effort == "low"

    auto = resolve_minutes_adapter("auto", timeout_seconds=1, claude_model="fable")
    assert isinstance(auto, AutoMinutesAdapter) and auto.claude_model == "fable"


def test_settings_defaults_pin_cheaper_model_for_cleaning_and_larger_chunks():
    settings = Settings()

    # 清洗是照原样改写，不需要最强模型；纪要要抓脉络与决议，用最强的。
    assert settings.cleaning_model_claude == "opus"
    assert settings.minutes_model_claude == "fable"
    assert settings.cleaning_model_codex == "gpt-5.6-luna"
    assert settings.minutes_model_codex == "gpt-5.6-sol"
    assert settings.cleaning_codex_reasoning_effort == "medium"
    assert settings.minutes_codex_reasoning_effort == "medium"
    # 上下文窗口早已不是瓶颈：块大一倍，超时跟着放宽。
    assert settings.cleaning_chunk_chars == 6000
    assert settings.cleaning_timeout_seconds >= 480


def test_worker_builds_role_specific_adapters_from_settings(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/test.sqlite3",
        minutes_backend="claude",
        asr_backend="fake",
        diarization_backend="fake",
        embedding_backend="fake",
        cleaning_model_claude="sonnet",
        minutes_model_claude="fable",
        cleaning_timeout_seconds=42,
    )
    worker = Worker(session_factory=lambda: None, settings=settings)

    assert isinstance(worker.cleaner_adapter, ClaudeCliAdapter)
    assert worker.cleaner_adapter.model == "sonnet"
    assert worker.cleaner_adapter.timeout_seconds == 42
    assert isinstance(worker.minutes_adapter, ClaudeCliAdapter)
    assert worker.minutes_adapter.model == "fable"
