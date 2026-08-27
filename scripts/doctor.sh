#!/usr/bin/env bash
# 检查本机是否具备转写与纪要生成条件；只读探测，不安装或下载任何内容。
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR=${MW_DATA_DIR:-"$REPO_ROOT/data"}
MODELS_DIR="$DATA_DIR/models"

if [[ ${DRY:-0} == "1" || ${DRY_RUN:-0} == "1" ]]; then
  echo "[DRY RUN] 将执行以下只读就绪检查："
  echo "- ffmpeg 是否在 PATH"
  echo "- ASR 模型：$MODELS_DIR/qwen3-asr-mlx/config.json"
  echo "- 说话人切分模型：$MODELS_DIR/sherpa-onnx/segmentation.onnx"
  echo "- 声纹模型：$MODELS_DIR/sherpa-onnx/embedding.onnx"
  echo "- Claude CLI 是否在 PATH（登录状态以生成纪要时为准）"
  echo "- Codex CLI 是否在 PATH（登录状态以生成纪要时为准）"
  echo "- 数据目录所在磁盘的剩余空间"
  exit 0
fi

ok() {
  echo "✓ $1"
}

missing() {
  echo "✗ $1"
}

check_file() {
  local label=$1
  local path=$2
  if [[ -f "$path" ]]; then
    ok "$label已就绪"
    return 0
  fi
  missing "$label缺失：$path"
  return 1
}

# 只查 CLI 是否在 PATH：claude /doctor、codex whoami 需要交互终端，
# 在脚本/launchd 环境必然误报未登录。登录问题由生成纪要时的真实调用暴露
# （失败停在 PARTIAL_READY，可在界面重试），不在这里猜测。
check_cli() {
  local label=$1
  local executable=$2
  if command -v "$executable" >/dev/null 2>&1; then
    ok "$label 已安装（登录状态以生成纪要时为准）"
    return 0
  fi
  missing "$label 未在 PATH 中找到"
  return 1
}

transcription_ready=1
minutes_ready=1

echo "meeting-workbench 系统就绪检测"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg 已安装"
else
  missing "ffmpeg 未在 PATH 中找到"
  transcription_ready=0
fi

check_file "ASR 模型" "$MODELS_DIR/qwen3-asr-mlx/config.json" || transcription_ready=0
check_file "说话人切分模型" "$MODELS_DIR/sherpa-onnx/segmentation.onnx" || transcription_ready=0
check_file "声纹模型" "$MODELS_DIR/sherpa-onnx/embedding.onnx" || transcription_ready=0

claude_ready=0
codex_ready=0
check_cli "Claude CLI" claude && claude_ready=1
check_cli "Codex CLI" codex && codex_ready=1
if [[ $claude_ready == 0 && $codex_ready == 0 ]]; then
  minutes_ready=0
fi

disk_path=$DATA_DIR
while [[ ! -e "$disk_path" ]]; do
  disk_path=$(dirname "$disk_path")
done
echo "磁盘剩余空间：$(df -h "$disk_path" | awk 'NR == 2 {print $4}')"

if [[ $transcription_ready == 1 ]]; then
  ok "转写已就绪"
else
  missing "转写未就绪，请按上面的缺失项补齐"
fi
if [[ $minutes_ready == 1 ]]; then
  ok "纪要生成已就绪"
else
  missing "纪要生成未就绪，请安装 Claude CLI 或 Codex CLI（并各自登录）"
fi

if [[ $transcription_ready == 1 && $minutes_ready == 1 ]]; then
  exit 0
fi
exit 1
