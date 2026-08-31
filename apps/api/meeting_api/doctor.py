"""本机依赖、模型与纪要 CLI 的就绪探测。"""

from __future__ import annotations

import shutil
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from meeting_api.config import Settings
from meeting_api.db import make_engine

router = APIRouter(prefix="/api")

_GIB = 1024**3
_REPO_ROOT = Path(__file__).resolve().parents[3]


class ModelsStatus(BaseModel):
    asr: bool
    segmentation: bool
    embedding: bool


class CliStatus(BaseModel):
    claude_available: bool
    codex_available: bool


class MigrationsStatus(BaseModel):
    current_revision: str | None
    head_revision: str
    pending: bool
    warning: str | None


class DoctorResponse(BaseModel):
    ffmpeg: bool
    models: ModelsStatus
    cli: CliStatus
    disk_gb_free: float
    transcription_ready: bool
    minutes_ready: bool
    migrations: MigrationsStatus


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


def probe_migrations(engine: Engine) -> MigrationsStatus:
    """只读比较数据库当前 revision 与仓库 Alembic head。"""
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(_REPO_ROOT / "apps/api/migrations")
    )
    head_revision = ScriptDirectory.from_config(config).get_current_head()
    if head_revision is None:
        raise RuntimeError("Alembic 未找到 head revision")
    with engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    pending = current_revision != head_revision
    current_label = f"当前 {current_revision}" if current_revision else "当前未初始化"
    warning = (
        f"数据库迁移未应用（{current_label}，最新 {head_revision}），请运行 make migrate。"
        if pending
        else None
    )
    return MigrationsStatus(
        current_revision=current_revision,
        head_revision=head_revision,
        pending=pending,
        warning=warning,
    )


def build_doctor_report(
    settings: Settings, engine: Engine | None = None
) -> DoctorResponse:
    owned_engine = engine is None
    engine = engine or make_engine(settings.resolved_database_url())
    models = probe_models(settings.data_dir / "models")
    cli = probe_cli_status()
    ffmpeg = shutil.which("ffmpeg") is not None
    disk_gb_free = round(shutil.disk_usage(settings.data_dir).free / _GIB, 2)
    transcription_ready = ffmpeg and all(
        (models.asr, models.segmentation, models.embedding)
    )
    minutes_ready = cli.claude_available or cli.codex_available
    try:
        migrations = probe_migrations(engine)
        return DoctorResponse(
            ffmpeg=ffmpeg,
            models=models,
            cli=cli,
            disk_gb_free=disk_gb_free,
            transcription_ready=transcription_ready,
            minutes_ready=minutes_ready,
            migrations=migrations,
        )
    finally:
        if owned_engine:
            engine.dispose()


@router.get("/doctor", response_model=DoctorResponse)
def get_doctor(request: Request) -> DoctorResponse:
    return build_doctor_report(request.app.state.settings, request.app.state.engine)
