"""本机依赖、模型与纪要 CLI 的就绪探测。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from meeting_api.config import Settings

router = APIRouter(prefix="/api")

_GIB = 1024**3
_CLI_TIMEOUT_SECONDS = 10.0


class ModelsStatus(BaseModel):
    asr: bool
    segmentation: bool
    embedding: bool


class CliStatus(BaseModel):
    claude_available: bool
    claude_logged_in: bool
    codex_available: bool
    codex_logged_in: bool


class DoctorResponse(BaseModel):
    ffmpeg: bool
    models: ModelsStatus
    cli: CliStatus
    disk_gb_free: float
    transcription_ready: bool
    minutes_ready: bool


def probe_cli(name: str, login_args: list[str]) -> tuple[bool, bool]:
    """返回 CLI 是否在 PATH、官方登录检查是否成功。"""
    executable = shutil.which(name)
    if executable is None:
        return False, False
    try:
        completed = subprocess.run(
            [executable, *login_args],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True, False
    return True, completed.returncode == 0


def probe_models(models_dir: Path) -> ModelsStatus:
    return ModelsStatus(
        asr=(models_dir / "qwen3-asr-mlx" / "config.json").is_file(),
        segmentation=(models_dir / "sherpa-onnx" / "segmentation.onnx").is_file(),
        embedding=(models_dir / "sherpa-onnx" / "embedding.onnx").is_file(),
    )


def probe_cli_status() -> CliStatus:
    claude_available, claude_logged_in = probe_cli("claude", ["/doctor"])
    codex_available, codex_logged_in = probe_cli("codex", ["whoami"])
    return CliStatus(
        claude_available=claude_available,
        claude_logged_in=claude_logged_in,
        codex_available=codex_available,
        codex_logged_in=codex_logged_in,
    )


def build_doctor_report(settings: Settings) -> DoctorResponse:
    models = probe_models(settings.data_dir / "models")
    cli = probe_cli_status()
    ffmpeg = shutil.which("ffmpeg") is not None
    disk_gb_free = round(shutil.disk_usage(settings.data_dir).free / _GIB, 2)
    transcription_ready = ffmpeg and all(
        (models.asr, models.segmentation, models.embedding)
    )
    minutes_ready = (
        cli.claude_available
        and cli.claude_logged_in
        or cli.codex_available
        and cli.codex_logged_in
    )
    return DoctorResponse(
        ffmpeg=ffmpeg,
        models=models,
        cli=cli,
        disk_gb_free=disk_gb_free,
        transcription_ready=transcription_ready,
        minutes_ready=minutes_ready,
    )


@router.get("/doctor", response_model=DoctorResponse)
def get_doctor(request: Request) -> DoctorResponse:
    return build_doctor_report(request.app.state.settings)
