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

## 数据与隐私

- 音频、转写、说话人信息、声纹和数据库均留在 `data/`，音频不出本机。
- 纪要只走用户已登录的本机 CLI：Claude 使用 `claude -p --output-format json`，Codex 使用 `codex exec`。禁止 `--bare`，也不读取 CLI token。
- 使用云端 CLI 时，纪要生成所需的文本会由该 CLI 发送给相应服务；音频和模型权重不会随请求发送。
- 想自定义纪要风格时，把提示词模板写进 `data/minutes_prompt.md`（存在即覆盖默认指令头；逐字稿仍会附在其后）。
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

本项目采用 [MIT License](LICENSE)。
