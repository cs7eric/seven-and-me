#!/usr/bin/env bash
# 一键跑全流程: init + N 组 + run-failed + aggregate
# 第一轮: shard-size/组, 间歇 sleep_first
# 重试 (run-failed): 间歇 sleep_retry
#
# 用法:
#   ./backend/scripts/refresh_stock_universe_loop.sh
#   ./backend/scripts/refresh_stock_universe_loop.sh 1000 60 150   # 1000/组 60s/150s
#   ./backend/scripts/refresh_stock_universe_loop.sh 600 30 5      # 默认

set -e

SHARD_SIZE=${1:-600}
SLEEP_FIRST=${2:-30}
SLEEP_RETRY=${3:-5}
PROJ_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJ_ROOT"

echo "=== refresh_stock_universe_loop.sh ==="
echo "  project:       $PROJ_ROOT"
echo "  shard_size:    $SHARD_SIZE (init --shard-size)"
echo "  sleep_first:   ${SLEEP_FIRST}s (第一轮每组)"
echo "  sleep_retry:   ${SLEEP_RETRY}s (run-failed 之前/之后)"
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

echo "[sleep ${SLEEP_FIRST}s]"
sleep "$SLEEP_FIRST"

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

# 重试 (run-failed 之前 间歇 150s 让限流恢复)
echo ""
echo "============================================="
echo "[$((TOTAL_GROUPS+2))/$((TOTAL_GROUPS+2))] sleep ${SLEEP_RETRY}s before run-failed"
echo "============================================="
sleep "$SLEEP_RETRY"

python -m backend.scripts.refresh_stock_universe_sharded run-failed
echo ""
echo "[sleep ${SLEEP_RETRY}s]"
sleep "$SLEEP_RETRY"

# aggregate
python -m backend.scripts.refresh_stock_universe_sharded aggregate
echo ""
echo "=== final status ==="
python -m backend.scripts.refresh_stock_universe_sharded status
