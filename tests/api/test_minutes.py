from __future__ import annotations

from pathlib import Path

import pytest

from meeting_api.config import Settings
from meeting_api.minutes.adapter import (
    AutoMinutesAdapter,
    ClaudeCliAdapter,
    CodexCliAdapter,
    FakeMinutesAdapter,
    MinutesCliError,
    resolve_minutes_adapter,
)
from meeting_api.worker import Worker

NOTE = "纪要文本会发送到 Claude/OpenAI 云端，音频不会上传"


def _prepare_generating_minutes(client, *, keep_unknown: bool = False) -> str:
    created = client.post(
        "/api/meetings",
        json={"title": "纪要生成测试", "expected_speakers": 2},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )

    second_decision = (
        {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"}
        if keep_unknown
        else {
            "cluster_id": "S2",
            "kind": "NEW_PERSON",
            "display_name": "李雷",
        }
    )
    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": "王芳",
                },
                second_decision,
            ]
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "GENERATING_MINUTES"
    return meeting_id


def test_fake_adapter_success_makes_meeting_ready_and_exposes_minutes(client):
    meeting_id = _prepare_generating_minutes(client)

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "READY"
    response = client.get(f"/api/meetings/{meeting_id}/minutes")
    assert response.status_code == 200
    assert response.json()["markdown"].startswith("# 会议纪要")
    assert response.json()["note"] == NOTE

    transcript_path = (
        client.app.state.settings.data_dir
        / "meetings"
        / meeting_id
        / "transcript.txt"
    )
    assert transcript_path.is_file()
    assert "假转写第一段" in transcript_path.read_text(encoding="utf-8")
    assert str(client.app.state.settings.data_dir) not in response.text


def test_unconfirmed_speakers_add_warning_at_start_of_minutes(client):
    meeting_id = _prepare_generating_minutes(client, keep_unknown=True)

    assert client.app.state.worker.process_next() == meeting_id

    response = client.get(f"/api/meetings/{meeting_id}/minutes")
    assert response.status_code == 200
    assert response.json()["markdown"].startswith("含未确认说话人")


def test_cli_error_makes_partial_ready_then_retry_can_succeed(client):
    meeting_id = _prepare_generating_minutes(client)
    client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
        error=MinutesCliError("模拟配额不足")
    )

    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "PARTIAL_READY"

    retried = client.post(f"/api/meetings/{meeting_id}/minutes/retry")
    assert retried.status_code == 200
    assert retried.json()["state"] == "GENERATING_MINUTES"

    client.app.state.worker.minutes_adapter = FakeMinutesAdapter()
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    assert client.get(f"/api/meetings/{meeting_id}/minutes").status_code == 200


def test_claude_command_uses_print_json_and_disables_file_tools():
    command = ClaudeCliAdapter().build_command()

    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--output-format") + 1] == "json"
    disabled = command[command.index("--disallowedTools") + 1]
    assert {"Read", "Write", "Edit", "Glob", "Grep", "Bash"} <= set(
        disabled.split(",")
    )
    assert "--bare" not in command


def test_codex_command_uses_exec_without_bare():
    command = CodexCliAdapter().build_command()

    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    # 提示词经 stdin（"-"）传入，不进 argv。
    assert command[-1] == "-"
    assert "--bare" not in command


def _write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_claude_adapter_sends_transcript_via_stdin_not_argv(tmp_path):
    # 逐字稿走 stdin，避免长会议撞 argv 单参数上限（ARG_MAX）。
    fake_claude = _write_script(
        tmp_path / "claude",
        'input=$(cat)\nprintf \'{"result": "收到:%s"}\' "$input"',
    )

    adapter = ClaudeCliAdapter(executable=str(fake_claude))

    assert "逐字稿正文" not in adapter.build_command()
    assert adapter.generate("逐字稿正文") == "收到:逐字稿正文"


def test_codex_adapter_sends_transcript_via_stdin_not_argv(tmp_path):
    fake_codex = _write_script(tmp_path / "codex", "cat")

    adapter = CodexCliAdapter(executable=str(fake_codex))

    assert "逐字稿正文" not in adapter.build_command()
    assert adapter.generate("逐字稿正文") == "逐字稿正文"


def test_nonzero_exit_and_timeout_raise_minutes_cli_error(tmp_path):
    failing = _write_script(tmp_path / "claude", "echo '配额不足' >&2\nexit 3")
    hanging = _write_script(tmp_path / "codex", "exec sleep 30")

    with pytest.raises(MinutesCliError, match="配额不足"):
        ClaudeCliAdapter(executable=str(failing)).generate("逐字稿正文")
    with pytest.raises(MinutesCliError, match="超时"):
        CodexCliAdapter(executable=str(hanging), timeout_seconds=0.2).generate("逐字稿正文")


def test_auto_adapter_prefers_claude_then_codex_then_fails(tmp_path):
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "")
    _write_script(both / "codex", "")
    codex_only = tmp_path / "codex-only"
    codex_only.mkdir()
    _write_script(codex_only / "codex", "")
    empty = tmp_path / "empty"
    empty.mkdir()

    assert isinstance(AutoMinutesAdapter(path=str(both)).resolve(), ClaudeCliAdapter)
    assert isinstance(AutoMinutesAdapter(path=str(codex_only)).resolve(), CodexCliAdapter)
    with pytest.raises(MinutesCliError, match="未找到"):
        AutoMinutesAdapter(path=str(empty)).resolve()


def test_worker_default_adapter_follows_settings_backend(tmp_path):
    def make_worker(backend: str) -> Worker:
        return Worker(
            session_factory=None,
            settings=Settings(data_dir=tmp_path, minutes_backend=backend),
        )

    # 真实运行默认 auto：按本机 CLI 选择，绝不默默产出 fake 纪要。
    assert isinstance(make_worker("auto").minutes_adapter, AutoMinutesAdapter)
    assert isinstance(make_worker("fake").minutes_adapter, FakeMinutesAdapter)
    assert isinstance(resolve_minutes_adapter("claude"), ClaudeCliAdapter)
    assert isinstance(resolve_minutes_adapter("codex"), CodexCliAdapter)


def test_auto_without_any_cli_makes_meeting_partial_ready(client, tmp_path):
    meeting_id = _prepare_generating_minutes(client)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    client.app.state.worker.minutes_adapter = AutoMinutesAdapter(path=str(empty))

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    assert detail["state"] == "PARTIAL_READY"


def test_minutes_cli_settings_probes_executables_on_path(client, tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    response = client.get("/api/settings/minutes-cli")

    assert response.status_code == 200
    assert response.json() == {
        "claude_available": True,
        "codex_available": False,
        "note": NOTE,
    }
    assert not any(Path(fake_bin).as_posix() in str(value) for value in response.json().values())
