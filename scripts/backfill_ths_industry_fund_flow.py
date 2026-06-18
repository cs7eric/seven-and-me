"""同花顺 90 行业主力资金 → duckdb 一次性回填 + 每日增量.

数据源 (扫本地 JSON, 不走网络):
  reference/ths-fund-flow/history/YYYY-MM-DD.json
    每份含 {ok, rowCount, totalPages, pageRowCounts, fetchedAt, rows: [90 行业], ...}
  rows 每条字段: rank / industry / change_pct / inflow / outflow / net
                  / company_count / leader_stock / leader_change / leader_price

幂等: 全部走 INSERT OR REPLACE by (trade_date, industry), 重复跑不写脏.

用法:
    python scripts/backfill_ths_industry_fund_flow.py
    python scripts/backfill_ths_industry_fund_flow.py --days=60
    python scripts/backfill_ths_industry_fund_flow.py --date=2026-06-16
    python scripts/backfill_ths_industry_fund_flow.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_ths_industry_fund_flow")

REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = REPO_ROOT / "reference" / "ths-fund-flow" / "history"


def _date_within_window(d: date, days: int) -> bool:
    """判断 d 是不是 days 天内 (含今天)."""
    today = date.today()
    return d >= (today - timedelta(days=days))


def _scan_history(days: int) -> dict[str, list[dict]]:
    """扫 reference/ths-fund-flow/history/YYYY-MM-DD.json → {date_iso: [rows]}.

    rows 元素保留原始英文 key, 给 repo upsert_fund_flow() 用.
    """
    out: dict[str, list[dict]] = {}
    if not HISTORY_DIR.exists():
        log.warning("history dir 不存在: %s", HISTORY_DIR)
        return out
    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    for f in files:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if not _date_within_window(d, days):
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("history %s parse failed: %s", f.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        rows = data.get("rows") or []
        if not rows:
            continue
        out[f.stem] = rows
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回填同花顺 90 行业资金流 到 duckdb")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--date", type=str, default=None,
                    help="单日 YYYY-MM-DD, 只回填这一天")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log.info("start: days=%s date=%s dry_run=%s",
             args.days, args.date, args.dry_run)

    # 初始化 schema (幂等)
    from backend.adapters.market.duckdb_store import init_schema
    init_schema()
    log.info("schema 初始化完成 (幂等)")

    from backend.repositories.market.ths_industry_fund_flow_repo import (
        upsert_fund_flow, coverage,
    )

    # 单日模式
    if args.date:
        p = HISTORY_DIR / f"{args.date}.json"
        if not p.exists():
            log.error("history 文件不存在: %s", p)
            return 1
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = [_to_repo_row(r) for r in (data.get("rows") or [])]
        log.info("history %s: %d 行", p.name, len(rows))
        if args.dry_run:
            log.info("[dry-run] 没写任何东西")
            return 0
        n = upsert_fund_flow(rows, trade_date=args.date, source="ths.10jqka.com.cn")
        log.info("upserted %d 行 (date=%s)", n, args.date)
        return 0

    # 区间模式
    by_date = _scan_history(args.days)
    total_rows = sum(len(v) for v in by_date.values())
    log.info("history 命中 %d 天 / %d 行", len(by_date), total_rows)

    if args.dry_run:
        log.info("[dry-run] 没写任何东西")
        return 0

    n_days = 0
    n_rows = 0
    for d, rows_raw in by_date.items():
        try:
            rows = [_to_repo_row(r) for r in rows_raw]
            n = upsert_fund_flow(rows, trade_date=d, source="ths.10jqka.com.cn")
            n_days += 1
            n_rows += n
        except Exception as exc:
            log.warning("upsert %s failed: %s", d, exc)
    log.info("done.  days=%d rows=%d", n_days, n_rows)
    log.info("coverage: %s", coverage())
    return 0


# 中英文 key 映射 (history JSON 实际存的是中文 key, 跟前端 IndustryFundFlowRow 一致)
_ZH_KEY_MAP: dict[str, str] = {
    "序号": "rank",
    "行业": "industry",
    "行业指数涨跌幅": "change_pct",
    "流入资金(亿)": "inflow",
    "流出资金(亿)": "outflow",
    "净额(亿)": "net",
    "公司家数": "company_count",
    "领涨股": "leader_stock",
    "领涨股涨跌幅": "leader_change",
    "当前价(元)": "leader_price",
    "code": "industry_code",            # 后端 enrich
    "行业code": "industry_code",
}


def _parse_percent(v: Any) -> float | None:
    """把 '5.98%' / 5.98 / '5.98' → 5.98 (数字)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_number(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _to_repo_row(row: dict[str, Any]) -> dict[str, Any]:
    """history JSON 里的 row (中文 key) → repo 期望的 row (英文 key, 数值已 parse).

    同时 enrich industry_code: history 里没存 6 位 ths code, 调 ths_industry_service.name_to_code()
    从磁盘 industry_list.json 查. 失败/找不到留 None.
    """
    out: dict[str, Any] = {}
    for zh, en in _ZH_KEY_MAP.items():
        if zh in row:
            v = row[zh]
            if en in ("change_pct", "leader_change"):
                out[en] = _parse_percent(v)
            elif en in ("inflow", "outflow", "net", "leader_price"):
                out[en] = _parse_number(v)
            elif en in ("rank", "company_count"):
                out[en] = _parse_number(v)
            else:
                out[en] = v
    # enrich industry_code (enrich, 不破坏: 已有值优先)
    if not out.get("industry_code") and out.get("industry"):
        try:
            from backend.services.stock.f10.ths_industry_service import name_to_code
            code = name_to_code(out["industry"])
            if code:
                out["industry_code"] = code
        except Exception as exc:
            log.debug("name_to_code(%s) failed: %s", out.get("industry"), exc)
    return out


if __name__ == "__main__":
    sys.exit(main())
