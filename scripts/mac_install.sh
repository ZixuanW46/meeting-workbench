#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
PLATFORM="$(uname -s)"

# MW_FORCE_DARWIN 仅供 Linux 自动化测试覆盖 Darwin 分支，生产环境不要设置。
if [[ "${MW_FORCE_DARWIN:-0}" == "1" ]]; then
    PLATFORM="Darwin"
fi

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '[DRY RUN]'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

if [[ "$DRY_RUN" == "1" ]]; then
    cd "$REPO_ROOT"
    echo "DRY RUN：打印 macOS 一键安装命令序列（本机不执行）"
    echo "DRY RUN：依赖齐全时不要求 Homebrew；需补装缺失依赖而没有 Homebrew 时请访问 https://brew.sh/"
    echo "DRY RUN：使用 Homebrew keg-only Python 3.12"
    run brew install python@3.12
    run brew install ffmpeg
    run brew install node
    run "$PYTHON_BIN" -m venv "$REPO_ROOT/.venv"
    run "$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip
    run "$REPO_ROOT/.venv/bin/python" -m pip install -e ".[mac]"
    run "$REPO_ROOT/scripts/download_models.sh"
    echo "DRY RUN：运行 Alembic 数据库迁移"
    run "$REPO_ROOT/.venv/bin/python" -m alembic upgrade head
    echo "DRY RUN：安装并构建前端生产静态文件"
    run npm --prefix apps/web install
    run npm --prefix apps/web run build
    run "$REPO_ROOT/scripts/doctor.sh"
    echo "DRY RUN：如纪要 CLI 未登录，请运行 claude /login 或 codex login。"
    exit 0
fi

if [[ "$PLATFORM" != "Darwin" ]]; then
    echo "非 macOS，跳过 Homebrew、模型下载和本机安装"
    exit 0
fi

# 依赖齐全时不要求 Homebrew；只有需要补装缺失依赖时才检查，缺 brew 也不代装。
require_brew() {
    if command -v brew >/dev/null 2>&1; then
        return 0
    fi
    echo "缺少 $1 且未找到 Homebrew。请访问官方安装页 https://brew.sh/ 安装后重试。" >&2
    exit 1
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    require_brew "$PYTHON_BIN"
    brew list --versions python@3.12 >/dev/null 2>&1 || brew install python@3.12
    # python@3.12 是 keg-only 版本化 formula，可执行文件默认不进 PATH，直接取 brew 前缀。
    BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
    if [[ -x "$BREW_PYTHON" ]]; then
        PYTHON_BIN="$BREW_PYTHON"
    fi
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' || {
    echo "需要 Python 3.12。可设置 PYTHON_BIN 指向正确解释器。" >&2
    exit 1
}

command -v ffmpeg >/dev/null 2>&1 || { require_brew ffmpeg; brew install ffmpeg; }
command -v node >/dev/null 2>&1 || { require_brew node; brew install node; }

cd "$REPO_ROOT"
run "$PYTHON_BIN" -m venv .venv
run "$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip
run "$REPO_ROOT/.venv/bin/python" -m pip install -e ".[mac]"

if [[ ! -x "$REPO_ROOT/.venv/bin/huggingface-cli" ]] && \
    ! command -v huggingface-cli >/dev/null 2>&1; then
    echo "mac 依赖安装后仍未找到 huggingface-cli。" >&2
    exit 1
fi

run "$REPO_ROOT/scripts/download_models.sh"
echo "运行 Alembic 数据库迁移"
run "$REPO_ROOT/.venv/bin/python" -m alembic upgrade head
echo "安装并构建前端生产静态文件"
run npm --prefix apps/web install
run npm --prefix apps/web run build

if ! "$REPO_ROOT/scripts/doctor.sh"; then
    echo "就绪检查尚未全绿；如纪要 CLI 未登录，请运行 claude /login 或 codex login。"
fi
echo "安装完成。服务默认由 launchd 绑定 127.0.0.1:8000。"
