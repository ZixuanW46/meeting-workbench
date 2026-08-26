"""运行配置。全部走环境变量（前缀 MW_），默认值面向本机开发。

大文件（音频、声纹向量）都放 data_dir 下的本机目录，路径永不暴露给浏览器。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MW_")

    data_dir: Path = Path("data")
    database_url: str = ""  # 留空则用 data_dir/meeting-workbench.sqlite3

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'meeting-workbench.sqlite3'}"
