#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_PLIST="$REPO_ROOT/scripts/launchd/com.will.meeting-workbench.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/com.will.meeting-workbench.plist"
DRY_RUN="${DRY_RUN:-0}"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY RUN：将生成 $TARGET_PLIST"
    echo "DRY RUN：将执行 launchctl bootstrap gui/$UID $TARGET_PLIST"
    exit 0
fi
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "launchd 仅支持 macOS；Linux 请使用 DRY_RUN=1。" >&2
    exit 1
fi
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    echo "尚未安装 Python 环境，请先运行 scripts/mac_install.sh。" >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO_ROOT/data/logs"
sed -e "s|__REPO_ROOT__|$REPO_ROOT|g" -e "s|__HOME__|$HOME|g" "$SOURCE_PLIST" > "$TARGET_PLIST"
launchctl bootout "gui/$UID/com.will.meeting-workbench" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$TARGET_PLIST"
echo "launchd 已安装；服务监听 http://127.0.0.1:8000。"
