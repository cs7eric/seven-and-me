"""手动/批量跑 90 行业全量成分股 (Playwright 翻全页, 持久化到 constituents/{code}.json).

用法 (从项目根目录):
    python -m backend.scripts.refresh_ths_industry_constituents
    python -m backend.scripts.refresh_ths_industry_constituents --refresh  # 强制刷新
    python -m backend.scripts.refresh_ths_industry_constituents --only 半导体 银行  # 限定行业

需要:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 允许从项目根跑
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services.stock.f10.ths_industry_service import (
    CONSTITUENTS_DIR,
    get_all_constituents,
    get_industry_list,
    get_constituents_payload,
    INDUSTRY_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("refresh_ths_industry")

STATE_FILE: Path = INDUSTRY_DIR / "constituents_crawl_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true", help="强制重新爬, 覆盖磁盘缓存")
    p.add_argument("--only", nargs="*", help="只刷指定行业 (name 或 code)")
    p.add_argument("--limit", type=int, default=0, help="最多刷 N 个 (调试用)")
    args = p.parse_args()

    listing = get_industry_list()
    if args.only:
        only = {str(x).strip() for x in args.only}
        targets = {c: v for c, v in listing.items() if c in only or v["name"] in only}
    else:
        targets = listing
    if args.limit > 0:
        targets = dict(list(targets.items())[: args.limit])

    logger.info("targets: %d industries, refresh=%s", len(targets), args.refresh)

    state = _load_state()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    state.setdefault("runs", {})[run_id] = {
        "startedAt": datetime.now().isoformat(timespec="seconds"),
        "targets": list(targets.keys()),
        "industries": {},
    }
    run_state = state["runs"][run_id]

    ok = 0
    fail = 0
    t0 = time.time()
    for code, info in targets.items():
        name = info["name"]
        logger.info("[%d/%d] %s (%s) ...", ok + fail + 1, len(targets), name, code)
        row_t0 = time.time()
        try:
            payload = get_constituents_payload(code, refresh=args.refresh)
            elapsed = round((time.time() - row_t0) * 1000)
            pages = payload.get("pages", 0)
            nrows = len(payload.get("rows") or [])
            run_state["industries"][code] = {
                "name": name, "ok": True, "pages": pages,
                "rows": nrows, "elapsedMs": elapsed,
                "fetchedAt": payload.get("fetchedAt"),
            }
            ok += 1
            logger.info("  -> %d rows / %d pages / %dms", nrows, pages, elapsed)
        except Exception as exc:
            elapsed = round((time.time() - row_t0) * 1000)
            run_state["industries"][code] = {
                "name": name, "ok": False, "error": str(exc)[:200],
                "elapsedMs": elapsed,
            }
            fail += 1
            logger.warning("  -> failed: %s", exc)
        _save_state(state)

    total_elapsed = round((time.time() - t0) * 1000)
    run_state["finishedAt"] = datetime.now().isoformat(timespec="seconds")
    run_state["okCount"] = ok
    run_state["failCount"] = fail
    run_state["elapsedMs"] = total_elapsed
    _save_state(state)
    logger.info("done: ok=%d fail=%d elapsed=%dms (%.1fs)",
                ok, fail, total_elapsed, total_elapsed / 1000)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
