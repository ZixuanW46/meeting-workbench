#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '[DRY RUN] %q' "$1"
        shift
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY RUN：检查 macOS 与 Python 3.12"
    echo "DRY RUN：若缺少 Python 3.12，将通过 Homebrew 安装 python@3.12"
else
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "mac_install.sh 只支持 macOS；Linux 请勿执行真实安装。" >&2
        exit 1
    fi
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        if ! command -v brew >/dev/null 2>&1; then
            echo "未找到 Homebrew。请先安装 Homebrew，再重新运行本脚本。" >&2
            exit 1
        fi
        brew list --versions python@3.12 >/dev/null 2>&1 || brew install python@3.12
        # python@3.12 是 keg-only 版本化 formula，可执行文件不进 PATH，直接取 brew 前缀。
        BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
        if [[ -x "$BREW_PYTHON" ]]; then
            PYTHON_BIN="$BREW_PYTHON"
        fi
    fi
    "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' || {
        echo "需要 Python 3.12。可设置 PYTHON_BIN 指向正确解释器。" >&2
        exit 1
    }
fi

cd "$REPO_ROOT"
run "$PYTHON_BIN" -m venv .venv
run "$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip
run "$REPO_ROOT/.venv/bin/python" -m pip install -e ".[mac]"
if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY RUN：运行 Alembic 数据库迁移"
else
    echo "运行 Alembic 数据库迁移"
fi
run "$REPO_ROOT/.venv/bin/python" -m alembic upgrade head
if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY RUN：安装并构建前端静态文件"
else
    echo "安装并构建前端静态文件"
fi
run npm --prefix apps/web install
run npm --prefix apps/web run build

echo "安装完成。服务默认由 launchd 绑定 127.0.0.1:8000。"
