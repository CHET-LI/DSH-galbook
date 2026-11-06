#!/usr/bin/env bash
# 用法：在仓库根目录跑  bash integrations/deepseek-harness/selftest/selftest.sh
# 需要：dsh（npm i -g @deepseek-ai/dsh）、python3。不需要 DeepSeek API key，不花钱。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
W=$(mktemp -d)
PY=${PYTHON:-python3}
cd "$ROOT"
$PY -m galbook demo --books "$W/books" >/dev/null
sed "s#/path/to/books#$W/books#; s#/path/to/play-data#$W/data#; s#/path/to/galbook#$ROOT#g; s#command: python3#command: $PY#" \
  integrations/deepseek-harness/galbook.patch.yml > "$W/galbook.patch.yml"
export DEEPSEEK_API_KEY=sk-fake-local DEEPSEEK_BASE_URL=http://127.0.0.1:9911
run() {  # $1 = mcp|cli
  $PY integrations/deepseek-harness/selftest/mock_model.py --mode "$1" --books "$W/books" --data "$W/data" --log "$W/$1.log" & M=$!
  sleep 1
  if [ "$1" = mcp ]; then dsh headless --patch "$W/galbook.patch.yml" --approval-policy never "玩一下" > "$W/$1.out" 2>"$W/$1.err" || true
  else dsh headless --approval-policy never --add-dir "$W" "用 galbook 玩一下" > "$W/$1.out" 2>"$W/$1.err" || true; fi
  kill $M; wait $M 2>/dev/null || true
  echo "== $1：dsh 最终输出"; head -8 "$W/$1.out"
  echo "== $1：每一步（galbook 工具数 / 技能可见 / 第几步 / 上一步结果开头）"
  $PY - "$W/$1.log" <<'PY'
import json, sys
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    print(" ", len(d["galbook_tools"]), d["skill_listed"], d["step"], (d["last_result"] or "")[:70].replace("\n", " | "))
PY
}
run mcp
run cli
echo "== 玩家档案："; ls "$W/data/fog-harbor"
