"""大盘概况 / 市场脉搏 · duckdb 同步 / 历史回填.

默认数据源:
  - PostgreSQL app.market_overview_snapshots
    → duckdb.market_overview_daily (MSI / turnover_activity 的成交额数据源)

历史兼容源:
  - reference/market-overview/archive/YYYYMMDD.json
  - reference/market-overview/market-overview/archive/YYYYMMDD.json
  - reference/stock-universe/market_pulse/rotation/YYYY-MM-DD.json

幂等: 全部走 INSERT OR REPLACE / 字段级 UPSERT, 重复跑不写脏.

用法:
    python scripts/backfill_market_overview_daily.py
    python scripts/backfill_market_overview_daily.py --days=60
    python scripts/backfill_market_overview_daily.py --days=30 --source=archive
    python scripts/backfill_market_overview_daily.py --dry-run
    python scripts/backfill_market_overview_daily.py --date=2026-06-16     # 单日
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_market_overview_daily")

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKET_OVERVIEW_ROOT = REPO_ROOT / "reference" / "market-overview"
AKSHARE_ARCHIVE = MARKET_OVERVIEW_ROOT / "archive"  # 共享: akshare fund-flow + eltdx overview
ELTDX_ARCHIVE = MARKET_OVERVIEW_ROOT / "market-overview" / "archive"
ROTATION_DIR = REPO_ROOT / "reference" / "stock-universe" / "market_pulse" / "rotation"


def _yyyymmdd_to_iso(stem: str) -> str | None:
    if len(stem) != 8 or not stem.isdigit():
        return None
    try:
        return date(int(stem[:4]), int(stem[4:6]), int(stem[6:8])).isoformat()
    except ValueError:
        return None


def _date_within_window(d: date, days: int) -> bool:
    """判断 d 是不是 days 天内 (含今天)."""
    today = date.today()
    return d >= (today - timedelta(days=days))


# ---------------------------------------------------------------------------
# Source 1: akshare fund-flow + spot_em
# ---------------------------------------------------------------------------
def _scan_akshare_archive(days: int) -> list[dict]:
    """扫 reference/market-overview/archive/YYYYMMDD.json 拿 akshare 资金流 + spot_em."""
    out: list[dict] = []
    if not AKSHARE_ARCHIVE.exists():
        log.warning("akshare archive dir 不存在: %s", AKSHARE_ARCHIVE)
        return out
    files = sorted(AKSHARE_ARCHIVE.glob("*.json"), reverse=True)
    for f in files:
        iso = _yyyymmdd_to_iso(f.stem)
        if not iso:
            continue
        d = date.fromisoformat(iso)
        if not _date_within_window(d, days):
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("akshare archive %s parse failed: %s", f.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        # akshare 写的 archive 含 tradingDate / fetchedAt / source / 资金流 + 涨跌家数
        if not data.get("tradingDate"):
            data["tradingDate"] = iso
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# Source 2: eltdx overview
# ---------------------------------------------------------------------------
def _scan_eltdx_archive(days: int) -> list[dict]:
    """扫 reference/market-overview/market-overview/archive/YYYYMMDD.json 拿 eltdx."""
    out: list[dict] = []
    if not ELTDX_ARCHIVE.exists():
        log.warning("eltdx archive dir 不存在: %s", ELTDX_ARCHIVE)
        return out
    files = sorted(ELTDX_ARCHIVE.glob("*.json"), reverse=True)
    for f in files:
        iso = _yyyymmdd_to_iso(f.stem)
        if not iso:
            continue
        d = date.fromisoformat(iso)
        if not _date_within_window(d, days):
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("eltdx archive %s parse failed: %s", f.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        if not data.get("tradingDate"):
            data["tradingDate"] = iso
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# Source 3: market_pulse rotation (90 行业)
# ---------------------------------------------------------------------------
def _scan_rotation(days: int) -> dict[str, list[dict]]:
    """扫 reference/stock-universe/market_pulse/rotation/YYYY-MM-DD.json → {date_iso: [rows]}.

    rotation 文件的 items 元素字段: name / changePct / mainNet / inflow / outflow
                                    / stockCount / leadingStock / leadingChangePct / rank
    """
    out: dict[str, list[dict]] = {}
    if not ROTATION_DIR.exists():
        log.warning("rotation dir 不存在: %s", ROTATION_DIR)
        return out
    files = sorted(ROTATION_DIR.glob("*.json"), reverse=True)
    for f in files:
        # rotation 文件名是 ISO YYYY-MM-DD.json
        stem = f.stem
        try:
            d = date.fromisoformat(stem)
        except ValueError:
            continue
        if not _date_within_window(d, days):
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("rotation %s parse failed: %s", f.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("items") or []
        if not items:
            continue
        out[stem] = items
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """回填大盘概况 / 市场脉搏 90 行业 到 duckdb.

    `argv` 默认 None → 走 sys.argv. 接受 list 给 in-process 调用方传参
    (e.g. daily_eod_incremental 调它, 避免 subprocess 再开 duckdb 撞锁).
    """
    ap = argparse.ArgumentParser(description="回填大盘概况 / 市场脉搏 90 行业 到 duckdb")
    ap.add_argument("--days", type=int, default=60,
                    help="回填最近 N 天 (默认 60)")
    ap.add_argument("--date", type=str, default=None,
                    help="单日 (YYYY-MM-DD 或 YYYYMMDD), 只回填这一天")
    ap.add_argument("--source", choices=["pg", "archive", "all", "akshare", "eltdx", "sector"], default="pg",
                    help="数据源: pg=Postgres runtime source; archive/all/akshare/eltdx/sector=历史 JSON 兼容")
    ap.add_argument("--dry-run", action="store_true", help="只看计划, 不写入")
    args = ap.parse_args(argv)

    log.info("start: days=%s source=%s dry_run=%s", args.days, args.source, args.dry_run)

    # 初始化 schema (幂等)
    from backend.adapters.market.duckdb_store import init_schema
    init_schema()
    log.info("schema 初始化完成 (幂等)")

    # 生产路径: Postgres runtime source -> DuckDB downstream cache.
    if args.source == "pg":
        if args.date:
            target = _normalize_date_arg(args.date)
            return _sync_pg_date(target, dry_run=args.dry_run)
        return _sync_pg_history(days=args.days, dry_run=args.dry_run)

    # 单日 archive 兼容模式
    if args.date:
        iso = _normalize_date_arg(args.date)
        d_norm = iso.replace("-", "")
        args.days = max(args.days, 1)  # 单日也走 days 路径 (下面会过滤)
        found_sources: list[str] = []
        missing_paths: list[Path] = []
        # 直接读对应 archive
        if args.source in ("all", "akshare"):
            p = AKSHARE_ARCHIVE / f"{d_norm}.json"
            if p.exists():
                found_sources.append("akshare")
                items = [json.loads(p.read_text(encoding="utf-8"))]
                log.info("akshare archive: %s", p)
                if not args.dry_run:
                    _upsert_akshare(items)
            else:
                missing_paths.append(p)
        if args.source in ("all", "eltdx"):
            p = ELTDX_ARCHIVE / f"{d_norm}.json"
            if p.exists():
                found_sources.append("eltdx")
                items = [json.loads(p.read_text(encoding="utf-8"))]
                log.info("eltdx archive: %s", p)
                if not args.dry_run:
                    _upsert_eltdx(items)
            else:
                missing_paths.append(p)
        if args.source in ("all", "sector"):
            p = ROTATION_DIR / f"{iso}.json"
            if p.exists():
                found_sources.append("sector")
                data = json.loads(p.read_text(encoding="utf-8"))
                log.info("rotation: %s (items=%d)", p, len(data.get("items") or []))
                if not args.dry_run:
                    _upsert_rotation({iso: data.get("items") or []})
            else:
                missing_paths.append(p)
        if not found_sources:
            log.error(
                "目标日 %s 没有任何本地源 archive, 无法写 market_overview_daily. missing=%s",
                iso,
                ", ".join(str(p) for p in missing_paths),
            )
            return 1
        log.info("done. date=%s sources=%s", iso, ",".join(found_sources))
        return 0

    # 区间模式
    n_akshare = n_eltdx = n_sector_days = 0
    if args.source in ("all", "akshare"):
        items = _scan_akshare_archive(args.days)
        log.info("akshare archive 命中 %d 天", len(items))
        if not args.dry_run and items:
            n_akshare = _upsert_akshare(items)
    if args.source in ("all", "eltdx"):
        items = _scan_eltdx_archive(args.days)
        log.info("eltdx archive 命中 %d 天", len(items))
        if not args.dry_run and items:
            n_eltdx = _upsert_eltdx(items)
    if args.source in ("all", "sector"):
        rot = _scan_rotation(args.days)
        n_sector_days = len(rot)
        total_rows = sum(len(v) for v in rot.values())
        log.info("rotation 命中 %d 天 / %d 行", n_sector_days, total_rows)
        if not args.dry_run and rot:
            _upsert_rotation(rot)

    if args.dry_run:
        log.info("[dry-run] 没写任何东西")
    else:
        log.info("done.  akshare_upserted=%d  eltdx_upserted=%d  sector_days=%d",
                 n_akshare, n_eltdx, n_sector_days)
    return 0


def _normalize_date_arg(value: str) -> str:
    d_norm = value.replace("-", "")
    if len(d_norm) == 8 and d_norm.isdigit():
        return f"{d_norm[:4]}-{d_norm[4:6]}-{d_norm[6:8]}"
    # validate
    return date.fromisoformat(value).isoformat()


def _sync_pg_date(target: str, dry_run: bool = False) -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.config.database import session_scope
    from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

    with session_scope() as db:
        item = MarketOverviewPgRepository(db).get(target)

    if item is None:
        log.error("PG app.market_overview_snapshots 没有目标日 %s 的记录", target)
        return 1
    if item.get("total_amount") in (None, 0):
        log.error("PG app.market_overview_snapshots.%s total_amount 为空, 不能同步到 DuckDB", target)
        return 1

    if dry_run:
        log.info(
            "[dry-run] pg snapshot: date=%s total_amount=%s source=%s",
            target,
            item.get("total_amount"),
            item.get("source"),
        )
        return 0

    _upsert_pg_snapshot_to_duckdb(item)
    log.info(
        "done. pg_to_duckdb date=%s total_amount=%s source=%s",
        target,
        item.get("total_amount"),
        item.get("source"),
    )
    return 0


def _sync_pg_history(days: int, dry_run: bool = False) -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    from backend.config.database import session_scope
    from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

    with session_scope() as db:
        items = MarketOverviewPgRepository(db).get_history(days=days)

    items = [it for it in items if it.get("total_amount") not in (None, 0)]
    if dry_run:
        log.info("[dry-run] pg snapshots with total_amount: %d", len(items))
        return 0
    for item in items:
        _upsert_pg_snapshot_to_duckdb(item)
    log.info("done. pg_to_duckdb rows=%d", len(items))
    return 0 if items else 1


def _upsert_pg_snapshot_to_duckdb(item: dict) -> None:
    from backend.adapters.market.duckdb_store import get_conn

    cols = [
        "trade_date",
        "total_amount",
        "total_volume",
        "rising_count",
        "falling_count",
        "flat_count",
        "limit_up_count",
        "limit_down_count",
        "stock_count",
        "main_net_inflow",
        "super_large_net_inflow",
        "large_net_inflow",
        "medium_net_inflow",
        "small_net_inflow",
        "main_net_inflow_ratio",
        "super_large_net_ratio",
        "large_net_ratio",
        "medium_net_ratio",
        "small_net_ratio",
        "source",
    ]
    params = [
        item.get("trade_date"),
        item.get("total_amount"),
        item.get("total_volume"),
        item.get("rising_count"),
        item.get("falling_count"),
        item.get("flat_count"),
        item.get("limit_up_count"),
        item.get("limit_down_count"),
        item.get("stock_count"),
        item.get("main_net_inflow"),
        item.get("super_large_net_inflow"),
        item.get("large_net_inflow"),
        item.get("medium_net_inflow"),
        item.get("small_net_inflow"),
        item.get("main_net_inflow_ratio"),
        item.get("super_large_net_ratio"),
        item.get("large_net_ratio"),
        item.get("medium_net_ratio"),
        item.get("small_net_ratio"),
        f"pg:{item.get('source') or 'market_overview_snapshots'}"[:32],
    ]
    placeholders = ", ".join(["?"] * len(cols))
    con = get_conn()
    con.execute(
        f"INSERT OR REPLACE INTO market_overview_daily ({', '.join(cols)}) VALUES ({placeholders})",
        params,
    )


def _upsert_akshare(items: list[dict]) -> int:
    from backend.repositories.market.market_overview_repo import upsert_overview_akshare
    n = 0
    for it in items:
        try:
            upsert_overview_akshare(it)
            n += 1
        except Exception as exc:
            log.warning("akshare upsert %s failed: %s", it.get("tradingDate"), exc)
    return n


def _upsert_eltdx(items: list[dict]) -> int:
    from backend.repositories.market.market_overview_repo import upsert_overview_eltdx
    n = 0
    for it in items:
        try:
            upsert_overview_eltdx(it)
            n += 1
        except Exception as exc:
            log.warning("eltdx upsert %s failed: %s", it.get("tradingDate"), exc)
    return n


def _upsert_rotation(by_date: dict[str, list[dict]]) -> int:
    from backend.repositories.market.market_pulse_sector_repo import upsert_sector_spot
    n = 0
    for d, items in by_date.items():
        try:
            upsert_sector_spot(items, trade_date=d,
                               source="akshare.stock_fund_flow_industry")
            n += 1
        except Exception as exc:
            log.warning("sector upsert %s failed: %s", d, exc)
    return n


if __name__ == "__main__":
    sys.exit(main())
