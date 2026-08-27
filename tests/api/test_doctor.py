from __future__ import annotations

import subprocess
from types import SimpleNamespace

from meeting_api.doctor import probe_cli


def test_doctor_reports_dependencies_models_cli_login_and_readiness(
    client, monkeypatch
):
    models_dir = client.app.state.settings.data_dir / "models"
    (models_dir / "qwen3-asr-mlx").mkdir(parents=True)
    (models_dir / "qwen3-asr-mlx" / "config.json").write_text(
        "{}", encoding="utf-8"
    )
    (models_dir / "sherpa-onnx").mkdir()
    (models_dir / "sherpa-onnx" / "segmentation.onnx").touch()
    (models_dir / "sherpa-onnx" / "embedding.onnx").touch()

    executables = {
        "ffmpeg": "/usr/local/bin/ffmpeg",
        "claude": "/usr/local/bin/claude",
        "codex": "/usr/local/bin/codex",
    }
    monkeypatch.setattr(
        "meeting_api.doctor.shutil.which", lambda name: executables.get(name)
    )
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] > 0
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("meeting_api.doctor.subprocess.run", fake_run)
    monkeypatch.setattr(
        "meeting_api.doctor.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=12.5 * 1024**3),
    )

    response = client.get("/api/doctor")

    assert response.status_code == 200
    assert response.json() == {
        "ffmpeg": True,
        "models": {"asr": True, "segmentation": True, "embedding": True},
        "cli": {
            "claude_available": True,
            "claude_logged_in": True,
            "codex_available": True,
            "codex_logged_in": True,
        },
        "disk_gb_free": 12.5,
        "transcription_ready": True,
        "minutes_ready": True,
    }
    assert commands == [
        ["/usr/local/bin/claude", "/doctor"],
        ["/usr/local/bin/codex", "whoami"],
    ]
    assert "--bare" not in str(commands)


def test_doctor_reports_partial_state_and_minutes_not_ready(client, monkeypatch):
    models_dir = client.app.state.settings.data_dir / "models"
    (models_dir / "qwen3-asr-mlx").mkdir(parents=True)
    (models_dir / "qwen3-asr-mlx" / "config.json").touch()

    monkeypatch.setattr(
        "meeting_api.doctor.shutil.which",
        lambda name: "/bin/claude" if name == "claude" else None,
    )
    monkeypatch.setattr(
        "meeting_api.doctor.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "未登录"),
    )

    payload = client.get("/api/doctor").json()

    assert payload["ffmpeg"] is False
    assert payload["models"] == {
        "asr": True,
        "segmentation": False,
        "embedding": False,
    }
    assert payload["cli"] == {
        "claude_available": True,
        "claude_logged_in": False,
        "codex_available": False,
        "codex_logged_in": False,
    }
    assert payload["transcription_ready"] is False
    assert payload["minutes_ready"] is False
    assert payload["disk_gb_free"] >= 0


def test_cli_probe_skips_login_command_when_executable_is_missing(monkeypatch):
    monkeypatch.setattr("meeting_api.doctor.shutil.which", lambda _name: None)

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("which 找不到时不应执行登录探测")

    monkeypatch.setattr("meeting_api.doctor.subprocess.run", forbidden_run)

    assert probe_cli("claude", ["/doctor"]) == (False, False)


def test_minutes_cli_settings_reuses_doctor_probe(client, monkeypatch):
    calls: list[tuple[str, list[str]]] = []

    def fake_probe(name: str, login_args: list[str]):
        calls.append((name, login_args))
        return (name == "claude", False)

    monkeypatch.setattr("meeting_api.routes.settings.probe_cli", fake_probe)

    response = client.get("/api/settings/minutes-cli")

    assert response.status_code == 200
    assert response.json()["claude_available"] is True
    assert response.json()["codex_available"] is False
    assert calls == [("claude", ["/doctor"]), ("codex", ["whoami"])]
