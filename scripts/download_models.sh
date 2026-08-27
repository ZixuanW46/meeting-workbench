#!/usr/bin/env bash
# 下载 M16 使用的公开模型；不登录 Hugging Face，也不读取或传递 token。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"
PLATFORM="$(uname -s)"

# MW_FORCE_DARWIN 仅供 Linux 自动化测试覆盖 Darwin 分支，生产环境不要设置。
if [[ "${MW_FORCE_DARWIN:-0}" == "1" ]]; then
    PLATFORM="Darwin"
fi

if [[ "$PLATFORM" != "Darwin" && "$DRY_RUN" != "1" ]]; then
    echo "非 macOS，跳过模型下载"
    exit 0
fi

DATA_DIR="${MW_DATA_DIR:-$REPO_ROOT/data}"
MODELS_DIR="$DATA_DIR/models"
ASR_DIR="$MODELS_DIR/qwen3-asr-mlx"
SHERPA_DIR="$MODELS_DIR/sherpa-onnx"
SEGMENTATION_MODEL="$SHERPA_DIR/segmentation.onnx"
EMBEDDING_MODEL="$SHERPA_DIR/embedding.onnx"
SEGMENTATION_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '[DRY RUN]'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

run mkdir -p "$ASR_DIR" "$SHERPA_DIR"

if [[ -f "$ASR_DIR/config.json" ]]; then
    echo "ASR 模型已存在，跳过下载：$ASR_DIR"
else
    HF_CLI="$REPO_ROOT/.venv/bin/huggingface-cli"
    if [[ ! -x "$HF_CLI" ]]; then
        HF_CLI="huggingface-cli"
    fi
    if [[ "$DRY_RUN" != "1" ]] && ! command -v "$HF_CLI" >/dev/null 2>&1; then
        echo "未找到 huggingface-cli，请先安装仓库的 mac 依赖。" >&2
        exit 1
    fi
    # 尊重调用者已有的 HF_ENDPOINT；公开仓库无需 login 或 token。
    run "$HF_CLI" download mlx-community/Qwen3-ASR-1.7B-8bit --local-dir "$ASR_DIR"
fi

cleanup_dir=""
cleanup_file=""
cleanup() {
    if [[ -n "$cleanup_file" && -f "$cleanup_file" ]]; then
        rm -f -- "$cleanup_file"
    fi
    if [[ -n "$cleanup_dir" ]]; then
        case "$cleanup_dir" in
            "$MODELS_DIR"/.model-download.*) rm -rf -- "$cleanup_dir" ;;
        esac
    fi
}
trap cleanup EXIT

if [[ -f "$SEGMENTATION_MODEL" ]]; then
    echo "说话人切分模型已存在，跳过下载：$SEGMENTATION_MODEL"
elif [[ "$DRY_RUN" == "1" ]]; then
    DRY_TEMP="$MODELS_DIR/.model-download.tmp"
    run mkdir -p "$DRY_TEMP/extracted"
    run curl --fail --location "$SEGMENTATION_URL" --output "$DRY_TEMP/segmentation.tar.bz2"
    run tar -xjf "$DRY_TEMP/segmentation.tar.bz2" -C "$DRY_TEMP/extracted"
    run install -m 0644 "$DRY_TEMP/extracted/model.onnx" "$SEGMENTATION_MODEL"
    run rm -rf "$DRY_TEMP"
else
    cleanup_dir="$(mktemp -d "$MODELS_DIR/.model-download.XXXXXX")"
    archive="$cleanup_dir/segmentation.tar.bz2"
    extracted="$cleanup_dir/extracted"
    mkdir -p "$extracted"
    curl --fail --location "$SEGMENTATION_URL" --output "$archive"
    tar -xjf "$archive" -C "$extracted"
    source_model="$(find "$extracted" -type f -name model.onnx -print -quit)"
    if [[ -z "$source_model" ]]; then
        echo "切分模型归档中未找到 model.onnx。" >&2
        exit 1
    fi
    # 转换模型源自 pyannote segmentation 3.0；原始权重按 MIT 许可证发布。
    install -m 0644 "$source_model" "$SEGMENTATION_MODEL"
    cleanup
    cleanup_dir=""
fi

if [[ -f "$EMBEDDING_MODEL" ]]; then
    echo "声纹模型已存在，跳过下载：$EMBEDDING_MODEL"
elif [[ "$DRY_RUN" == "1" ]]; then
    run curl --fail --location "$EMBEDDING_URL" --output "$EMBEDDING_MODEL"
else
    cleanup_file="$SHERPA_DIR/.embedding.onnx.download.$$"
    curl --fail --location "$EMBEDDING_URL" --output "$cleanup_file"
    mv "$cleanup_file" "$EMBEDDING_MODEL"
    cleanup_file=""
fi

echo "模型准备完成：$MODELS_DIR"
