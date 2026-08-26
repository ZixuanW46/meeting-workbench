#!/usr/bin/env bash
# 等效于 `make test`，给没有 make 的环境用。
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/python -m pytest
(cd apps/web && npm test)
