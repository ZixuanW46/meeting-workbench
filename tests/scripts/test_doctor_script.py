from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "scripts" / "doctor.sh"


def test_doctor_script_passes_bash_syntax_check():
    assert DOCTOR.is_file()
    result = subprocess.run(
        ["bash", "-n", str(DOCTOR)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_doctor_script_dry_run_has_human_readable_checks():
    env = os.environ.copy()
    env["DRY"] = "1"

    result = subprocess.run(
        ["bash", str(DOCTOR)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "ffmpeg" in result.stdout
    assert "ASR" in result.stdout
    assert "说话人切分" in result.stdout
    assert "声纹" in result.stdout
    assert "Claude CLI" in result.stdout
    assert "Codex CLI" in result.stdout
    assert "磁盘" in result.stdout
