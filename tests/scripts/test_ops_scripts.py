from __future__ import annotations

import os
import sqlite3
import subprocess
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from meeting_api.config import Settings
from meeting_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
NEW_SCRIPTS = [
    SCRIPTS / "mac_install.sh",
    SCRIPTS / "backup.sh",
    SCRIPTS / "restore.sh",
    SCRIPTS / "launchd" / "install_launchd.sh",
]


def _run(script: Path, *args: str, env: dict[str, str] | None = None):
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=REPO_ROOT,
        env=command_env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_new_shell_scripts_pass_bash_syntax_check():
    for script in NEW_SCRIPTS:
        assert script.is_file(), f"缺少脚本：{script.relative_to(REPO_ROOT)}"
        result = subprocess.run(
            ["bash", "-n", str(script)], check=False, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


def test_mac_install_dry_run_is_safe_on_linux():
    result = _run(SCRIPTS / "mac_install.sh", env={"DRY_RUN": "1"})

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "Python 3.12" in result.stdout
    assert "Alembic" in result.stdout
    assert "前端" in result.stdout


def test_launchd_files_exist_and_install_dry_run_does_not_execute_launchctl(tmp_path):
    plist = SCRIPTS / "launchd" / "com.will.meeting-workbench.plist"
    assert plist.is_file()
    marker = tmp_path / "launchctl-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 99\n", encoding="utf-8"
    )
    fake_launchctl.chmod(0o755)

    result = _run(
        SCRIPTS / "launchd" / "install_launchd.sh",
        env={"DRY_RUN": "1", "PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert not marker.exists()


def test_backup_excludes_model_weights_and_restore_reaches_healthz(tmp_path):
    data_dir = tmp_path / "source-data"
    backup_root = tmp_path / "backups"
    restore_dir = tmp_path / "restored-data"
    (data_dir / "meetings" / "m1").mkdir(parents=True)
    (data_dir / "models").mkdir()
    database_path = data_dir / "meeting-workbench.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE backup_probe (value TEXT NOT NULL)")
        connection.execute("INSERT INTO backup_probe VALUES ('已恢复')")
    (data_dir / "meetings" / "m1" / "minutes.md").write_text("纪要", encoding="utf-8")
    (data_dir / "models" / "fake.onnx").write_bytes(b"weight")
    (data_dir / "models" / "fake.safetensors").write_bytes(b"weight")

    backup = _run(
        SCRIPTS / "backup.sh",
        env={"MW_DATA_DIR": str(data_dir), "BACKUP_ROOT": str(backup_root)},
    )
    assert backup.returncode == 0, backup.stderr
    archives = list(backup_root.glob("meeting-workbench-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tar:
        members = set(tar.getnames())
    assert "data/meeting-workbench.sqlite3" in members
    assert "data/meetings/m1/minutes.md" in members
    assert not any(name.endswith((".onnx", ".safetensors")) for name in members)
    assert not any(name == "data/models" or name.startswith("data/models/") for name in members)

    restore = _run(SCRIPTS / "restore.sh", str(archives[0]), str(restore_dir))
    assert restore.returncode == 0, restore.stderr
    with sqlite3.connect(restore_dir / "meeting-workbench.sqlite3") as connection:
        assert connection.execute("SELECT value FROM backup_probe").fetchone() == ("已恢复",)
    assert (restore_dir / "meetings" / "m1" / "minutes.md").read_text() == "纪要"
    assert not (restore_dir / "models").exists()

    # 恢复目录可直接作为 MW_DATA_DIR 启动服务。
    settings = Settings(
        data_dir=restore_dir,
        worker_disabled=True,
        minutes_backend="fake",
        static_dir=tmp_path / "missing-dist",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
