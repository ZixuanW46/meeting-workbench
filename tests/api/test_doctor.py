from __future__ import annotations

import subprocess
from types import SimpleNamespace

from sqlalchemy import text

from meeting_api.doctor import cli_available


def _forbid_subprocess(monkeypatch):
    """doctor 只做只读探测：登录类子命令需要交互终端，在 launchd/脚本环境
    必然误报未登录，所以就绪检测禁止再启动任何子进程。"""

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("doctor 探测不应启动子进程")

    monkeypatch.setattr(subprocess, "run", forbidden_run)


def test_doctor_reports_dependencies_models_cli_and_readiness(client, monkeypatch):
    models_dir = client.app.state.settings.data_dir / "models"
    (models_dir / "qwen3-asr-mlx").mkdir(parents=True)
    (models_dir / "qwen3-asr-mlx" / "config.json").write_text("{}", encoding="utf-8")
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
    _forbid_subprocess(monkeypatch)
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
            "codex_available": True,
        },
        "disk_gb_free": 12.5,
        "transcription_ready": True,
        "minutes_ready": True,
        "migrations": {
            "current_revision": None,
            "head_revision": "0013",
            "pending": True,
            "warning": "数据库迁移未应用（当前未初始化，最新 0013），请运行 make migrate。",
        },
    }


def test_doctor_warns_when_database_revision_is_behind_head(client, monkeypatch):
    with client.app.state.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0010')"))
    monkeypatch.setattr("meeting_api.doctor.shutil.which", lambda _name: None)

    payload = client.get("/api/doctor").json()

    assert payload["migrations"] == {
        "current_revision": "0010",
        "head_revision": "0013",
        "pending": True,
        "warning": "数据库迁移未应用（当前 0010，最新 0013），请运行 make migrate。",
    }


def test_doctor_reports_no_migration_warning_at_head(client, monkeypatch):
    with client.app.state.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0013')"))
    monkeypatch.setattr("meeting_api.doctor.shutil.which", lambda _name: None)

    migrations = client.get("/api/doctor").json()["migrations"]

    assert migrations == {
        "current_revision": "0013",
        "head_revision": "0013",
        "pending": False,
        "warning": None,
    }


def test_doctor_minutes_ready_with_only_codex_present(client, monkeypatch):
    # 有一个 CLI 在 PATH 即视为纪要可用；登录问题由生成环节用真实调用暴露
    # （PARTIAL_READY + 重试），不在这里猜测。
    monkeypatch.setattr(
        "meeting_api.doctor.shutil.which",
        lambda name: "/opt/homebrew/bin/codex" if name == "codex" else None,
    )
    _forbid_subprocess(monkeypatch)

    payload = client.get("/api/doctor").json()

    assert payload["cli"] == {"claude_available": False, "codex_available": True}
    assert payload["minutes_ready"] is True
    assert payload["ffmpeg"] is False
    assert payload["transcription_ready"] is False


def test_doctor_reports_partial_state_and_minutes_not_ready(client, monkeypatch):
    models_dir = client.app.state.settings.data_dir / "models"
    (models_dir / "qwen3-asr-mlx").mkdir(parents=True)
    (models_dir / "qwen3-asr-mlx" / "config.json").touch()

    monkeypatch.setattr("meeting_api.doctor.shutil.which", lambda _name: None)
    _forbid_subprocess(monkeypatch)

    payload = client.get("/api/doctor").json()

    assert payload["ffmpeg"] is False
    assert payload["models"] == {
        "asr": True,
        "segmentation": False,
        "embedding": False,
    }
    assert payload["cli"] == {"claude_available": False, "codex_available": False}
    assert payload["transcription_ready"] is False
    assert payload["minutes_ready"] is False
    assert payload["disk_gb_free"] >= 0


def test_cli_available_uses_path_lookup_only(monkeypatch):
    looked_up: list[str] = []

    def fake_which(name: str):
        looked_up.append(name)
        return "/usr/local/bin/claude" if name == "claude" else None

    monkeypatch.setattr("meeting_api.doctor.shutil.which", fake_which)
    _forbid_subprocess(monkeypatch)

    assert cli_available("claude") is True
    assert cli_available("codex") is False
    assert looked_up == ["claude", "codex"]


def test_minutes_cli_settings_reuses_doctor_probe(client, monkeypatch):
    calls: list[str] = []

    def fake_available(name: str) -> bool:
        calls.append(name)
        return name == "claude"

    monkeypatch.setattr("meeting_api.routes.settings.cli_available", fake_available)

    response = client.get("/api/settings/minutes-cli")

    assert response.status_code == 200
    assert response.json()["claude_available"] is True
    assert response.json()["codex_available"] is False
    assert calls == ["claude", "codex"]
