"""THS industry fund-flow repository for ``cynexus_appl_market`` flat daily table."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date


def _to_date(value: date | str | None) -> date | None:
    return to_date(value)


def _to_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_to_payload(row: Any) -> dict[str, Any]:
    r = row if isinstance(row, dict) else row._mapping if hasattr(row, "_mapping") else dict(row)
    return {
        "序号": int(r.get("rank") or 0),
        "行业": r.get("industry"),
        "code": r.get("industry_code"),
        "行业指数涨跌幅": _to_float(r.get("change_pct")),
        "流入资金(亿)": _to_float(r.get("inflow")),
        "流出资金(亿)": _to_float(r.get("outflow")),
        "净额(亿)": _to_float(r.get("net")),
        "公司家数": _to_int(r.get("company_count")),
        "领涨股": r.get("leader_stock"),
        "领涨股涨跌幅": _to_float(r.get("leader_change")),
        "当前价(元)": _to_float(r.get("leader_price")),
        "tradeDate": r.get("trade_date").isoformat() if r.get("trade_date") else None,
        "source": r.get("source"),
    }


def _legacy_row_to_values(row: dict[str, Any], trade_date: date, source: str, fetched_at: datetime) -> dict[str, Any] | None:
    industry = _strip(row.get("行业") or row.get("industry"))
    if not industry:
        return None
    return {
        "trade_date": trade_date,
        "industry": industry,
        "industry_code": _strip(row.get("code") or row.get("industryCode") or row.get("industry_code")),
        "rank": _to_int(row.get("序号") or row.get("rank")),
        "change_pct": _to_float(row.get("行业指数涨跌幅") or row.get("changePct") or row.get("change_pct")) or 0,
        "inflow": _to_float(row.get("流入资金(亿)") or row.get("inflow")) or 0,
        "outflow": _to_float(row.get("流出资金(亿)") or row.get("outflow")) or 0,
        "net": _to_float(row.get("净额(亿)") or row.get("net")) or 0,
        "company_count": _to_int(row.get("公司家数") or row.get("companyCount") or row.get("company_count")),
        "leader_stock": _strip(row.get("领涨股") or row.get("leaderStock") or row.get("leader_stock")),
        "leader_change": _to_float(row.get("领涨股涨跌幅") or row.get("leaderChange") or row.get("leader_change")),
        "leader_price": _to_float(row.get("当前价(元)") or row.get("leaderPrice") or row.get("leader_price")),
        "source": source,
        "ingested_at": fetched_at,
        "extra": row,
    }


class ThsIndustryFundFlowRepository:
    def __init__(self, db: Session):
        self.db = db

    def ensure_bootstrapped(self, scope: str = "industry") -> None:
        # Data has been migrated into cynexus_appl_market.mkt_ths_industry_fund_flow_daily.
        return

    def has_trade_date(self, trade_date: date | str, *, scope: str = "industry") -> bool:
        td = _to_date(trade_date)
        if td is None:
            return False
        return bool(self.db.execute(text("""
            SELECT 1 FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1
        """), {"td": td}).first())

    def latest_trade_date(self, *, scope: str = "industry") -> date | None:
        return self.db.execute(text("""
            SELECT MAX(trade_date) FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE deleted_at IS NULL
        """)).scalar_one_or_none()

    def list_trade_dates(self, *, scope: str = "industry", limit: int = 365) -> list[str]:
        rows = self.db.execute(text("""
            SELECT DISTINCT trade_date FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE deleted_at IS NULL ORDER BY trade_date DESC LIMIT :limit
        """), {"limit": max(1, min(limit, 1000))}).all()
        return [td.isoformat() for (td,) in rows]

    def replace_trade_day_snapshot(
        self,
        *,
        trade_date: date | str,
        raw_payload: dict[str, Any],
        scope: str = "industry",
        source_type: str = "crawler",
        source: str = "ths.10jqka.com.cn",
        fetched_at: datetime | None = None,
    ) -> dict[str, Any]:
        td = _to_date(trade_date)
        if td is None:
            raise ValueError("trade_date is required")
        fetched_dt = fetched_at or _to_datetime(raw_payload.get("fetchedAt")) or datetime.now()
        raw_rows = raw_payload.get("rows") or []
        normalized = [_legacy_row_to_values(row, td, source, fetched_dt) for row in raw_rows if isinstance(row, dict)]
        normalized = [row for row in normalized if row is not None]
        normalized.sort(key=lambda row: (row.get("net") or float("-inf"), row.get("change_pct") or float("-inf")), reverse=True)
        for idx, row in enumerate(normalized, start=1):
            row["rank"] = idx
        self.db.execute(text("""
            UPDATE cynexus_appl_market.mkt_ths_industry_fund_flow_daily
               SET deleted_at = now()
             WHERE trade_date = :td AND deleted_at IS NULL
        """), {"td": td})
        for row in normalized:
            execute_upsert(self.db, table="mkt_ths_industry_fund_flow_daily", key_columns=["trade_date", "industry"], values=row)
        self.db.flush()
        return self.get_daily_payload(td, scope=scope) or {"ok": True, "tradeDate": td.isoformat(), "rowCount": len(normalized), "rows": []}

    def get_daily_payload(self, trade_date: date | str | None = None, *, scope: str = "industry") -> dict[str, Any] | None:
        td = _to_date(trade_date) if trade_date is not None else self.latest_trade_date(scope=scope)
        if td is None:
            return None
        rows = self.db.execute(text("""
            SELECT trade_date, industry, industry_code, rank, change_pct, inflow, outflow, net,
                   company_count, leader_stock, leader_change, leader_price, source, ingested_at
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE trade_date = :td AND deleted_at IS NULL
             ORDER BY net DESC, rank ASC NULLS LAST
        """), {"td": td}).mappings().all()
        if not rows:
            return None
        fetched_at = next((row.get("ingested_at") for row in rows if row.get("ingested_at")), None)
        return {
            "ok": True,
            "tradeDate": td.isoformat(),
            "rowCount": len(rows),
            "totalPages": None,
            "pageRowCounts": [],
            "fetchedAt": fetched_at.isoformat() if fetched_at else None,
            "rows": [_row_to_payload(dict(row)) for row in rows],
            "source": rows[0].get("source"),
        }

    def get_fund_flow_daily(self, trade_date: date | str, *, scope: str = "industry") -> list[dict[str, Any]]:
        payload = self.get_daily_payload(trade_date, scope=scope)
        return payload["rows"] if payload else []

    def get_fund_flow_daily_topn(self, trade_date: date | str, top_n: int = 10, *, scope: str = "industry") -> dict[str, Any]:
        rows = self.get_fund_flow_daily(trade_date, scope=scope)
        if not rows:
            td = _to_date(trade_date)
            return {"tradeDate": td.isoformat() if td else None, "topN": top_n, "top": [], "bottom": [], "count": 0}
        return {"tradeDate": rows[0]["tradeDate"], "topN": top_n, "top": rows[:top_n], "bottom": list(reversed(rows[-top_n:])) if len(rows) >= top_n else list(reversed(rows)), "count": len(rows)}

    def get_fund_flow_history(self, days: int = 10, top_n: int | None = None, *, scope: str = "industry") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for trade_date in self.list_trade_dates(scope=scope, limit=max(1, min(days, 365))):
            rows = self.get_fund_flow_daily(trade_date, scope=scope)
            if top_n is not None:
                rows = rows[:top_n]
            out.append({"tradeDate": trade_date, "items": rows})
        return out

    def get_fund_flow_for_industry(self, industry: str, days: int = 30, *, end: date | str | None = None, scope: str = "industry") -> list[dict[str, Any]]:
        if not industry:
            return []
        end_date = _to_date(end)
        where_end = "AND trade_date <= :end_date" if end_date is not None else ""
        params: dict[str, Any] = {"industry": industry, "limit": max(1, min(days, 365))}
        if end_date is not None:
            params["end_date"] = end_date
        rows = self.db.execute(text(f"""
            SELECT trade_date, industry, industry_code, rank, change_pct, inflow, outflow, net,
                   company_count, leader_stock, leader_change, leader_price, source
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE industry = :industry AND deleted_at IS NULL {where_end}
             ORDER BY trade_date DESC LIMIT :limit
        """), params).mappings().all()
        return [_row_to_payload(dict(row)) for row in reversed(rows)]

    def list_industries_with_data(self, days: int = 30, *, scope: str = "industry") -> list[dict[str, Any]]:
        latest_dates = self.list_trade_dates(scope=scope, limit=max(1, min(days, 365)))
        if not latest_dates:
            return []
        cutoff = _to_date(latest_dates[-1])
        rows = self.db.execute(text("""
            SELECT industry, industry_code, COUNT(*) AS days, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE deleted_at IS NULL AND trade_date >= :cutoff
             GROUP BY industry, industry_code
             ORDER BY industry ASC
        """), {"cutoff": cutoff}).all()
        return [{"industry": r[0], "industryCode": r[1], "days": int(r[2] or 0), "firstDate": r[3].isoformat() if r[3] else None, "lastDate": r[4].isoformat() if r[4] else None} for r in rows]

    def get_sector_breadth_input(self, trade_date: date | str, *, scope: str = "industry") -> dict[str, Any] | None:
        td = _to_date(trade_date)
        if td is None:
            return None
        row = self.db.execute(text("""
            SELECT COUNT(*) FILTER (WHERE change_pct > 0),
                   COUNT(*) FILTER (WHERE change_pct < 0),
                   COUNT(*) FILTER (WHERE change_pct = 0),
                   COUNT(*)
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE trade_date = :td AND deleted_at IS NULL
        """), {"td": td}).one()
        total = int(row[3] or 0)
        if total == 0:
            return None
        return {"advancing": int(row[0] or 0), "declining": int(row[1] or 0), "flat": int(row[2] or 0), "total": total}

    def coverage(self, *, scope: str = "industry") -> dict[str, Any]:
        row = self.db.execute(text("""
            SELECT MIN(trade_date), MAX(trade_date), COUNT(*), COUNT(DISTINCT trade_date)
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE deleted_at IS NULL
        """)).one()
        return {"firstDate": row[0].isoformat() if row[0] else None, "lastDate": row[1].isoformat() if row[1] else None, "rowCount": int(row[2] or 0), "tradeDayCount": int(row[3] or 0)}

    def soft_delete_trade_date(self, trade_date: date | str, *, scope: str = "industry") -> int:
        td = _to_date(trade_date)
        if td is None:
            return 0
        result = self.db.execute(text("""
            UPDATE cynexus_appl_market.mkt_ths_industry_fund_flow_daily
               SET deleted_at = now()
             WHERE trade_date = :td AND deleted_at IS NULL
        """), {"td": td})
        self.db.flush()
        return int(result.rowcount or 0)

    def purge_non_trading_days(self, *, scope: str = "industry") -> list[str]:
        return []


__all__ = ["ThsIndustryFundFlowRepository"]
