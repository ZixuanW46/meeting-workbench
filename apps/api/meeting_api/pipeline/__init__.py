"""模型后端接口层。

约定（16GB 统一内存的硬约束）：
- 所有后端实现 load()/unload()/是否已加载。
- 同一时刻只允许一个模型驻留内存：一律通过 SingleModelSlot 使用后端，
  禁止 ASR + diarization + 声纹同时常驻。
- Linux 开发机 / CI 只有 fake 后端；真实后端（Qwen3-ASR MLX、sherpa-onnx）
  在 M11 于 macOS 上接入，并且永远不在 CI 下载权重。
"""
