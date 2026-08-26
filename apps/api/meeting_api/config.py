"""运行配置。全部走环境变量（前缀 MW_），默认值面向本机开发。

大文件（音频、声纹向量）都放 data_dir 下的本机目录，路径永不暴露给浏览器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MW_")

    data_dir: Path = Path("data")
    database_url: str = ""  # 留空则用 data_dir/meeting-workbench.sqlite3
    worker_disabled: bool = False
    worker_poll_seconds: float = 1.0
    asr_backend: Literal["fake", "qwen3-asr-mlx"] = "fake"
    diarization_backend: Literal["fake", "sherpa-onnx"] = "fake"
    embedding_backend: Literal["fake", "sherpa-onnx"] = "fake"
    # auto：按本机 PATH 选 claude/codex，都没有则纪要失败进 PARTIAL_READY；
    # 测试固定用 fake，绝不真调 CLI。
    minutes_backend: Literal["auto", "claude", "codex", "fake"] = "auto"

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'meeting-workbench.sqlite3'}"
