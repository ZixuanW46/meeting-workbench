# AGENTS.md — 给后续 Codex / Claude 的工程约定

本仓库按 `ROADMAP.md` 的 milestone 顺序开发。一次只做一个 milestone，做完必须全绿再停。

## 谁写哪一层（2026-08-27 锁定）

- **后端 / 领域 / 迁移 / API 测试**：Codex 实现，Box 审，Fable 5 再审。
- **产品前端 `apps/web/`**：只由 **Claude Fable 5** 写。Codex **禁止**改 `apps/web/`（含页面、样式、组件、前端测试）。
- 前端视觉参考 [Linear](https://linear.app)：克制、紧凑、近黑画布与发丝线分层（见 `docs/LINEAR-DESIGN.md`）、细边框、列表优先，不要 Ant Design 默认企业后台（大蓝顶栏、厚阴影、宽留白）。Fable 5 可以换掉 AntD 默认壳；业务判断仍以后端为准。

## 工作流（每个 milestone 固定四步）

1. **先写失败测试**：按 ROADMAP 该节「先写失败测试」列的用例写测试，跑一遍确认它们**因缺实现而失败**（不是因语法错误失败）。
2. **最薄实现**：只写让这些测试变绿的代码，不顺手做下一个 milestone 的事。
3. **全绿**：`make test`（后端 pytest + 前端 vitest）+ `make lint`（ruff + tsc）全部通过。
4. **提交**：遵循 [Conventional Commits](https://www.conventionalcommits.org/)——`type(scope): 摘要`，type 限 `feat` / `fix` / `test` / `docs` / `refactor` / `perf` / `chore`；milestone 交付时把 milestone id 写进 scope（如 `feat(M22): 新建会议闭环`），日常修复/优化可省略 scope。一个逻辑变更一个 commit，正文写清动机与验证方式；禁止把无关文件捆进同一个 commit。

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
- `apps/web/`：Vite + React + TS。视觉跟 Linear，不跟 AntD 默认主题。业务判断（如「每卡必须有决定」）以后端为准，前端只做体验层拦截。**只许 Fable 5 改这个目录。**
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
