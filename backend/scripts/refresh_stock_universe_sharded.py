"""
分批拉取 stock_universe (单次跑一组, 跑完即退出, 进程结束).

数据流:
  1. init 阶段 (refresh_stock_universe_init.py) 拉 code+name, 拆 1000/组写到 groups/0001.json ...
  2. 每次 run --group NNNN 读 groups/NNNN.json, 调 eltdx helpers.stock_topics(code) 拿 topics
  3. 跑完写 snapshot, 失败 code 进 _failed_codes.json
  4. 进程退出

用法:
  python -m backend.scripts.refresh_stock_universe_sharded --group 0001
  python -m backend.scripts.refresh_stock_universe_sharded --group 0002 --workers 64
  python -m backend.scripts.refresh_stock_universe_sharded --failed                # 只重跑失败的
  python -m backend.scripts.refresh_stock_universe_sharded --status                # 看进度
  python -m backend.scripts.refresh_stock_universe_sharded --aggregate             # 聚合 sectors.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from backend.config.settings import STOCK_UNIVERSE_DIR
from backend.services.stock import stock_universe_service as svc

logger = logging.getLogger(__name__)

FAILED_FILE = STOCK_UNIVERSE_DIR / "_failed_codes.json"
SNAPSHOT_FILE = STOCK_UNIVERSE_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.json"
GROUPS_DIR = STOCK_UNIVERSE_DIR / "groups"
PROGRESS_FILE = STOCK_UNIVERSE_DIR / "_progress.json"

DEFAULT_WORKERS = 64
DEFAULT_POOL_SIZE = 8
DEFAULT_TIMEOUT = 6.0


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: {path} corrupted: {exc}, use default")
        return default


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# snapshot 合并
# ---------------------------------------------------------------------------


def _read_snapshot() -> dict:
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ensure_snapshot() -> dict:
    data = _read_snapshot()
    if not data or data.get("version") != svc.DAILY_VERSION:
        return {
            "version": svc.DAILY_VERSION,
            "trading_day": datetime.now().strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().isoformat(),
            "source": "sharded_pull",
            "stock_count": 0,
            "empty_count": 0,
            "stocks": [],
        }
    return data


def _write_snapshot(data: dict) -> None:
    data["fetched_at"] = datetime.now().isoformat()
    _atomic_write(SNAPSHOT_FILE, data)


def merge_into_snapshot(results: dict[str, list], label: str) -> int:
    """合并到 snapshot. 返回本组实际写入的 code 数 (含失败)."""
    data = _ensure_snapshot()
    by_code = {s["code"]: s for s in data["stocks"]}

    name_map = _read_codes_name_map()
    for code, topics in results.items():
        industry = None
        for t in topics:
            reason = t.get("reason") or ""
            if industry is None:
                industry = svc.extract_industry_from_reason(reason)
        entry = by_code.get(code, {
            "code": code,
            "name": name_map.get(code, ""),
            "industry": "",
            "topics": [],
        })
        if topics:
            entry["industry"] = industry or entry.get("industry", "")
            entry["topics"] = topics
        else:
            entry["industry"] = entry.get("industry", "")
            entry["topics"] = []
        by_code[code] = entry

    data["stocks"] = list(by_code.values())
    data["stock_count"] = len(data["stocks"])
    data["empty_count"] = sum(1 for s in data["stocks"] if not s.get("topics"))
    data["source"] = f"sharded_pull (last: {label})"
    _write_snapshot(data)
    return len(results)


# ---------------------------------------------------------------------------
# failed 列表 (跨 group 累积)
# ---------------------------------------------------------------------------


def load_failed() -> list[str]:
    data = _read_json(FAILED_FILE, {"codes": []})
    return list(data.get("codes") or [])


def save_failed(codes: list[str]) -> None:
    _atomic_write(FAILED_FILE, {
        "trading_day": datetime.now().strftime("%Y-%m-%d"),
        "count": len(codes),
        "codes": sorted(set(codes)),
    })


def add_failed(new_failed: list[str]) -> list[str]:
    """累加到 failed 列表并写盘. 自动 dedup."""
    cur = load_failed()
    cur_set = set(cur)
    before = len(cur_set)
    # 防御: dedup 入参
    new_set = set(new_failed)
    cur_set.update(new_set)
    after = len(cur_set)
    if after > before or len(new_set) != len(new_failed):
        print(f"  [failed dedup] before={before}, add={len(new_failed)} unique={len(new_set)}, after={after}")
    save_failed(list(cur_set))
    return list(cur_set)


def mark_failed_as_done(codes: list[str]) -> list[str]:
    """从 failed 列表移除 (这次跑通了)."""
    cur = load_failed()
    cur_set = set(cur) - set(codes)
    save_failed(list(cur_set))
    return list(cur_set)


# ---------------------------------------------------------------------------
# progress (group 完成情况)
# ---------------------------------------------------------------------------


def _read_progress() -> dict:
    return _read_json(PROGRESS_FILE, {"trading_day": datetime.now().strftime("%Y-%m-%d"),
                                       "done_groups": [], "failed_count": 0, "updated_at": None})


def mark_group_done(group_id: str, ok: int, failed: int) -> None:
    p = _read_progress()
    done = list(p.get("done_groups") or [])
    if group_id not in done:
        done.append(group_id)
    p["done_groups"] = done
    p["updated_at"] = datetime.now().isoformat()
    _atomic_write(PROGRESS_FILE, p)


# ---------------------------------------------------------------------------
# codes 名字 map (hot 读)
# ---------------------------------------------------------------------------


def _read_codes_name_map() -> dict[str, str]:
    data = _read_json(STOCK_UNIVERSE_DIR / "_codes.json", None)
    if not data:
        return {}
    return {c["full_code"]: c.get("name", "") for c in data.get("codes", [])}


# ---------------------------------------------------------------------------
# 跑一组
# ---------------------------------------------------------------------------


def run_shard(codes: list[str], workers: int, pool_size: int, timeout: float) -> dict[str, list]:
    """跑一组 codes, 返回 {code: topics_list}. 失败 code 返回空 list (也算)."""
    out: dict[str, list] = {}
    # dedup 入参, 防御性
    if not codes:
        return out
    deduped_codes: list[str] = list(dict.fromkeys(codes))
    if len(deduped_codes) < len(codes):
        print(f"  [dedup] 输入 {len(codes)} -> {len(deduped_codes)} unique")
    codes = deduped_codes

    client = svc._connect(pool_size=pool_size, timeout=timeout)
    try:
        client.connect()
    except Exception as exc:
        print(f"  ! connect 失败: {exc}, 全组标失败")
        return {c: [] for c in codes}
    try:
        with ThreadPoolExecutor(max_workers=min(workers, len(codes)),
                                thread_name_prefix="shard") as executor:
            # dict by code 保证 future 唯一 (即使 codes 有重复, dict 也会覆盖)
            futures: dict = {}
            for code in codes:
                if code in futures:
                    continue  # dedup 防御
                futures[executor.submit(svc._fetch_topics, client, code)] = code
            for future in as_completed(futures):
                code = futures[future]
                try:
                    topics = future.result() or []
                except Exception as exc:
                    logger.debug("%s err: %s", code, exc)
                    topics = []
                out[code] = topics
    finally:
        client.close()
    # 防御性: out 内部去重 (理论上 dict 不会重)
    if len(out) != len(set(out.keys())):
        print(f"  [dedup WARN] out 内部有重复 {len(out)} -> {len(set(out.keys()))}")
    return out


# ---------------------------------------------------------------------------
# 加载 group 文件
# ---------------------------------------------------------------------------


def load_group_codes(group_id: str) -> list[str]:
    """从 groups/NNNN.json 读 codes. group_id 形如 '0001'."""
    path = GROUPS_DIR / f"{group_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"group file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [c["full_code"] for c in data.get("codes", [])]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_status(args):
    p = _read_progress()
    failed = load_failed()
    snap = _ensure_snapshot()
    print(f"trading_day:    {p.get('trading_day')}")
    print(f"snapshot file:  {SNAPSHOT_FILE}")
    print(f"  stocks:       {snap['stock_count']} (empty: {snap['empty_count']})")
    print(f"groups done:    {len(p.get('done_groups') or [])}")
    done = p.get('done_groups') or []
    if done:
        print(f"  last 5:       {done[-5:]}")
    print(f"failed codes:   {len(failed)}")
    if failed:
        print(f"  first 10:     {failed[:10]}")


def cmd_run_group(args):
    group_id = args.group
    codes = load_group_codes(group_id)
    print(f"[run] group {group_id}: {len(codes)} codes (workers={args.workers} pool={args.pool_size} timeout={args.timeout})")

    t0 = time.time()
    results = run_shard(codes, args.workers, args.pool_size, args.timeout)
    elapsed = time.time() - t0
    ok = sum(1 for v in results.values() if v)
    fail = len(results) - ok
    speed = ok / max(elapsed, 0.1)
    print(f"  done: ok={ok} fail={fail} in {elapsed:.1f}s ({speed:.0f}/s)")

    # 写 snapshot (含失败)
    n = merge_into_snapshot(results, f"group {group_id}")
    print(f"  snapshot: merged {n} codes into {SNAPSHOT_FILE}")

    # failed 累加 + 标 group done
    failed_codes = [c for c, v in results.items() if not v]
    add_failed(failed_codes)
    mark_group_done(group_id, ok=ok, failed=fail)
    print(f"  total failed in _failed_codes.json: {len(load_failed())}")
    print(f"[run] exit.")


def cmd_run_failed(args):
    failed = load_failed()
    if not failed:
        print("[run-failed] no failed codes. exit.")
        return
    print(f"[run-failed] 重试 {len(failed)} 个 failed codes (workers={args.workers})")

    t0 = time.time()
    results = run_shard(failed, args.workers, args.pool_size, args.timeout)
    elapsed = time.time() - t0
    ok = sum(1 for v in results.values() if v)
    still_fail = [c for c, v in results.items() if not v]
    speed = ok / max(elapsed, 0.1)
    print(f"  done: ok={ok} still_fail={len(still_fail)} in {elapsed:.1f}s ({speed:.0f}/s)")

    merge_into_snapshot(results, "retry-failed")
    # 把这次跑通的从 failed 列表移除
    success = [c for c, v in results.items() if v]
    mark_failed_as_done(success)
    print(f"  total failed in _failed_codes.json: {len(load_failed())}")
    print(f"[run-failed] exit.")


def cmd_aggregate(args):
    snap = _ensure_snapshot()
    if not snap.get("stocks"):
        print("ERR: snapshot empty")
        return 1
    summary = svc.save_sectors_index(snap["stocks"], progress=True)
    cat_summary = ", ".join(
        "{}:{}".format(c["category_label"], c["sector_count"])
        for c in summary["categories"].values()
    )
    print(f"OK: {summary['category_count']} categories ({cat_summary})")
    return 0


def cmd_clean(args):
    """清空 _failed_codes.json + 当天 snapshot. 保留 _codes.json + groups/."""
    removed: list[str] = []
    if FAILED_FILE.exists():
        FAILED_FILE.unlink()
        removed.append(str(FAILED_FILE))
    if SNAPSHOT_FILE.exists():
        SNAPSHOT_FILE.unlink()
        removed.append(str(SNAPSHOT_FILE))
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        removed.append(str(PROGRESS_FILE))
    if removed:
        print(f"[clean] removed {len(removed)} files:")
        for p in removed:
            print(f"  - {p}")
    else:
        print("[clean] nothing to clean")
    print(f"[clean] OK (kept _codes.json + groups/)")


def main():
    parser = argparse.ArgumentParser(description="分批拉取 stock_universe (单组单次, 跑完即退出)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="看进度")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="跑一组 (单次, 跑完即退出)")
    p_run.add_argument("--group", required=True, help="组号, 形如 0001 (从 groups/NNNN.json 读 codes)")
    p_run.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p_run.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    p_run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_run.set_defaults(func=cmd_run_group)

    p_fail = sub.add_parser("run-failed", help="只重跑 _failed_codes.json 里的失败 code")
    p_fail.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p_fail.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    p_fail.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_fail.set_defaults(func=cmd_run_failed)

    p_agg = sub.add_parser("aggregate", help="聚合 sectors.json (从 snapshot)")
    p_agg.set_defaults(func=cmd_aggregate)

    p_clean = sub.add_parser("clean", help="清空 _failed_codes.json + 当天 snapshot (保留 _codes.json + groups/)")
    p_clean.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
