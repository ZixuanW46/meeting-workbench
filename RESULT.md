# M15 — 上传音频转码结果

## 完成内容

- WAV、FLAC、OGG 按原文件保存，不调用 ffmpeg。
- MP3、M4A、AAC 按文件后缀识别；multipart 上传和 tus 完成都会在进入
  `QUEUED` 前调用 ffmpeg，转换为 16kHz、单声道、PCM s16le WAV。
- ffmpeg 命令明确包含 `-ar 16000`、`-ac 1`，测试通过 PATH 内的轻量 stub
  锁定参数，不执行真实大文件转码。
- 转码成功后删除压缩源文件，会议的 `audio_filename`、大小和 SHA-256 均指向
  转换后的 WAV。
- 缺少 ffmpeg 时返回 422「未找到 ffmpeg」；ffmpeg 非 0 退出或没有生成有效
  输出时返回 422「音频转码失败」。失败不会进入 `QUEUED`：multipart 保持
  `DRAFT`，tus 保持可重新发起上传的 `UPLOADING`。
- 所有状态推进继续通过 `meeting_domain.transition()` 校验。

## TDD 记录

- 红灯：`.venv/bin/python -m pytest tests/api/test_transcode.py -q`，首次结果为
  6 failed、3 passed；失败均来自 M15 转码能力尚未实现。详见 `RED.txt`。
- 绿灯：最终 `tests/api/test_transcode.py` 为 11 passed。
- 全量验收：`./scripts/test.sh` 通过，pytest 202 passed，vitest 8 个测试文件、
  25 个测试通过。详见 `GREEN.txt`。
- lint：全仓 ruff 与 `tsc --noEmit` 均通过。环境未安装 make，因此直接执行了
  Makefile 中 `make lint` 对应的两条原始命令。

## 范围确认

- 未修改 `apps/web/`。
- 未下载模型或安装 ffmpeg。
- 未实现 M16。
