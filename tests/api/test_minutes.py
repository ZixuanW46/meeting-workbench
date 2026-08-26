from __future__ import annotations

from pathlib import Path

from meeting_api.minutes.adapter import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    FakeMinutesAdapter,
    MinutesCliError,
)

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
                {"cluster_id": "S1", "kind": "CONFIRM"},
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
    command = ClaudeCliAdapter().build_command("逐字稿正文")

    assert command[:3] == ["claude", "-p", "逐字稿正文"]
    assert command[command.index("--output-format") + 1] == "json"
    disabled = command[command.index("--disallowedTools") + 1]
    assert {"Read", "Write", "Edit", "Glob", "Grep", "Bash"} <= set(
        disabled.split(",")
    )
    assert "--bare" not in command


def test_codex_command_uses_exec_without_bare():
    command = CodexCliAdapter().build_command("逐字稿正文")

    assert command[:3] == ["codex", "exec", "逐字稿正文"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--bare" not in command


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
