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
    static_dir: Path = Path("apps/web/dist")
    database_url: str = ""  # 留空则用 data_dir/meeting-workbench.sqlite3
    # 上传完成后至少仍保留 1 GiB，避免 SQLite 和处理产物把系统盘彻底写满。
    upload_disk_reserve_bytes: int = 1024**3
    worker_disabled: bool = False
    worker_poll_seconds: float = 1.0
    # auto：仅 Darwin 且对应模型文件完整时选真实后端，其余情况安全回退 fake。
    asr_backend: Literal["auto", "fake", "qwen3-asr-mlx"] = "auto"
    diarization_backend: Literal["auto", "fake", "sherpa-onnx"] = "auto"
    embedding_backend: Literal["auto", "fake", "sherpa-onnx"] = "auto"
    # 出卡前按簇声纹自动并入的碎簇时长上限（秒），0 = 关闭，建议 15~30。
    fragment_merge_max_seconds: float = 20.0
    # 碎簇吸收安全边际：最近主簇需比次近主簇至少近这么多，0 = 关闭。
    fragment_merge_min_margin: float = 0.05
    # auto：按本机 PATH 选 claude/codex，都没有则纪要失败进 PARTIAL_READY；
    # 测试固定用 fake，绝不真调 CLI。
    minutes_backend: Literal["auto", "claude", "codex", "fake"] = "auto"
    # 关闭后跳过转写清洗，纪要直接吃原文。
    transcript_cleaning_enabled: bool = True

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'meeting-workbench.sqlite3'}"
