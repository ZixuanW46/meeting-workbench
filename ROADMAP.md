# ROADMAP

按小 milestone 推进，每个大约一轮 Codex 能做完。**严格 TDD**：先把「先写失败测试」一节的测试写出来并确认失败，再写最薄实现让它变绿，必要时重构。每个 milestone 的验收命令必须全绿才算完成。

全局约束（任何 milestone 不得违反）：

- v1 目标机是 M4 Mac Mini 16GB，原生 macOS venv，**禁止 Docker / Celery / Redis / Postgres**。
- **禁止下载任何模型权重**（Qwen / pyannote / sherpa 模型等）。CI 与 Linux 开发机一律 fake 后端。
- 模型串行加载：一切模型使用必须经过 `SingleModelSlot`。
- 唯一人工停点是说话人确认；系统只建议、不自动落名；未知合法。
- 纪要只走本机 `claude -p --output-format json` 或 `codex exec`，禁止 `--bare`、禁止扒 token。
- 大文件放 `data/` 本机目录，路径不暴露给浏览器。
- 状态迁移必须走 `meeting_domain.transition()`，禁止直接赋值绕过状态机。

---

## M0 — 骨架（已完成，本仓库现状）

- 仓库、pyproject、前端包、Makefile。
- 领域状态机 + 说话人确认规则 + 纯内存假流水线（DRAFT→AWAITING_SPEAKER_REVIEW→READY）及全部单测。
- FastAPI `/healthz` + `GET /api/meetings`（空列表）。
- fake ASR / fake diarization / `SingleModelSlot` 串行槽。
- Alembic 初始迁移（meetings 表）。
- 前端壳：AntD 布局 + 会议列表占位页 + vitest。
- 验收：`make test` 全绿。

---

## M1 — 新建会议闭环

**目标**：能通过 API 新建一场会议（标题、预计人数可空、本场热词可空），列表和详情返回真实数据；数据库结构以 Alembic 迁移为准。

**先写失败测试**（`tests/api/test_meetings_create.py`）：

- `POST /api/meetings` body `{"title": "周会", "expected_speakers": 4, "hotwords": ["声纹", "MLX"]}` → 201，返回 id 且 `state == "DRAFT"`。
- `expected_speakers` 缺省 → null（不确定是合法的）。
- `title` 为空串 → 422。
- `GET /api/meetings/{id}` → 200 返回同一对象；不存在的 id → 404。
- `GET /api/meetings` 按创建时间倒序包含新会议。

**再写实现**：

- `meeting_api/schemas.py`：Pydantic 请求/响应模型。
- `meeting_api/routes/meetings.py`：POST、GET detail。
- `Meeting` 模型加 `hotwords_json`（本场热词，JSON 文本列）；新增 Alembic 迁移 `0002`。
- lifespan 里的 `init_db` 保留给测试；README 的真实运行路径改为 `make migrate` 后启动。

**验收命令**：`make test-api && .venv/bin/alembic upgrade head`

**明确不做**：不做前端表单（M8）、不做上传、不做任何状态推进。

---

## M2 — 音频上传（multipart 先行，接口形状为 tus 预留）

**目标**：给 DRAFT 会议上传一个音频文件，落到 `data/meetings/{id}/raw/`，状态走 DRAFT→UPLOADING→QUEUED；接口形状为 M11 换 tus 留好。

**先写失败测试**（`tests/api/test_upload.py`）：

- `POST /api/meetings/{id}/upload`（multipart 一个文件）→ 200，返回 `{"size": n, "sha256": "..."}`；会后 `GET` 详情 `state == "QUEUED"`。
- 落盘文件存在且字节一致（通过 API 返回的 size/sha256 断言，不暴露路径）。
- 对非 DRAFT 会议上传 → 409（状态机拒绝）。
- 空文件 → 422。
- 响应里不包含任何服务器文件系统路径。

**再写实现**：

- `meeting_api/storage.py`：`meeting_dir(settings, meeting_id)`、保存流并算 sha256。
- 路由用 `meeting_domain.transition()` 推 UPLOADING→QUEUED（同一请求内完成）。
- `Meeting` 加 `audio_filename`、`audio_sha256`、`audio_size`；迁移 `0003`。
- 上传接口独立成 router，注释标明「tus 替换点」（M11 只换这个 router）。

**验收命令**：`make test-api`

**明确不做**：不做断点续传、不做进度条、不做音频格式转换/校验时长（M3 校验步骤再说）。

---

## M3 — 单队列 fake worker：推到人工停点

**目标**：进程内单 worker（同时只处理一场），把 QUEUED 的会议按 校验→ASR→切分→声纹匹配→准备确认包 的顺序推到 AWAITING_SPEAKER_REVIEW，全程用 fake 后端 + `SingleModelSlot`。

**先写失败测试**（`tests/api/test_worker.py`、`tests/domain` 补充）：

- 上传完成后触发 worker 跑一轮（测试里同步调用 `worker.process_next()`，不开线程），会议变为 `AWAITING_SPEAKER_REVIEW`。
- 处理产物落库：转写片段（带起止时间）、说话人簇、每簇 2–3 个试听片段引用、建议身份（fake 里给 S1 一个建议、S2 未知）。
- 两场排队时，一次 `process_next()` 只处理一场（单并发）。
- fake ASR 与 fake diarization 在一次处理里从未同时 loaded（用探针后端断言，走 `SingleModelSlot`）。
- 处理中抛异常 → 会议 `FAILED`，错误信息落库。

**再写实现**：

- `meeting_api/worker.py`:`Worker.process_next()`（拉一场 QUEUED，依次执行步骤，产物写 SQLite）。
- 新表：`transcript_segments`、`speaker_clusters`（含 suggested_person_id、试听片段 JSON）；迁移 `0004`。
- `meeting_api/main.py`：启动一个后台线程循环调用 `process_next()`（可用 `MW_WORKER_DISABLED=1` 关掉，测试用同步调用）。
- PROCESSING 内部步骤名记到 `Meeting.processing_step`（给 M4 的进度用）。

**验收命令**：`make test-api`

**明确不做**：不接真实模型；不做 SSE（M4）；不做确认（M5）；不做音频真实解码——fake 不读文件内容。

---

## M4 — SSE 进度 + 3 秒轮询降级

**目标**：`GET /api/meetings/{id}/events` 用 SSE 推送状态与 PROCESSING 内部步骤变化，支持 `Last-Event-ID` 续传；同一数据有轮询端点兜底。

**先写失败测试**（`tests/api/test_events.py`）：

- SSE 端点 content-type 为 `text/event-stream`，事件 data 为 JSON `{state, processing_step, seq}`，`id:` 单调递增。
- 带 `Last-Event-ID: n` 重连 → 只收到 seq > n 的事件。
- `GET /api/meetings/{id}/progress` 轮询端点返回同结构的当前值。
- 状态被 worker 推进后，新事件可被读到（测试里手动推状态 + 读一条事件即可，不要真等待）。

**再写实现**：

- `meeting_api/events.py`：每场会议一个内存事件序列（seq 自增，重启丢历史事件是可接受的，当前值从库里补）。
- worker 每次状态/步骤变化调用 `events.publish(meeting_id, ...)`。
- SSE 路由用 `StreamingResponse`；轮询路由直接读库。

**验收命令**：`make test-api`

**明确不做**：前端接 SSE（M8）；不做多实例广播（单机单进程）。

---

## M5 — 说话人确认 API 闭环

**目标**：人工停点完整闭环：拿确认包 → 逐卡提交决定 → 全部有决定后推进 AWAITING_SPEAKER_REVIEW→APPLYING_DECISIONS→GENERATING_MINUTES（纪要生成本身是 M6，先停在该状态）。

**先写失败测试**（`tests/api/test_speaker_review.py`）：

- `GET /api/meetings/{id}/review`：返回每张卡（簇代号、建议身份或 null、试听片段引用、对应文字），**不含伪精确百分比**（响应模型里不允许 score/percent 字段）。
- `POST /api/meetings/{id}/review/decisions`：提交全部决定 → 200，状态推进到 `GENERATING_MINUTES`（APPLYING_DECISIONS 在同请求内完成回写）。
- 少一张卡的决定 → 409，body 里列出缺的 cluster_id，状态不变（复用 `ReviewIncomplete`）。
- 含 `KEEP_UNKNOWN`/`UNDECIDED_UNKNOWN` 的提交合法，会议记 `has_unconfirmed_speakers = true`。
- `REASSIGN`/`LINK_EXISTING` 缺 `person_id` → 422。
- 决定回写：簇上落最终 person_id 或未知标记；**没有任何自动落名路径**。

**再写实现**：

- `meeting_api/routes/review.py`；决定校验直接复用 `meeting_domain.speaker_review`。
- `persons` 表（id、显示名）；`NEW_PERSON` 在此建人；迁移 `0005`。
- 会议加 `has_unconfirmed_speakers` 列。

**验收命令**：`make test-api`

**明确不做**：声纹入库（M9）；确认 UI（M8）；重跑 ASR/diarization——确认后只改标签。

---

## M6 — 纪要生成：CLI 适配器 + READY / PARTIAL_READY

**目标**：GENERATING_MINUTES 阶段把逐字稿写成文件，通过适配器调本机 CLI 生成纪要；成功→READY，失败→PARTIAL_READY 且可重试。测试全部用 fake 适配器。

**先写失败测试**（`tests/api/test_minutes.py`）：

- fake 适配器成功：会议 READY，纪要 markdown 落库/落盘可通过 `GET /api/meetings/{id}/minutes` 取到。
- `has_unconfirmed_speakers` 的会议，纪要开头带「含未确认说话人」标记。
- fake 适配器抛 `MinutesCliError`（模拟配额）：会议 PARTIAL_READY，`POST /api/meetings/{id}/minutes/retry` → 回 GENERATING_MINUTES 并可再次成功。
- claude 适配器的**命令构造**单测（不真执行）：形如 `claude -p <prompt> --output-format json` 且指定关闭文件工具；断言参数里没有 `--bare`。codex 适配器同理（`codex exec ...`）。
- `GET /api/settings/minutes-cli`：探测本机 `claude`/`codex` 可执行文件是否存在（测试用假 PATH）。

**再写实现**：

- `meeting_api/minutes/adapter.py`：`MinutesAdapter` Protocol + `FakeMinutesAdapter` + `ClaudeCliAdapter` + `CodexCliAdapter`（subprocess，超时、非零退出→`MinutesCliError`）。
- worker 增加 GENERATING_MINUTES 处理；逐字稿写到 `data/meetings/{id}/transcript.txt`。
- 界面文案素材：接口返回里带 `"note": "纪要文本会发送到 Claude/OpenAI 云端，音频不会上传"`。

**验收命令**：`make test-api`

**明确不做**：CI 里真调 claude/codex；不做 DOCX（M7）；不做提示词调优。

---

## M7 — 导出

**目标**：任何 AWAITING_SPEAKER_REVIEW 之后的会议可导出转写（MD）；READY/PARTIAL_READY 可导出纪要（MD + DOCX）。PARTIAL_READY 也必须能导出转写（纪要失败不锁死成果）。

**先写失败测试**（`tests/api/test_export.py`）：

- `GET /api/meetings/{id}/export/transcript.md`：按时间排、带说话人标签（确认后的名字或「说话人S2（未确认）」）。
- `GET /api/meetings/{id}/export/minutes.md`、`minutes.docx`：正确 content-type 与附件文件名；DOCX 能被 `python-docx` 重新打开。
- DRAFT 会议导出 → 409。

**再写实现**：

- `meeting_api/routes/export.py`；`python-docx` 加入依赖。

**验收命令**：`make test-api`

**明确不做**：PDF、模板美化、批量导出。

---

## M8 — 前端会议工作台（纵向切片打通）

**目标**：前端完成 列表（真数据）→ 新建 → 上传 → 进度（SSE + 断线 3 秒轮询）→ 说话人确认卡（WaveSurfer 试听）→ 转写|纪要 视图。至此一场会可以全程在浏览器里走完（后端仍是 fake 模型）。

**先写失败测试**（vitest + msw，`apps/web/src/**/*.test.tsx`）：

- 列表页从 `/api/meetings` 渲染真数据；空态保留。
- 新建表单：标题必填、人数可选「不确定」、热词标签输入。
- 进度组件：SSE mock 推事件更新步骤文案；SSE 断开后落到 3 秒轮询（fake timers）。
- 确认卡：每卡必须选择一个决定后「提交」才可点；提交含未知时出现「含未确认说话人」提示。
- api client 单测：409 缺卡错误渲染成缺卡提示。

**再写实现**：

- `src/api/client.ts`（fetch 封装）、`src/pages/`（NewMeeting、Workbench）、`src/components/`（Progress、SpeakerCard、TranscriptView、MinutesView）。
- 依赖加 `wavesurfer.js`、开发依赖加 `msw`。
- 音频试听走新增的 `GET /api/meetings/{id}/audio`（后端 Range 支持可以简化为整文件流）。

**验收命令**：`make test`

**实现者**：**Claude Fable 5**（不要 Codex）。视觉参考 Linear：克制、紧凑、细边框、列表优先，不要 Ant Design 默认企业后台。

**明确不做**：声纹库/词语库页面（M9/M10）、移动端。视觉不是「以后再打磨」——M8 就要是 Linear 气质的可用工作台。

---

## M9 — 词语库：全局 + 本场 + 不可变快照 + 显式重转写

**目标**：全局词库 CRUD；开跑时把「全局+本场」打成不可变快照存到会议上，ASR 只读快照；改词库后由用户显式触发重转写。

**先写失败测试**（`tests/domain/test_hotword_snapshot.py` + `tests/api/test_hotwords.py`）：

- 领域：`snapshot(global_words, meeting_words)` 去重、排序稳定、返回冻结结构；快照建立后修改全局词库不影响已有快照（值语义）。
- worker 开跑时落快照列；fake ASR 收到的热词 == 快照内容。
- 全局词库 CRUD API。
- `POST /api/meetings/{id}/retranscribe`：仅在 AWAITING_SPEAKER_REVIEW 或之后允许，重打快照、清产物、状态回 QUEUED；其他状态 409。
- 确认说话人（M5 流程）**不**触发重转写。

**再写实现**：

- `meeting_domain/hotwords.py`；`hotword_entries` 表 + 会议 `hotword_snapshot_json`；迁移；路由。

**验收命令**：`make test-api`

**明确不做**：词库导入导出、按行业分组。

---

## M10 — 声纹：入库条件 + 声纹库管理

**目标**：确认环节产生的合格单人片段生成声纹并入库（fake embedding），声纹库可查可删；未确认簇绝不入库。

**先写失败测试**（`tests/domain/test_voiceprint_rules.py` + `tests/api/test_voiceprints.py`）：

- 领域规则 `eligible_for_enrollment(decision, quality)`：仅当决定是 CONFIRM/REASSIGN/LINK_EXISTING/NEW_PERSON（即用户确认了身份）且质量合格才 True；KEEP_UNKNOWN/UNDECIDED_UNKNOWN 永远 False。
- 质量不合格（fake 质量分低于阈值）不入库。
- M5 提交决定后，合格簇的向量出现在声纹存储；person 关联正确。
- `GET/DELETE /api/voiceprints`；删除后 fake 匹配不再建议该人。
- 向量存本地（sqlite BLOB 或 `data/voiceprints/`），API 不暴露原始向量路径。

**再写实现**：

- `meeting_api/pipeline/embedding.py`：`EmbeddingBackend` Protocol + fake（真实 sherpa-onnx 在 M12）。
- `meeting_domain/voiceprint.py`（入库规则，纯函数）；`voiceprints` 表；迁移；M5 提交流程里挂钩。
- 前端声纹库页（列表 + 删除）。

**验收命令**：`make test`

**明确不做**：向量检索优化、跨库合并人、导入外部声纹。

---

## M11 — tus 断点续传替换 multipart

**目标**：上传通道换成 tus 协议（服务端 + 前端 tus-js-client），大文件断网可续传；M2 的 multipart 端点保留为兼容或删除（二选一，删除需同步改前端）。

**先写失败测试**（`tests/api/test_tus_upload.py`）：

- tus 创建（`POST /files/`）返回 Location + `Tus-Resumable` 头。
- 分两次 PATCH 传完一个文件，offset 正确衔接；错 offset → 409。
- `HEAD` 返回当前 offset（断线后客户端靠它续传）。
- 传完触发与 M2 相同的落盘 + sha256 + 状态推进逻辑（复用 storage 层断言）。

**再写实现**：

- 优先评估 `tuspy`/现成 ASGI tus 实现，不合适就手写最小子集（creation + HEAD + PATCH + offset 校验）。
- 前端上传组件换 `tus-js-client`，展示可暂停/续传。

**验收命令**：`make test`

**明确不做**：并行分片、S3 之类远端存储。

---

## M12 — 真实模型后端接入（仅 macOS，条件依赖）

**目标**：在 Mac 上 `pip install -e ".[mac]"` 后，`MW_ASR_BACKEND=qwen3-asr-mlx`、`MW_DIARIZATION_BACKEND=sherpa-onnx` 生效；Linux/CI 完全不受影响，照旧 fake。模型权重由用户手动下载到 `data/models/`，代码只从本地路径加载。

**先写失败测试**（可在 Linux 跑的部分）：

- 配置读取：`Settings` 新增后端选择项，默认 fake。
- 非 darwin 平台选择真实后端 → 启动时报清晰错误（不是 ImportError 堆栈）。
- 真实后端类的 `load()/unload()` 遵守 `LoadableModel` 协议（用 mock 的 mlx/sherpa 模块测调用顺序：先 unload ASR 再 load diarization——由 worker 流程保证）。
- 模型文件缺失时报「把模型放到 data/models/... 」的可执行指引。

**再写实现**：

- `pipeline/asr.py` 补 `Qwen3AsrMlxBackend`（import 放函数内，darwin-only）；`pipeline/diarization.py`、`embedding.py` 补 sherpa-onnx 后端。
- `scripts/download_models.md`：写清 Will 手动下载哪些文件放哪（**代码不自动下载**）。
- 真机验收（Will 手动）：10 分钟四人录音，两已知两未知，全程走完出纪要。

**验收命令**：`make test`（CI 无模型照样全绿）+ Mac 上手动脚本 `scripts/smoke_real_models.sh`

**明确不做**：CI 下模型、性能调优、量化实验、对客户的性能承诺。

---

## M13 — Mac Mini 交付：启动脚本 + launchd + 备份

**目标**：Will 在 Mac Mini 上一条命令装好、开机自启、重启不死；磁盘满/内存不足有人话错误；数据可备份恢复。

**先写失败测试**：

- `scripts/` 下脚本有 bats 或 pytest 子进程冒烟测试（语法 + dry-run）。
- 磁盘空间检查：上传前空间不足 → 422「磁盘空间不足，还剩 X GB」。
- 备份：`scripts/backup.sh` 打包 SQLite + data 目录（排除模型权重）；`restore.sh` 能恢复到新目录并通过 healthz。
- worker 启动时发现上次残留的 PROCESSING 会议 → 标 FAILED（或重新入队，二选一，写测试锁定行为）。

**再写实现**：

- `scripts/mac_install.sh`（检查 brew python@3.12、建 venv、装依赖、跑迁移、build 前端）。
- `scripts/launchd/`：`com.will.meeting-workbench.plist`（api + 静态前端一个服务），`install_launchd.sh`。
- uvicorn 直接托管 `apps/web/dist` 静态文件（省一个进程）。

**验收命令**：`make test` + Mac 上 `scripts/mac_install.sh && launchctl list | grep meeting`

**明确不做**：Linux+GPU 安装包、多用户、外网访问、自动更新。
