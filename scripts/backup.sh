#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MW_DATA_DIR="${MW_DATA_DIR:-$REPO_ROOT/data}"
BACKUP_ROOT="${BACKUP_ROOT:-$REPO_ROOT/backups}"

if [[ ! -d "$MW_DATA_DIR" ]]; then
    echo "数据目录不存在：$MW_DATA_DIR" >&2
    exit 1
fi

umask 077
mkdir -p "$BACKUP_ROOT"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/meeting-workbench-backup.XXXXXX")"
cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT
mkdir -p "$STAGING_DIR/data"

# 先复制普通数据；模型权重和 SQLite 临时文件不进入备份。
tar \
    --exclude='./models' \
    --exclude='./models/*' \
    --exclude='./meeting-workbench.sqlite3' \
    --exclude='./meeting-workbench.sqlite3-wal' \
    --exclude='./meeting-workbench.sqlite3-shm' \
    -C "$MW_DATA_DIR" -cf - . | tar -C "$STAGING_DIR/data" -xf -

DATABASE_PATH="$MW_DATA_DIR/meeting-workbench.sqlite3"
if [[ -f "$DATABASE_PATH" ]]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DATABASE_PATH" ".backup '$STAGING_DIR/data/meeting-workbench.sqlite3'"
    else
        echo "警告：未找到 sqlite3，数据库将以文件副本方式备份。" >&2
        cp "$DATABASE_PATH" "$STAGING_DIR/data/meeting-workbench.sqlite3"
    fi
fi

ARCHIVE="$BACKUP_ROOT/meeting-workbench-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -C "$STAGING_DIR" -czf "$ARCHIVE" data
# ${} 花括号必须保留：macOS 系统 bash 3.2 会把紧跟的全角字符首字节并进变量名。
echo "备份完成：${ARCHIVE}（已排除 data/models 模型权重）"
