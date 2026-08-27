"""本机依赖、模型与纪要 CLI 的就绪探测。"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from meeting_api.config import Settings

router = APIRouter(prefix="/api")

_GIB = 1024**3


class ModelsStatus(BaseModel):
    asr: bool
    segmentation: bool
    embedding: bool


class CliStatus(BaseModel):
    claude_available: bool
    codex_available: bool


class DoctorResponse(BaseModel):
    ffmpeg: bool
    models: ModelsStatus
    cli: CliStatus
    disk_gb_free: float
    transcription_ready: bool
    minutes_ready: bool


def cli_available(name: str) -> bool:
    """只探测 CLI 是否在 PATH，不再探测登录态。

    claude /doctor、codex whoami 这类登录检查需要交互终端，在 launchd
    与脚本环境必然报 "stdin is not a terminal"，曾让横幅在纪要实际可用时
    仍长期误报未就绪。登录问题交给生成环节用真实调用暴露：失败会停在
    PARTIAL_READY 并附具体错误，可在界面重试。"""
    return shutil.which(name) is not None


def probe_models(models_dir: Path) -> ModelsStatus:
    return ModelsStatus(
        asr=(models_dir / "qwen3-asr-mlx" / "config.json").is_file(),
        segmentation=(models_dir / "sherpa-onnx" / "segmentation.onnx").is_file(),
        embedding=(models_dir / "sherpa-onnx" / "embedding.onnx").is_file(),
    )


def probe_cli_status() -> CliStatus:
    return CliStatus(
        claude_available=cli_available("claude"),
        codex_available=cli_available("codex"),
    )


def build_doctor_report(settings: Settings) -> DoctorResponse:
    models = probe_models(settings.data_dir / "models")
    cli = probe_cli_status()
    ffmpeg = shutil.which("ffmpeg") is not None
    disk_gb_free = round(shutil.disk_usage(settings.data_dir).free / _GIB, 2)
    transcription_ready = ffmpeg and all(
        (models.asr, models.segmentation, models.embedding)
    )
    minutes_ready = cli.claude_available or cli.codex_available
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
