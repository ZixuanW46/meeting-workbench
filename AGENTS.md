# AGENTS.md — 给后续 Codex / Claude 的工程约定

本仓库按 `ROADMAP.md` 的 milestone 顺序开发。一次只做一个 milestone，做完必须全绿再停。

## 工作流（每个 milestone 固定四步）

1. **先写失败测试**：按 ROADMAP 该节「先写失败测试」列的用例写测试，跑一遍确认它们**因缺实现而失败**（不是因语法错误失败）。
2. **最薄实现**：只写让这些测试变绿的代码，不顺手做下一个 milestone 的事。
3. **全绿**：`make test`（后端 pytest + 前端 vitest）+ `make lint`（ruff + tsc）全部通过。
4. **提交**：一个 milestone 一个（或少数几个）commit，message 以 milestone id 开头，如 `M1: 新建会议闭环`。

## 常用命令

```bash
make setup      # 首次：建 .venv + npm install
make test       # 全量测试（验收）
make test-api   # 仅 pytest
make test-web   # 仅 vitest
make lint       # ruff + tsc --noEmit
make migrate    # alembic upgrade head（真实运行前）
make dev-api    # uvicorn :8000
make dev-web    # vite :5173（/api 代理到 :8000）
```

## 分层规则

- `packages/domain/meeting_domain/`：**纯领域逻辑**。禁止 import FastAPI、SQLAlchemy、任何模型运行时。状态机、说话人确认规则、词库快照、声纹入库条件都在这里，且必须有单测。
- `apps/api/meeting_api/`：FastAPI + SQLAlchemy。所有状态迁移必须调 `meeting_domain.transition()`，禁止直接给 `meeting.state` 赋新值绕过校验。
- `apps/api/meeting_api/pipeline/`：模型后端接口。任何模型只能通过 `SingleModelSlot` 使用（16GB 内存串行硬约束）。
- `apps/web/`：Vite + React + TS + AntD。业务判断（如「每卡必须有决定」）以后端为准，前端只做体验层拦截。
- `tests/`：后端与领域测试都在根 `tests/`（pytest 从 `pyproject.toml` 读 `pythonpath`，无需安装即可跑）。前端测试放组件旁边 `*.test.tsx`。

## 数据库

- SQLite，文件在 `MW_DATA_DIR`（默认 `./data`）。
- 结构以 Alembic 迁移为准：改模型必须新增 `apps/api/migrations/versions/` 迁移，编号顺延（0002、0003…），手写、可读、带 downgrade。
- 测试用 `init_db()`（create_all）建临时库，不跑迁移；因此迁移和模型必须保持一致（改一个就改另一个）。

## 红线（违反即返工）

- ❌ 不下载任何模型权重（CI、测试、开发机一律 fake 后端；真机模型 Will 手动放 `data/models/`）。
- ❌ 不引入 Docker、Celery、Redis、Postgres。
- ❌ 不自动落名说话人：身份只能来自用户在确认停点的决定；未知是合法结果。
- ❌ 不在纪要通道之外把任何数据发到云端；纪要只走本机 `claude -p --output-format json` 或 `codex exec`，**禁止 `--bare`、禁止扒 token**。
- ❌ 不把服务器文件路径放进 API 响应。
- ❌ 不给建议身份展示伪精确置信百分比（只有「较高 / 需判断」两档）。
- ❌ 不动 `/workspace` 下其他项目。
- ❌ 不把 16GB 机器上的处理时长写成对客户的性能承诺。

## 平台约定

- 开发/CI 在 Linux 跑，v1 生产是 M4 Mac Mini 16GB（原生 macOS venv + localhost + launchd）。
- macOS 专属依赖只能进 `[project.optional-dependencies].mac`，代码里 import 放函数内并按平台报清晰错误。
- Python ≥3.12；ruff 规则见 `pyproject.toml`；TS strict 已开。
- 代码注释和用户可见文案用中文；标识符用英文。
