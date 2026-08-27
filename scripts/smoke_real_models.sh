#!/usr/bin/env bash
# Will 在 Mac 上手动运行；不下载模型，不用于 Linux/CI。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "真实模型冒烟仅支持 macOS；Linux/CI 请继续使用 fake" >&2
  exit 2
fi
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "用法：$0 /path/to/local-test.wav" >&2
  exit 2
fi

.venv/bin/python - "$1" <<'PY'
import sys
from pathlib import Path

from meeting_api.config import Settings
from meeting_api.pipeline.asr import get_asr_backend
from meeting_api.pipeline.diarization import get_diarization_backend
from meeting_api.pipeline.embedding import get_embedding_backend
from meeting_api.pipeline.serial import SingleModelSlot

audio_path = Path(sys.argv[1])
settings = Settings()
if (
    settings.asr_backend != "qwen3-asr-mlx"
    or settings.diarization_backend != "sherpa-onnx"
    or settings.embedding_backend != "sherpa-onnx"
):
    raise SystemExit("请先按 download_models.md 设置三个真实后端环境变量")
models_dir = settings.data_dir / "models"
slot = SingleModelSlot()

asr = get_asr_backend(settings.asr_backend, models_dir)
diarization = get_diarization_backend(settings.diarization_backend, models_dir)
embedding = get_embedding_backend(settings.embedding_backend, models_dir)

with slot.use(asr) as loaded_asr:
    transcript = loaded_asr.transcribe(audio_path)
print(f"ASR：{len(transcript)} 个片段（ASR 已卸载）")

with slot.use(diarization) as loaded_diarization:
    speakers = loaded_diarization.diarize(audio_path)
print(f"切分：{len(speakers)} 个片段（切分模型已卸载）")

with slot.use(embedding) as loaded_embedding:
    # 与 worker 匹配口径一致：取首个簇的前 3 段时间窗提均值声纹。
    first_cluster = speakers[0].cluster_id
    windows = [
        (segment.start, segment.end)
        for segment in speakers
        if segment.cluster_id == first_cluster
    ][:3]
    vector = loaded_embedding.embed(audio_path, windows)
print(f"声纹：簇 {first_cluster} 取 {len(windows)} 窗，{len(vector)} 维（声纹模型已卸载）")
PY
