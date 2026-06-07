#!/usr/bin/env bash
# 一键跑全流程: init + 各组 + run-failed 循环 + aggregate
# 第一轮: shard-size/组, 间歇 sleep_first
# 重试: run-failed 循环到 failed = 0 (max_rounds 上限)
#
# 用法:
#   ./backend/scripts/refresh_stock_universe_loop.sh
#   ./backend/scripts/refresh_stock_universe_loop.sh 1000 60 30 30   # 1000/组 60s/30s 30 rounds
#   ./backend/scripts/refresh_stock_universe_loop.sh 800 100 5 30   # 默认

set -e

SHARD_SIZE=${1:-800}
SLEEP_FIRST=${2:-100}
SLEEP_RETRY=${3:-5}
MAX_RETRY_ROUNDS=${4:-30}
PROJ_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJ_ROOT"

echo "=== refresh_stock_universe_loop.sh ==="
echo "  project:        $PROJ_ROOT"
echo "  shard_size:     $SHARD_SIZE (init --shard-size)"
echo "  sleep_first:    ${SLEEP_FIRST}s (第一轮每组)"
echo "  sleep_retry:    ${SLEEP_RETRY}s (run-failed 之间)"
echo "  max_retry:      $MAX_RETRY_ROUNDS rounds (run-failed 循环上限)"
echo ""

# 1. init
echo "============================================="
echo "[1/init] init (拉 code+name, 拆 ${SHARD_SIZE}/组)"
echo "============================================="
python -m backend.scripts.refresh_stock_universe_init --shard-size "$SHARD_SIZE"
echo ""

# 1.5 clean (清空上次 loop 留下的 _failed_codes.json + snapshot)
echo "============================================="
echo "[1.5/clean] 清空昨天 failed + snapshot"
echo "============================================="
python -m backend.scripts.refresh_stock_universe_sharded clean
echo ""

# 2-N. 跑第一轮每组
TOTAL_GROUPS=$(ls reference/stock-universe/groups/ 2>/dev/null | wc -l)
echo "  -> 共 $TOTAL_GROUPS 个组"

for ((g=1; g<=TOTAL_GROUPS; g++)); do
    GROUP_ID=$(printf "%04d" $g)
    echo ""
    echo "============================================="
    echo "[$((g+1))/$((TOTAL_GROUPS+2))] run group $GROUP_ID"
    echo "============================================="
    python -m backend.scripts.refresh_stock_universe_sharded run --group "$GROUP_ID"
    echo "[sleep ${SLEEP_FIRST}s]"
    sleep "$SLEEP_FIRST"
done

# run-failed 循环 (跑到 failed = 0)
# 第一轮跑完到 run-failed 之间不 sleep
FAILED_FILE="reference/stock-universe/_failed_codes.json"

for ((r=1; r<=MAX_RETRY_ROUNDS; r++)); do
    # 读 failed 数量
    COUNT=-1
    if [ -f "$FAILED_FILE" ]; then
        COUNT=$(python -c "
import json
try:
    d = json.load(open('$FAILED_FILE', encoding='utf-8'))
    print(len(d.get('codes') or []))
except Exception:
    print(-1)
")
    else
        COUNT=0
    fi

    if [ "$COUNT" -le 0 ]; then
        echo ""
        echo "============================================="
        echo "[$((TOTAL_GROUPS+2))/$((TOTAL_GROUPS+2))] run-failed: 0 failed, skip"
        echo "============================================="
        break
    fi

    echo ""
    echo "============================================="
    echo "[retry $r/$MAX_RETRY_ROUNDS] run-failed (当前 failed=$COUNT)"
    echo "============================================="
    python -m backend.scripts.refresh_stock_universe_sharded run-failed

    # 检查这一轮跑完
    COUNT_AFTER=-1
    if [ -f "$FAILED_FILE" ]; then
        COUNT_AFTER=$(python -c "
import json
try:
    d = json.load(open('$FAILED_FILE', encoding='utf-8'))
    print(len(d.get('codes') or []))
except Exception:
    print(-1)
")
    else
        COUNT_AFTER=0
    fi

    if [ "$COUNT_AFTER" -le 0 ]; then
        echo "  -> retry $r done, all failed cleared"
        break
    fi
    echo "  -> retry $r done, $COUNT -> $COUNT_AFTER, sleep ${SLEEP_RETRY}s"
    sleep "$SLEEP_RETRY"
done

# aggregate
echo ""
echo "============================================="
echo "[aggregate] 写 sectors_xxx_<n>.json + index.json"
echo "============================================="
python -m backend.scripts.refresh_stock_universe_sharded aggregate
echo ""
echo "=== final status ==="
python -m backend.scripts.refresh_stock_universe_sharded status
