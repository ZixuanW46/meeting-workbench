# 切分阶段 API 假死：根因、复现与修法

> 2026-09-06 生产机（M4 Mac mini 16GB）观察：一场 87 分钟录音处理到
> `processing_step = DIARIZATION` 时，launchd 跑的 uvicorn 进程 %CPU 100%、RSS 1.4 GB，
> `curl -m 20 localhost:8000/healthz` 超时（0 字节），`/api/projects`、`/api/meetings`
> 同样超时，网页整体打不开；该步骤结束后自动恢复。前面的 VALIDATING / ASR 阶段 API 正常。

## 结论

**根因是 sherpa-onnx 的 `OfflineSpeakerDiarization.process()` 在 Python 线程里全程持有
GIL**，不是 SQLite 长事务，也不是 worker 里的纯 Python 大循环。

- worker 是与 uvicorn 同进程的后台线程（`main.py:_run_worker_loop`）。uvicorn 的
  asyncio 事件循环跑在主线程，每处理一个请求都要拿到 GIL。
- `pipeline/diarization.py:SherpaOnnxDiarizationBackend.diarize()` 调
  `self._model.process(samples)`。sherpa-onnx v1.13.6 的 pybind11 绑定
  `sherpa-onnx/python/csrc/offline-speaker-diarization.cc` 里，`process` 的 lambda 直接
  `return self.Process(samples.data(), samples.size())`，整个文件没有任何
  `py::gil_scoped_release` / `py::call_guard<py::gil_scoped_release>`。C++ 侧跑完
  segmentation 滑窗 → 逐段 embedding → 聚类才返回，期间 Python 解释器一步都动不了。
- 对照组：同一文件里 `SpeakerEmbeddingExtractor` 的 `create_stream / is_ready / compute`
  都带 `py::call_guard<py::gil_scoped_release>()`，所以声纹匹配阶段
  （`SherpaOnnxEmbeddingBackend.embed`）和切分后的簇声纹二次合并都不会饿死事件循环。
- ASR 阶段（mlx-audio）能响应，与观察一致：MLX 的求值在 nanobind 里释放 GIL。
- SQLite 排除：`db.py` 已开 WAL，worker 在切分期间没有打开事务（`_set_step` 提交后才进
  `slot.use()`），且 VALIDATING / ASR 阶段同样有会话在用却没有假死。
- 100% CPU（单核）、31 线程、1.4 GB RSS 都吻合：sherpa 默认 `num_threads=1`；整段音频
  被 `soundfile` 读成 float32（87 分钟 16 kHz ≈ 334 MB），`process` 的参数类型是
  `std::vector<float>`，pybind11 再拷一份，加上 onnxruntime 的 arena。

### 真机探针数据（2026-09-06，`scripts/gil_probe.py`，120 秒真实录音切片）

主线程每 10 ms 醒一次记录最大停顿；后台线程跑被测步骤：

| 步骤 | 耗时 | 探针醒来次数 | 最大停顿 | 结论 |
|---|---|---|---|---|
| 加载两只模型 | 0.21 s | 5 | 0.16 s | 会释放 |
| `soundfile.read` 整段 | 0.01 s | 1 | 0.01 s | 太短，无影响 |
| `process()`（无回调，即产品代码现状） | **16.56 s** | **1** | **16.56 s** | **全程抱死 GIL** |
| `process()`（带进度回调，回调里 `sleep(0)`） | 16.29 s | 155 | 2.27 s | segmentation 阶段仍抱死 |
| `SpeakerEmbeddingExtractor.compute()` ×20 | 1.13 s | 89 | 0.02 s | 会释放 |

线性外推：120 s → 16.6 s，87 分钟 ≈ 12 分钟整段无法响应，与「网页整体打不开、切分
结束后恢复」完全吻合。带回调的那一行还说明：回调只在 `ComputeEmbeddings()` 里触发
（`offline-speaker-diarization-pyannote-impl.h`），`RunSpeakerSegmentationModel()` 不接回调，
所以「回调里让出 GIL」最多把假死从 12 分钟压到约 100 秒（segmentation 占 14%），
仍然超过 `curl -m 20`。

## 复现

### 1. 真机（放好模型的 macOS）

```bash
.venv/bin/python scripts/gil_probe.py "data/meetings/<id>/raw/<录音>.wav" --seconds 120
```

看 `process()（无回调）` 那一行：探针只醒 1 次、最大停顿 ≈ 总耗时即复现。

### 2. 任何机器（fake 后端，不需要模型）

`tests/api/test_pipeline_isolation.py`：

- `test_gil_hog_really_blocks_other_threads`：用 `sum(range(n))` 模拟「一次 C 级长调用不让出
  GIL」（CPython `builtin_sum` 的 int 快路径在 C 循环里不检查 eval breaker），证明探针有意义。
- `test_healthz_and_readonly_api_stay_responsive_while_diarization_hogs_gil`：把这个 GIL hog
  塞进一个 fake 切分后端，worker 线程处理会议时用 `TestClient` 量 `/healthz` 与
  `/api/meetings` 的 wall time——TestClient 的 ASGI 应用跑在同进程的另一个线程里，GIL 被抱死
  时它同样拿不到请求，所以这个断言就是「切分期间 API 必须可用」的验收指标。把
  `run_isolated` 换回同线程直调，这个测试会因为 healthz 等了整段 hog 时长而变红。

## 修法评估

| 方案 | 效果 | 代价 / 风险 | 结论 |
|---|---|---|---|
| **a) 整条流水线搬进 multiprocessing 子进程** | 彻底 | 大改：`Worker` 直接持有 SQLAlchemy 会话、进程内 `EventStore`（SSE）、`SingleModelSlot` 还被 HTTP 线程（声纹入库）共用；都要改成跨进程协议。macOS `spawn` 下模型每场重载，不比现状差（现状 `slot.use()` 每次都 load/unload），但要重做取消、崩溃恢复。≥ 2–3 天 | 记入后续，不是本轮 |
| **a′) 只把持有 GIL 的那一步（sherpa 切分）放进 spawn 子进程** | 彻底（父进程完全不碰 `process()`） | 新增一个 ≈80 行的 `run_isolated`，切分后端加 `isolate` 开关；子进程生命周期完全在 `slot.use()` 之内，16GB 串行约束不变；子进程退出即归还 ~700 MB 音频副本与 onnxruntime arena，父进程 RSS 不再长期 1.4 GB；spawn 启动 + 重新加载 onnx ≈ 1–2 s，对 12 分钟的步骤可忽略 | **本轮实施** |
| b1) C 扩展释放 GIL | 彻底 | 要改 sherpa-onnx 上游：`process` 无回调分支加 `py::gil_scoped_release`（一行）。可以提 PR，但等不到、也不能自己打补丁 wheel | 建议顺手给上游提 issue/PR |
| b2) 用进度回调分块 yield | 只压到 ~100 s | 回调不覆盖 segmentation 阶段（实测最大停顿 2.27 s/120 s 音频，随时长线性增长） | 不够，否决 |
| b3) 把音频切块分别 `process()` | 能释放 | 聚类按块各自编号，簇标签跨块不一致，要再做一层跨块合并——改变产品行为 | 否决 |
| **c) 把 /healthz 与只读接口可用性写进测试** | 不修根因 | 几乎零成本 | **本轮实施**（作为 a′ 的验收指标） |

## 本轮实施（a′ + c）

- `apps/api/meeting_api/pipeline/isolation.py`：`run_isolated(target, *args, timeout=None)`。
  固定 `multiprocessing.get_context("spawn")`（父进程已有 onnxruntime / mlx 线程，fork 不安全；
  Linux CI 也统一 spawn），`daemon=True`，`Pipe` 回传 `("ok", result)` 或
  `("error", exc, traceback)`；父进程 `conn.poll()` 等待期间释放 GIL。子进程崩溃 / 超时
  抛 `IsolatedCallError`，子进程里的异常原样再抛（traceback 进日志），worker 现有的
  `except Exception` 照常把会议标 FAILED 并写 `processing_error`。
- `SherpaOnnxDiarizationBackend(models_dir, isolate=True)`：默认在子进程里执行
  `_diarize_in_subprocess`，子进程内部就是原来的 in-process 实现（`isolate=False`），所以
  mock sherpa 的既有测试仍覆盖真实路径。`load()` 只校验文件、不再在父进程 import sherpa。
- spawn 注意：target 必须是模块级可 pickle 的函数；子进程会重新 import
  `meeting_api.pipeline.diarization`（只依赖 stdlib）；`__main__` 是 `uvicorn.__main__` /
  `pytest.__main__`，两者都有 `if __name__ == "__main__"` 守卫，spawn 用 `__mp_main__`
  重新导入不会再起一个服务。

### 修复后真机验证（同一台机器，60 秒真实录音切片）

| 路径 | 总耗时 | 探针醒来次数 | 主线程最大停顿 |
|---|---|---|---|
| 修复前：`isolate=False` 同线程调 `process()` | 7.88 s | 1 | 7.88 s |
| 修复后：`isolate=True` spawn 子进程 | 8.94 s | 709 | 0.015 s |

多出的 ~1 s 是 spawn 起进程 + 子进程重新加载 onnx；父进程自始至终没有 import `sherpa_onnx`。
fake 后端验收测试本机实测 `/healthz` 0.003 s、`/api/meetings` 0.003 s；把 `run_isolated`
换回同线程直调做对照，`/healthz` 要等 1.497 s（整段 hog）才返回，断言变红。

**跑自己的脚本验证时**要给入口加 `if __name__ == "__main__":` 守卫，否则 spawn 子进程会把
脚本顶层再执行一遍、递归起子进程，报 multiprocessing 的 bootstrapping 错误。

## 上线

按 [README](../README.md) 常规三步（build dist → `make migrate` → `launchctl kickstart -k`），
**先确认 `/api/meetings` 里没有 PROCESSING / GENERATING_MINUTES 的会议再重启**。验证方法：
下一场长录音进入 DIARIZATION 时 `ps` 里应多出一个 Python 子进程占 100% CPU，主进程
CPU 接近 0，`curl -m 5 localhost:8000/healthz` 立刻返回。

## 后续

- ASR（mlx）与声纹提取虽然会释放 GIL，但同样可以走 `run_isolated` 换取「步骤结束即归还
  内存」，父进程 RSS 可稳定在百兆量级；先观察一周切分子进程的稳定性再决定。
- 给 sherpa-onnx 上游提 PR：`offline-speaker-diarization.cc` 的 `process` 无回调分支加
  `py::gil_scoped_release`。
- 子进程化之后「取消」可以真正打断切分（`terminate()`），进度回调也能透传成 SSE 的
  n/m——都在 ROADMAP 的进度条粒度条目里一起做。
