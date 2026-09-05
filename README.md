# meeting-workbench 会议纪要工作台

面向线下会议的本地工作台：上传录音、本地转写与说话人分析、人工确认说话人，再用本机已登录的 Claude Code 或 Codex CLI 生成纪要。身份确认始终由人完成，未知说话人也是合法结果。

## 快速开始

运行环境为 macOS Apple Silicon，推荐 M4 Mac Mini。请先安装 [Homebrew](https://brew.sh/)；安装脚本会通过 Homebrew 补齐 Python 3.12、Node 和 ffmpeg，建立虚拟环境、安装前端、迁移数据库、准备模型并执行就绪检查。

```bash
git clone <repo> && cd meeting-workbench
./scripts/mac_install.sh
```

Qwen3-ASR 与 sherpa-onnx 都是公开模型；公开模型无需 Hugging Face token，也不要登录 Hugging Face。模型文件只保存在本机 `data/models/`。

纪要功能需要用户自己登录一个本机 CLI；安装脚本不会代登，也不会读取或保存登录 token：

```bash
claude /login
# 或
codex login
```

需要开机自启时安装已有的 launchd 配置：

```bash
./scripts/launchd/install_launchd.sh
```

launchd 中的 API 默认只绑定 `127.0.0.1:8000`，不监听局域网；由同机浏览器访问工作台。若确认所在网络可信，可在安装时显式开放局域网访问（API 无鉴权，开放前请自行评估）：

```bash
MW_BIND_HOST=0.0.0.0 ./scripts/launchd/install_launchd.sh
```

之后局域网设备可通过 `http://<主机名>.local:8000`（mDNS 固定网址）或本机 IP 访问。

## 从 Plaud 导入录音（可选）

用 Plaud 录音笔的话，可以在「新建会议」页把录音来源切到「从 Plaud 导入」，直接从已登录的 Plaud 账号里挑一条录音导入，不必先手动下载再上传。前置条件是本机装好 Plaud 官方 MCP 并登录一次：

```bash
npm install -g @plaud-ai/mcp   # 需要 Node.js ≥ 20；装完 PATH 里会有 plaud-mcp
```

登录既可以在界面里点「登录 Plaud」（会在运行 API 的这台机器上打开浏览器做 OAuth），也可以在终端跑 `plaud-mcp install`（它会顺带把本机检测到的 AI 客户端也配上 Plaud MCP）。登录态由 Plaud MCP 自己保存在 `~/.plaud/`，工作台**不读取**这个目录，所有查询都通过起 `plaud-mcp` 子进程调用 MCP 工具完成。

导入时后端用 MCP 拿到录音的临时下载直链，把音频下载到 `data/` 后走与上传完全相同的转码与转写流程；会议记住来源录音 id，同一条录音不会被重复导入，列表里也会标出「已导入」。会议日期默认取录音开始时间（按本机时区），标题优先用你填的，其次用 Plaud 里改过的名字，设备默认的时间名则留给自动命名接管。

相关配置：`MW_PLAUD_MCP_COMMAND`（默认 `plaud-mcp`，可写成 `npx -y @plaud-ai/mcp`）、`MW_PLAUD_MCP_TIMEOUT_SECONDS`（单次 MCP 调用，默认 60）、`MW_PLAUD_LOGIN_TIMEOUT_SECONDS`（默认 150）、`MW_PLAUD_DOWNLOAD_TIMEOUT_SECONDS`（默认 900）。

## 数据与隐私

- 音频、转写、说话人信息、声纹和数据库均留在 `data/`，音频不出本机。
- 从 Plaud 导入只是把你自己账号里的录音**拉下来**：请求经 Plaud 官方 MCP 发出，工作台不读取其 token 文件，也不向 Plaud 上传任何内容。
- 纪要只走用户已登录的本机 CLI：Claude 使用 `claude -p --output-format json`，Codex 使用 `codex exec`。禁止 `--bare`，也不读取 CLI token。
- 使用云端 CLI 时，纪要生成所需的文本会由该 CLI 发送给相应服务；音频和模型权重不会随请求发送。
- 纪要与清洗的 CLI 子进程在空临时目录里运行，关闭全部内置工具与 MCP、不持久化会话；逐字稿只留在 `data/`。
- 想自定义纪要风格时，把提示词模板写进 `data/minutes_prompt.md`（存在即覆盖默认指令头；逐字稿仍会附在其后）。
- 每场会议都归属一个「项目」：不选就落到默认项目 General。项目有自己的一层热词，任何状态都能改挂，改挂不影响已生成的产物。删除项目只解除归属（其会议改挂到 General），会议本身保留；General 不可删除、可改名。
- 项目列表支持用户自定义顺序：新建的项目追加到末尾，拖动排序后顺序持久保存；删除项目不影响其余项目的相对顺序。
- 热词分三层，转写开跑时合并冻结成本场不可变快照：全局词库 + 会议所属项目的热词 + 本场热词；纪要术语表同样叠加全局与项目两层的注解，同一个词以项目的注解为准。改词库或改挂项目都不会回溯已冻结的快照，要让新词生效请重新处理该会议。
- General 是横跨多个项目的大会用的：它的会议叠加**所有项目**的热词，同一个词多个项目都写了注解时以项目列表里靠前者为准。General 自己不维护热词（词库页不给编辑入口）。
- 词库页可以把热词在全局词库与项目之间、项目与项目之间批量移动；目标已有同词就合并，目标已写注解时保留目标的说法。
- 会议可标记语言（`zh` 中文 / `en` 英文，默认中文，新建时选、之后也可改）：英文会议的转写与清洗保留英文原文，纪要仍用中文撰写；改语言不影响已有产物，只在下一次转写或重转写时生效。
- 单次 CLI 调用超时可调：`MW_MINUTES_TIMEOUT_SECONDS`（默认 600）、`MW_CLEANING_TIMEOUT_SECONDS`（默认 180）。
- 处理失败或被取消的会议可在界面上「重新处理」，音频不必重传；服务重启时中断的转写会自动回到队列。
- 模型在本机串行使用，以适应 16GB 统一内存；实际耗时取决于录音与机器负载，不作为对外性能承诺。

## 开发

Linux 与 macOS 开发环境都默认使用 fake 后端，测试不需要网络、模型权重或预先迁移数据库。

```bash
make setup      # 建立虚拟环境并安装 Python、前端依赖
make test       # pytest + vitest
make lint       # ruff + tsc --noEmit
make migrate    # 本地运行前升级 SQLite 结构
make dev-api    # API 开发服务
make dev-web    # Web 开发服务
```

本机没有 `make` 时，使用 `./scripts/test.sh` 运行完整测试。API 和 Web 开发服务也可直接按 `Makefile` 中的等价命令启动。

## 目录结构

```text
apps/api/        FastAPI + SQLAlchemy + Alembic（SQLite）
apps/web/        Vite + React + TypeScript，Linear 气质的自绘界面
packages/domain/ 纯领域逻辑（状态机、确认规则等），零框架依赖
tests/           后端、领域与脚本 pytest
scripts/         安装、模型、备份和 launchd 运维脚本
data/            本机数据（音频、SQLite、声纹和模型），不入 git
```

## 文档

- `ROADMAP.md`：milestone 范围与 TDD 验收清单。
- `AGENTS.md`：工程分层、开发流程与红线。
- `scripts/download_models.md`：模型来源及手动准备说明。
- `docs/DIARIZATION-GIL.md`：切分阶段 API 假死的根因（sherpa-onnx 持有 GIL）、复现与子进程隔离修法。

本项目采用 [MIT License](LICENSE)。
