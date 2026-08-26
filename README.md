# meeting-workbench 会议纪要工作台

本地会议工作台：上传录音 → 本地转写 + 认人 → **人工确认说话人**（唯一必经停点）→ 用本机已登录的 Claude Code / Codex CLI 生成纪要。音频永不上云；只有纪要文本会经本机 CLI 发给 Claude/OpenAI。

v1 目标机：**M4 Mac Mini（16GB 统一内存），原生 macOS，无 Docker**。当前阶段模型全部是 fake 后端（接口已留好），真实模型（Qwen3-ASR MLX、sherpa-onnx）按 `ROADMAP.md` M12 接入。

## 在 Mac Mini（macOS，Apple Silicon）上启动

前置：Homebrew。**不要用 Docker**（Docker-on-Mac 吃不到 Metal，16GB 内存也经不起虚拟机开销）。

```bash
brew install python@3.12 node

git clone <本仓库> && cd meeting-workbench

# 后端：venv + 依赖
python3.12 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
# 以后接真实模型时（M12）再加：.venv/bin/pip install -e ".[mac]"

# 前端依赖
cd apps/web && npm install && cd ../..

# 建库（SQLite，落在 ./data/）
make migrate

# 起两个终端：
make dev-api   # FastAPI  → http://localhost:8000（/healthz 自检）
make dev-web   # 前端     → http://localhost:5173（/api 自动代理到 8000）
```

打开 http://localhost:5173 即可。开机自启（launchd）与一键安装脚本在 ROADMAP M13 交付。

### 16GB 内存须知

- 模型严格串行加载（代码里 `SingleModelSlot` 强制）：转写完卸载再做切分/声纹。
- 一小时录音按会后批处理预估 15–30 分钟；处理期间少开 Chrome 标签，一旦 swap 时长会翻数倍。
- 这些数字仅供自用，不构成对外性能承诺。

## 开发（Linux / macOS 通用）

```bash
make setup   # venv + npm install
make test    # 后端 pytest + 前端 vitest（验收命令）
make lint    # ruff + tsc --noEmit
```

测试不需要网络、不需要模型权重、不需要先跑迁移。环境里没有 `make` 时用 `./scripts/test.sh`（等效 `make test`）。

## 目录结构

```
apps/api/       FastAPI + SQLAlchemy + Alembic（SQLite）
apps/web/       Vite + React + TS + Ant Design
packages/domain 纯领域逻辑（状态机、确认规则…），零框架依赖
tests/          后端 + 领域 pytest
scripts/        运维/启动脚本（逐步补齐）
data/           本机数据（音频、SQLite、声纹），不入 git
```

## 关键文档

- `ROADMAP.md`：milestone 切分与每步的 TDD 清单（先读这个再动手）。
- `AGENTS.md`：工程约定与红线。
