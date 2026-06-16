"""
把 reference/market-limit/daily/*.json 里 name = code 的股票补上中文名.

腾讯 kline API 不返回股票 name, backfill 时只能写 code.
universe 里 (reference/stock-universe/...) 有完整的 code → name 映射, 这里用它反查.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.stock.limit_emotion_service import _load_universe_meta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_names")


def run(force: bool = False):
    daily_dir = ROOT / "reference" / "market-limit" / "daily"
    if not daily_dir.exists():
        logger.warning("daily dir not found: %s", daily_dir)
        return

    universe = _load_universe_meta()
    logger.info("Loaded universe meta: %d entries", len(universe))

    # 收集所有 daily 文件里出现过的 code → 用于统计多少需要补
    need_fix: dict[str, int] = {}  # code -> 出现次数
    all_codes: set[str] = set()

    for path in sorted(daily_dir.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("read %s failed: %s", path.name, exc)
            continue
        for s in blob.get("stocks") or []:
            code = (s.get("code") or "").lower()
            if not code:
                continue
            all_codes.add(code)
            if (s.get("name") or "").strip() == code:
                need_fix[code] = need_fix.get(code, 0) + 1

    logger.info("Total unique codes: %d", len(all_codes))
    logger.info("Codes with name = code (need fix): %d", len(need_fix))

    # 反查 universe 拿到真实 name
    fixed_in_universe = 0
    missing_in_universe = 0
    for code in need_fix:
        meta = universe.get(code) or universe.get(code[-6:]) or {}
        if meta.get("name"):
            fixed_in_universe += 1
        else:
            missing_in_universe += 1
            logger.debug("  no name in universe for %s", code)

    logger.info(
        "Can fix %d, missing in universe %d",
        fixed_in_universe, missing_in_universe,
    )

    if not force:
        logger.info("DRY-RUN done. Run with --force to write.")
        return

    # 实际写入
    updated_files = 0
    for path in sorted(daily_dir.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        stocks = blob.get("stocks") or []
        changed = 0
        for s in stocks:
            code = (s.get("code") or "").lower()
            if (s.get("name") or "").strip() != code:
                continue
            meta = universe.get(code) or universe.get(code[-6:]) or {}
            real_name = (meta.get("name") or "").strip()
            if real_name:
                s["name"] = real_name
                changed += 1
        if changed:
            blob["stocks"] = stocks
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
            updated_files += 1
            logger.info("Updated %s: %d names fixed", path.name, changed)

    logger.info("Done! Updated %d files.", updated_files)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="补全 daily 文件里的股票名")
    parser.add_argument("--force", action="store_true", help="实际写入（默认 dry-run）")
    args = parser.parse_args()
    run(force=args.force)
