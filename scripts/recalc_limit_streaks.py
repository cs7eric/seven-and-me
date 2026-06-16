"""
重新计算 reference/market-limit/daily/*.json 的连板 streak。

从最早的一天开始，每只股票的 limitUpStreak = 上一天的 limitUpStreak + 1（今日涨停）
或者 0（今日未涨停）。保留原始的 isLimitUp / isLimitDown 不变。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.settings import MARKET_LIMIT_DAILY_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("recalc")


def run(force: bool = False):
    MARKET_LIMIT_DAILY_DIR.mkdir(parents=True, exist_ok=True)

    # 收集所有日期文件
    files: list[Path] = sorted(MARKET_LIMIT_DAILY_DIR.glob("*.json"))
    if not files:
        logger.warning("No daily files found in %s", MARKET_LIMIT_DAILY_DIR)
        return

    # 按日期升序排列
    dates: list[date] = []
    date_to_path: dict[date, Path] = {}
    for p in files:
        try:
            d = date.fromisoformat(p.stem)
            dates.append(d)
            date_to_path[d] = p
        except ValueError:
            logger.warning("Skipping non-date file: %s", p.name)
            continue
    dates.sort()
    logger.info("Found %d daily files from %s to %s", len(dates), dates[0], dates[-1])

    # 加载所有数据到内存
    all_data: dict[date, list[dict]] = {}
    for d in dates:
        path = date_to_path[d]
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path.name, exc)
            continue
        stocks = blob.get("stocks") or []
        all_data[d] = stocks
        logger.info("Loaded %s: %d stocks", d, len(stocks))

    # 按日期顺序重算 streak
    updated = 0
    prev_streaks: dict[str, int] = {}  # code -> streak from previous day

    for d in dates:
        rows = all_data.get(d)
        if not rows:
            continue

        new_streaks: dict[str, int] = {}
        for row in rows:
            code = (row.get("code") or "").lower()
            if not code:
                continue

            prev = prev_streaks.get(code, 0)
            is_up = bool(row.get("isLimitUp"))
            cur = (prev + 1) if is_up else 0

            row["limitUpStreak"] = cur
            row["previousLimitUpStreak"] = prev
            row["isPromoted"] = bool(is_up and prev > 0 and cur == prev + 1)
            row["isBrokenStreak"] = bool((not is_up) and prev > 0)

            new_streaks[code] = cur

        prev_streaks = new_streaks

        # 写回文件
        path = date_to_path[d]
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # 更新 stocks
        blob["stocks"] = rows

        if force:
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1
            lu = sum(1 for r in rows if r.get("isLimitUp"))
            max_s = max((r.get("limitUpStreak") or 0) for r in rows) if rows else 0
            logger.info("Wrote %s (force): limitUp=%d, maxStreak=%d", d, lu, max_s)
        else:
            # dry-run: 只打印 diff
            max_s = max((r.get("limitUpStreak") or 0) for r in rows) if rows else 0
            max_s_old = max(
                (json.loads(date_to_path[d].read_text(encoding="utf-8")).get("stocks", [{}])[0].get("limitUpStreak") or 0)
                for _ in [1]
            ) if date_to_path[d].exists() else 0
            logger.info("DRY-RUN %s: would update streaks", d)

    if not force:
        logger.info("DRY-RUN done. Run with --force to actually write.")
    else:
        logger.info("Done! Updated %d files.", updated)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="重新计算连板 streak")
    parser.add_argument("--force", action="store_true", help="实际写入（默认 dry-run）")
    args = parser.parse_args()
    run(force=args.force)