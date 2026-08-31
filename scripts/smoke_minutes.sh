#!/usr/bin/env bash
# Will 手动运行的真机纪要冒烟：用固定逐字稿走真实纪要通道
# （auto：优先 claude，失败回退 codex），验证 CLI 登录与出稿质量。
# 会产生一次真实 CLI 调用；测试与 CI 一律不要跑这个脚本。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python ]]; then
    echo "尚未安装 Python 环境，请先运行 scripts/mac_install.sh。" >&2
    exit 2
fi
if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
    echo "本机没有 claude 或 codex CLI，无法冒烟纪要。" >&2
    exit 2
fi

.venv/bin/python - <<'PY'
from meeting_api.minutes.adapter import AutoMinutesAdapter
from meeting_api.minutes.prompt import build_minutes_prompt

transcript = "\n".join(
    [
        "王芳 00:00-00:06",
        "今天确认两件事，上线时间和负责人分工。",
        "",
        "李雷 00:06-00:12",
        "上线定在周五；我负责发布，回滚预案周四给出。",
        "",
        "王芳 00:12-00:18",
        "好，会后我把纪要发给大家。",
    ]
)
markdown = AutoMinutesAdapter().generate(build_minutes_prompt(transcript))
print(markdown)
PY
echo
echo "纪要冒烟完成：真实 CLI 调用成功。"
