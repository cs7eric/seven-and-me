"""一键跑完整 stock_universe refresh loop (Python 版, 替代 .ps1).

行为与 ``refresh_stock_universe_loop.ps1`` 完全一致, 但不需要 PowerShell:
  1. ``init``        — 拉 code+name, 按 shard_size 拆 groups/
  1.5 ``clean``      — 清空上次 loop 留下的 _failed_codes.json + 当日 snapshot
  2-N  各组          — 循环调 sharded run --group NNNN, 每组后 sleep sleep_first
  retry ``run-failed`` — 反复到 failed_codes=0, 最多 max_retry_rounds 轮
  finally ``aggregate`` + ``status``

被 ``stock_universe_scheduler`` 用 subprocess 调, 进度输出到 stdout
(由调用方 capture 到 ``reference/stock-universe/_logs/<date>-slot-<HHMM>.log``).

用法 (CLI):
  python -m backend.scripts.refresh_stock_universe_loop
  python -m backend.scripts.refresh_stock_universe_loop --shard-size 1000 --sleep-first 60
  python -m backend.scripts.refresh_stock_universe_loop --max-retry-rounds 30
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from backend.config.settings import BASE_DIR, STOCK_UNIVERSE_DIR

logger = logging.getLogger(__name__)

GROUPS_DIR = STOCK_UNIVERSE_DIR / "groups"
FAILED_FILE = STOCK_UNIVERSE_DIR / "_failed_codes.json"
DEFAULT_SHARD_SIZE = 800
DEFAULT_SLEEP_FIRST = 120
DEFAULT_SLEEP_RETRY = 5
DEFAULT_MAX_RETRY_ROUNDS = 5


def _read_failed_count() -> int:
    if not FAILED_FILE.exists():
        return 0
    try:
        data = json.loads(FAILED_FILE.read_text(encoding="utf-8"))
        return len(data.get("codes") or [])
    except Exception:
        return -1


def _run_step(name: str, args: list[str]) -> int:
    """subprocess 调一个子脚本 (跟 ps1 里 ``python -m ...`` 行为一致). 返回 returncode."""
    cmd = [sys.executable, "-m"] + args
    print(f"  $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(BASE_DIR))
    print(f"  -> {name} exit={proc.returncode}", flush=True)
    return proc.returncode


def run_loop(
    shard_size: int = DEFAULT_SHARD_SIZE,
    sleep_first: int = DEFAULT_SLEEP_FIRST,
    sleep_retry: int = DEFAULT_SLEEP_RETRY,
    max_retry_rounds: int = DEFAULT_MAX_RETRY_ROUNDS,
) -> int:
    """跑完整 loop. 返回 exit code (0=success, 非 0=failed)."""
    print("=== refresh_stock_universe_loop.py ===", flush=True)
    print(f"  project:        {BASE_DIR}")
    print(f"  shard_size:     {shard_size} (init --shard-size)")
    print(f"  sleep_first:    {sleep_first}s (第一轮每组)")
    print(f"  sleep_retry:    {sleep_retry}s (run-failed 之间)")
    print(f"  max_retry:      {max_retry_rounds} rounds (run-failed 循环上限)")
    print()

    # 1. init
    print("=============================================", flush=True)
    print(f"[1/init] 拉 code+name, 拆 {shard_size}/组")
    print("=============================================", flush=True)
    rc = _run_step("init", ["backend.scripts.refresh_stock_universe_init", "--shard-size", str(shard_size)])
    if rc != 0:
        print(f"ERR: init failed (exit={rc})", flush=True)
        return 1
    print()

    # 1.5 clean
    print("=============================================", flush=True)
    print("[1.5/clean] 清空昨天 failed + snapshot")
    print("=============================================", flush=True)
    rc = _run_step("clean", ["backend.scripts.refresh_stock_universe_sharded", "clean"])
    if rc != 0:
        print(f"ERR: clean failed (exit={rc})", flush=True)
        return 1
    print()

    # 2-N. 跑第一轮每组
    group_files = sorted(GROUPS_DIR.glob("*.json"))
    total = len(group_files)
    print(f"  -> 共 {total} 个组", flush=True)
    for i, group_file in enumerate(group_files):
        group_id = group_file.stem
        print()
        print("=============================================", flush=True)
        print(f"[{i + 2}/{total + 2}] run group {group_id}")
        print("=============================================", flush=True)
        rc = _run_step(f"run {group_id}", ["backend.scripts.refresh_stock_universe_sharded", "run", "--group", group_id])
        if rc != 0:
            print(f"  WARN: group {group_id} exit={rc}, 继续下一组", flush=True)
        print(f"[sleep {sleep_first}s]", flush=True)
        time.sleep(sleep_first)

    # run-failed 循环
    for r in range(1, max_retry_rounds + 1):
        count = _read_failed_count()
        if count <= 0:
            print()
            print("=============================================", flush=True)
            print(f"[{total + 2}/{total + 2}] run-failed: 0 failed, skip")
            print("=============================================", flush=True)
            break
        print()
        print("=============================================", flush=True)
        print(f"[retry {r}/{max_retry_rounds}] run-failed (当前 failed={count})")
        print("=============================================", flush=True)
        rc = _run_step(f"retry {r}", ["backend.scripts.refresh_stock_universe_sharded", "run-failed"])
        count_after = _read_failed_count()
        if count_after <= 0:
            print(f"  -> retry {r} done, all failed cleared", flush=True)
            break
        if count_after >= count:
            print(f"  -> retry {r} done, failed not decreasing ({count} -> {count_after}), sleep {sleep_retry}s")
        else:
            print(f"  -> retry {r} done, {count} -> {count_after}, sleep {sleep_retry}s")
        time.sleep(sleep_retry)

    # aggregate
    print()
    print("=============================================", flush=True)
    print("[aggregate] 写 sectors_xxx_<n>.json + index.json")
    print("=============================================", flush=True)
    rc = _run_step("aggregate", ["backend.scripts.refresh_stock_universe_sharded", "aggregate"])
    if rc != 0:
        print(f"ERR: aggregate failed (exit={rc})", flush=True)
        return 1
    print()

    # status
    print("=== final status ===", flush=True)
    _run_step("status", ["backend.scripts.refresh_stock_universe_sharded", "status"])

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="一键跑完整 stock_universe refresh loop (Python 版)")
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE,
                        help=f"每组大小, 默认 {DEFAULT_SHARD_SIZE} (5530/800=7 组)")
    parser.add_argument("--sleep-first", type=int, default=DEFAULT_SLEEP_FIRST,
                        help=f"第一轮每组后 sleep (秒), 默认 {DEFAULT_SLEEP_FIRST}")
    parser.add_argument("--sleep-retry", type=int, default=DEFAULT_SLEEP_RETRY,
                        help=f"run-failed 之间 sleep (秒), 默认 {DEFAULT_SLEEP_RETRY}")
    parser.add_argument("--max-retry-rounds", type=int, default=DEFAULT_MAX_RETRY_ROUNDS,
                        help=f"run-failed 最多跑几轮, 默认 {DEFAULT_MAX_RETRY_ROUNDS}")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    rc = run_loop(
        shard_size=args.shard_size,
        sleep_first=args.sleep_first,
        sleep_retry=args.sleep_retry,
        max_retry_rounds=args.max_retry_rounds,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
