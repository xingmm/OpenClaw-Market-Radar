#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[MOS] setup check started"

err=0
warn=0

check_file() {
  local p="$1"
  if [[ -f "$p" ]]; then
    echo "[OK] file: $p"
  else
    echo "[ERR] missing file: $p"
    err=1
  fi
}

check_dir() {
  local p="$1"
  if [[ -d "$p" ]]; then
    echo "[OK] dir: $p"
  else
    echo "[ERR] missing dir: $p"
    err=1
  fi
}

check_cmd() {
  local c="$1"
  if command -v "$c" >/dev/null 2>&1; then
    echo "[OK] command: $c"
  else
    echo "[ERR] command not found: $c"
    err=1
  fi
}

check_cmd python3

PY_CMD="python3"
if [[ -x ".venv/bin/python" ]]; then
  PY_CMD=".venv/bin/python"
  echo "[INFO] using project venv: .venv/bin/python"
fi

check_dir "scripts"
check_dir "MOS-TIB-SKILL"
check_dir "MOS-TIB-SKILL/references"
check_dir "MOS-TIB-SKILL/references/skills"
check_dir "OpenClaw/工作流暗号"
check_dir "OpenClaw/市场洞察报告/Raw_Data"
check_dir "OpenClaw/我的持仓与关注点和投资偏好/ai建议"

check_file "README.md"
check_file "RUNBOOK.md"
check_file "requirements.txt"
check_file ".env.example"
check_file "OpenClaw/工作流暗号/投研中台暗号.md"
check_file "OpenClaw/工作流暗号/投资雷达与策略简报暗号.md"
check_file "OpenClaw/我的持仓与关注点和投资偏好/我的持仓.template.md"
check_file "OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.template.md"
check_file "OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.template.md"
check_file "MOS-TIB-SKILL/references/skills/个股研究/SKILL.md"
check_file "MOS-TIB-SKILL/references/skills/宏观洞察/SKILL.md"
check_file "MOS-TIB-SKILL/references/skills/快讯雷达/SKILL.md"
check_file "MOS-TIB-SKILL/references/skills/市场洞察编排/SKILL.md"

# Python deps check
if "$PY_CMD" - << 'PY' >/dev/null 2>&1
import requests, feedparser
print("ok")
PY
then
  echo "[OK] python deps: requests, feedparser"
else
  echo "[ERR] missing python deps: requests/feedparser"
  echo "      run:"
  echo "        python3 -m venv .venv"
  echo "        source .venv/bin/activate"
  echo "        pip install -r requirements.txt"
  err=1
fi

# Private runtime files (expected to be local only)
for f in \
  "OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md" \
  "OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.md" \
  "OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.md"
do
  if [[ -f "$f" ]]; then
    echo "[OK] private runtime file exists: $f"
  else
    echo "[WARN] private runtime file missing: $f"
    warn=1
  fi
done

if [[ "$warn" -eq 1 ]]; then
  cat <<'MSG'
[HINT] create local runtime files from templates:
  cp OpenClaw/我的持仓与关注点和投资偏好/我的持仓.template.md OpenClaw/我的持仓与关注点和投资偏好/我的持仓.md
  cp OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.template.md OpenClaw/我的持仓与关注点和投资偏好/我的投资状态卡.md
  cp OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.template.md OpenClaw/我的持仓与关注点和投资偏好/我的关联偏好.md
MSG
fi

if [[ "$err" -eq 0 ]]; then
  echo "[PASS] setup check passed"
  exit 0
fi

echo "[FAIL] setup check failed"
exit 1
