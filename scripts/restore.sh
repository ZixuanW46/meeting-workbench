#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "用法：$0 <备份.tar.gz> <新的数据目录>" >&2
    exit 2
fi

ARCHIVE="$1"
TARGET_DIR="$2"
if [[ ! -f "$ARCHIVE" ]]; then
    echo "备份文件不存在：$ARCHIVE" >&2
    exit 1
fi
if [[ -e "$TARGET_DIR" ]]; then
    echo "恢复目标必须是尚不存在的新目录：$TARGET_DIR" >&2
    exit 1
fi

while IFS= read -r member; do
    case "$member" in
        data|data/*) ;;
        *)
            echo "备份包含非法路径：$member" >&2
            exit 1
            ;;
    esac
    if [[ "/$member/" == *"/../"* ]]; then
        echo "备份包含越界路径：$member" >&2
        exit 1
    fi
done < <(tar -tzf "$ARCHIVE")

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/meeting-workbench-restore.XXXXXX")"
cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT
tar -xzf "$ARCHIVE" -C "$STAGING_DIR"
if [[ ! -d "$STAGING_DIR/data" ]]; then
    echo "备份中缺少 data 目录" >&2
    exit 1
fi
mkdir -p "$(dirname "$TARGET_DIR")"
mv "$STAGING_DIR/data" "$TARGET_DIR"
echo "恢复完成：$TARGET_DIR"
