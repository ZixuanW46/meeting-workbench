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
    # CLI 单次调用超时（秒）。整份纪要要吞下几万字逐字稿再吐几千字，
    # 与分批的清洗不能共用一个值；清洗每批输出与输入等长，6000 字一批约需两三分钟。
    minutes_timeout_seconds: float = 600.0
    cleaning_timeout_seconds: float = 480.0
    # 清洗每批最多多少字：上下文窗口早已不是瓶颈，块越大批次越少，
    # 但单批失败丢得越多、漏块串块的风险越高。
    cleaning_chunk_chars: int = 6000
    # 两个角色各自钉死的模型。清洗是照原样改写，不需要最强模型；
    # 纪要要抓脉络与决议，用最强的。claude 用别名（fable/opus/sonnet）或全名，
    # codex 用模型 slug；留空 = 用各 CLI 自己的默认模型。
    cleaning_model_claude: str | None = "opus"
    minutes_model_claude: str | None = "fable"
    cleaning_model_codex: str | None = "gpt-5.6-luna"
    minutes_model_codex: str | None = "gpt-5.6-sol"
    cleaning_codex_reasoning_effort: str | None = "medium"
    minutes_codex_reasoning_effort: str | None = "medium"
    # Plaud 云端录音导入：mcp = 调官方 @plaud-ai/mcp（stdio），fake = 内存假网关（测试）。
    plaud_backend: Literal["mcp", "fake"] = "mcp"
    # 用 shlex.split 拆分，允许 "npx -y @plaud-ai/mcp" 或 "node /abs/path/index.js"。
    plaud_mcp_command: str = "plaud-mcp"
    # 单次工具调用（含进程启动 + 握手）超时；实测 get_file 约 2.5 s。
    plaud_mcp_timeout_seconds: float = 60.0
    # login 会在服务器机器上开浏览器做 OAuth，MCP 自己最长等 2 分钟。
    plaud_login_timeout_seconds: float = 150.0
    # 下载整段音频的总时长上限（单次 socket 读另有 60 s 超时）。
    plaud_download_timeout_seconds: float = 900.0

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'meeting-workbench.sqlite3'}"
