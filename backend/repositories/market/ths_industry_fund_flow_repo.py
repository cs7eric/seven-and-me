r"""THS industry fund-flow Postgres repository.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\industry-concept-fund-flow-postgres-migration.md`

后续如果调整表结构、抓取写入时机、交易日归档口径、API 返回字段或历史导入逻辑，
请先更新设计文档，再改这里；改完代码后也要同步回写设计文档。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.orm import Session

from backend.models.sector_fund_flow import SectorFundFlowBatch, SectorFundFlowSnapshot
from backend.utils.trading_day import is_trade_date_confirmed_by_tencent
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

_HISTORY_DIR = Path("F:/dev-repo/mp4-to-word-new/reference/ths-fund-flow/history")
_LATEST_FILE = Path("F:/dev-repo/mp4-to-word-new/reference/ths-fund-flow/latest.json")


def _to_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


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
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None


def _batch_to_payload(batch: SectorFundFlowBatch, rows: list[SectorFundFlowSnapshot]) -> dict[str, Any]:
    return {
        "ok": True,
        "tradeDate": batch.trade_date.isoformat(),
        "rowCount": batch.row_count,
        "totalPages": batch.total_pages,
        "pageRowCounts": batch.page_row_counts or [],
        "fetchedAt": batch.fetched_at.isoformat(),
        "rows": [_snapshot_to_payload(row) for row in rows],
        "source": batch.source,
    }


def _snapshot_to_payload(row: SectorFundFlowSnapshot) -> dict[str, Any]:
    return {
        "序号": int(row.rank or 0),
        "行业": row.sector_name,
        "code": row.sector_code,
        "行业指数涨跌幅": _to_float(row.change_pct),
        "流入资金(亿)": _to_float(row.inflow),
        "流出资金(亿)": _to_float(row.outflow),
        "净额(亿)": _to_float(row.net),
        "公司家数": _to_int(row.company_count),
        "领涨股": row.leader_stock,
        "领涨股涨跌幅": _to_float(row.leader_change),
        "当前价(元)": _to_float(row.leader_price),
        "tradeDate": row.trade_date.isoformat(),
        "source": row.source,
    }


def _legacy_row_to_snapshot(row: dict[str, Any]) -> dict[str, Any] | None:
    sector_name = _strip(row.get("行业") or row.get("industry"))
    if not sector_name:
        return None
    return {
        "sector_code": _strip(row.get("code") or row.get("industryCode") or row.get("industry_code")),
        "sector_name": sector_name,
        "rank": _to_int(row.get("序号") or row.get("rank")),
        "change_pct": _to_float(row.get("行业指数涨跌幅") or row.get("changePct") or row.get("change_pct")),
        "inflow": _to_float(row.get("流入资金(亿)") or row.get("inflow")),
        "outflow": _to_float(row.get("流出资金(亿)") or row.get("outflow")),
        "net": _to_float(row.get("净额(亿)") or row.get("net")),
        "company_count": _to_int(row.get("公司家数") or row.get("companyCount") or row.get("company_count")),
        "leader_stock": _strip(row.get("领涨股") or row.get("leaderStock") or row.get("leader_stock")),
        "leader_change": _to_float(row.get("领涨股涨跌幅") or row.get("leaderChange") or row.get("leader_change")),
        "leader_price": _to_float(row.get("当前价(元)") or row.get("leaderPrice") or row.get("leader_price")),
        "extra": row,
    }


class ThsIndustryFundFlowRepository:
    def __init__(self, db: Session):
        self.db = db

    def _alive_batches(self, scope: str = "industry") -> Select[tuple[SectorFundFlowBatch]]:
        return select(SectorFundFlowBatch).where(
            SectorFundFlowBatch.scope == scope,
            SectorFundFlowBatch.deleted_at.is_(None),
        )

    def _alive_snapshots(self, scope: str = "industry") -> Select[tuple[SectorFundFlowSnapshot]]:
        return select(SectorFundFlowSnapshot).where(
            SectorFundFlowSnapshot.scope == scope,
            SectorFundFlowSnapshot.deleted_at.is_(None),
        )

    def ensure_bootstrapped(self, scope: str = "industry") -> None:
        if self.latest_trade_date(scope=scope) is not None:
            return
        if not _HISTORY_DIR.exists():
            return
        history_files = sorted(_HISTORY_DIR.glob("*.json"))
        imported_any = False
        for path in history_files:
            payload = read_json_file(path, {})
            if not isinstance(payload, dict):
                continue
            trade_date = _to_date(path.stem)
            if trade_date is None:
                continue
            if is_trade_date_confirmed_by_tencent(trade_date) is not True:
                logger.info("skip non-trading history snapshot: %s", path.name)
                continue
            if self.has_trade_date(trade_date, scope=scope):
                continue
            self.replace_trade_day_snapshot(
                trade_date=trade_date,
                raw_payload=payload,
                scope=scope,
                source_type="json_import",
                source=str(payload.get("source") or "reference/ths-fund-flow/history"),
                fetched_at=_to_datetime(payload.get("archivedAt") or payload.get("fetchedAt")),
            )
            imported_any = True
        if not imported_any and _LATEST_FILE.exists():
            payload = read_json_file(_LATEST_FILE, {})
            if isinstance(payload, dict):
                fetched_at = _to_datetime(payload.get("fetchedAt")) or datetime.now()
                trade_date = fetched_at.date()
                if is_trade_date_confirmed_by_tencent(trade_date) is not True:
                    return
                self.replace_trade_day_snapshot(
                    trade_date=trade_date,
                    raw_payload=payload,
                    scope=scope,
                    source_type="json_import",
                    source=str(payload.get("source") or "reference/ths-fund-flow/latest.json"),
                    fetched_at=fetched_at,
                )

    def has_trade_date(self, trade_date: date | str, *, scope: str = "industry") -> bool:
        td = _to_date(trade_date)
        if td is None:
            return False
        stmt = select(func.count()).select_from(SectorFundFlowBatch).where(
            SectorFundFlowBatch.scope == scope,
            SectorFundFlowBatch.trade_date == td,
            SectorFundFlowBatch.deleted_at.is_(None),
        )
        return bool(self.db.scalar(stmt))

    def latest_trade_date(self, *, scope: str = "industry") -> date | None:
        return self.db.scalar(
            select(func.max(SectorFundFlowBatch.trade_date)).where(
                SectorFundFlowBatch.scope == scope,
                SectorFundFlowBatch.deleted_at.is_(None),
            )
        )

    def list_trade_dates(self, *, scope: str = "industry", limit: int = 365) -> list[str]:
        stmt = (
            select(SectorFundFlowBatch.trade_date)
            .where(
                SectorFundFlowBatch.scope == scope,
                SectorFundFlowBatch.deleted_at.is_(None),
            )
            .order_by(SectorFundFlowBatch.trade_date.desc())
            .limit(max(1, min(limit, 1000)))
        )
        return [td.isoformat() for td in self.db.scalars(stmt).all()]

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
        if source_type not in {"crawler", "json_import"}:
            raise ValueError("source_type must be crawler or json_import")
        fetched_dt = fetched_at or _to_datetime(raw_payload.get("fetchedAt")) or datetime.now()
        raw_rows = raw_payload.get("rows") or []
        normalized_rows = [_legacy_row_to_snapshot(row) for row in raw_rows if isinstance(row, dict)]
        normalized_rows = [row for row in normalized_rows if row is not None]
        normalized_rows.sort(key=lambda row: (row.get("net") or float("-inf"), row.get("change_pct") or float("-inf")), reverse=True)
        for idx, row in enumerate(normalized_rows, start=1):
            row["rank"] = idx

        self.db.execute(
            update(SectorFundFlowSnapshot)
            .where(
                SectorFundFlowSnapshot.scope == scope,
                SectorFundFlowSnapshot.trade_date == td,
                SectorFundFlowSnapshot.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        self.db.execute(
            update(SectorFundFlowBatch)
            .where(
                SectorFundFlowBatch.scope == scope,
                SectorFundFlowBatch.trade_date == td,
                SectorFundFlowBatch.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), status="partial")
        )

        batch = SectorFundFlowBatch(
            scope=scope,
            trade_date=td,
            source_type=source_type,
            status="success",
            source=source,
            total_pages=_to_int(raw_payload.get("totalPages")),
            row_count=len(normalized_rows),
            page_row_counts=list(raw_payload.get("pageRowCounts") or []),
            fetched_at=fetched_dt,
            extra={
                "rowCount": raw_payload.get("rowCount"),
                "importedFrom": raw_payload.get("importedFrom"),
            },
            remark="direct crawler write" if source_type == "crawler" else "bootstrapped from legacy JSON",
        )
        self.db.add(batch)
        self.db.flush()

        for row in normalized_rows:
            self.db.add(
                SectorFundFlowSnapshot(
                    batch_id=batch.id,
                    scope=scope,
                    trade_date=td,
                    sector_code=row["sector_code"],
                    sector_name=row["sector_name"],
                    rank=row["rank"],
                    change_pct=row["change_pct"],
                    inflow=row["inflow"],
                    outflow=row["outflow"],
                    net=row["net"],
                    company_count=row["company_count"],
                    leader_stock=row["leader_stock"],
                    leader_change=row["leader_change"],
                    leader_price=row["leader_price"],
                    source=source,
                    source_type=source_type,
                    captured_at=fetched_dt,
                    extra=row["extra"],
                )
            )
        self.db.flush()
        return self.get_daily_payload(td, scope=scope) or {
            "ok": True,
            "tradeDate": td.isoformat(),
            "rowCount": len(normalized_rows),
            "totalPages": batch.total_pages,
            "pageRowCounts": batch.page_row_counts,
            "fetchedAt": fetched_dt.isoformat(),
            "rows": [],
        }

    def get_daily_payload(self, trade_date: date | str | None = None, *, scope: str = "industry") -> dict[str, Any] | None:
        td = _to_date(trade_date) if trade_date is not None else self.latest_trade_date(scope=scope)
        if td is None:
            return None
        batch = self.db.scalar(
            self._alive_batches(scope)
            .where(SectorFundFlowBatch.trade_date == td)
            .order_by(SectorFundFlowBatch.fetched_at.desc())
            .limit(1)
        )
        if batch is None:
            return None
        rows = self.db.scalars(
            self._alive_snapshots(scope)
            .where(SectorFundFlowSnapshot.trade_date == td)
            .order_by(SectorFundFlowSnapshot.net.desc(), SectorFundFlowSnapshot.rank.asc())
        ).all()
        if not rows:
            return None
        return _batch_to_payload(batch, rows)

    def get_fund_flow_daily(self, trade_date: date | str, *, scope: str = "industry") -> list[dict[str, Any]]:
        payload = self.get_daily_payload(trade_date, scope=scope)
        if payload is None:
            return []
        return payload["rows"]

    def get_fund_flow_daily_topn(self, trade_date: date | str, top_n: int = 10, *, scope: str = "industry") -> dict[str, Any]:
        rows = self.get_fund_flow_daily(trade_date, scope=scope)
        if not rows:
            td = _to_date(trade_date)
            return {
                "tradeDate": td.isoformat() if td else None,
                "topN": top_n,
                "top": [],
                "bottom": [],
                "count": 0,
            }
        return {
            "tradeDate": rows[0]["tradeDate"],
            "topN": top_n,
            "top": rows[:top_n],
            "bottom": list(reversed(rows[-top_n:])) if len(rows) >= top_n else list(reversed(rows)),
            "count": len(rows),
        }

    def get_fund_flow_history(self, days: int = 10, top_n: int | None = None, *, scope: str = "industry") -> list[dict[str, Any]]:
        trade_dates = self.list_trade_dates(scope=scope, limit=max(1, min(days, 365)))
        out: list[dict[str, Any]] = []
        for trade_date in trade_dates:
            rows = self.get_fund_flow_daily(trade_date, scope=scope)
            if top_n is not None:
                rows = rows[:top_n]
            out.append({"tradeDate": trade_date, "items": rows})
        return out

    def get_fund_flow_for_industry(
        self,
        industry: str,
        days: int = 30,
        *,
        end: date | str | None = None,
        scope: str = "industry",
    ) -> list[dict[str, Any]]:
        if not industry:
            return []
        stmt = self._alive_snapshots(scope).where(SectorFundFlowSnapshot.sector_name == industry)
        end_date = _to_date(end)
        if end_date is not None:
            stmt = stmt.where(SectorFundFlowSnapshot.trade_date <= end_date)
        rows = self.db.scalars(
            stmt.order_by(SectorFundFlowSnapshot.trade_date.desc()).limit(max(1, min(days, 365)))
        ).all()
        return [_snapshot_to_payload(row) for row in reversed(rows)]

    def list_industries_with_data(self, days: int = 30, *, scope: str = "industry") -> list[dict[str, Any]]:
        latest_dates = self.list_trade_dates(scope=scope, limit=max(1, min(days, 365)))
        if not latest_dates:
            return []
        cutoff = _to_date(latest_dates[-1])
        if cutoff is None:
            return []
        rows = self.db.execute(
            select(
                SectorFundFlowSnapshot.sector_name,
                SectorFundFlowSnapshot.sector_code,
                func.count().label("days"),
                func.min(SectorFundFlowSnapshot.trade_date).label("first_date"),
                func.max(SectorFundFlowSnapshot.trade_date).label("last_date"),
            )
            .where(
                SectorFundFlowSnapshot.scope == scope,
                SectorFundFlowSnapshot.deleted_at.is_(None),
                SectorFundFlowSnapshot.trade_date >= cutoff,
            )
            .group_by(SectorFundFlowSnapshot.sector_name, SectorFundFlowSnapshot.sector_code)
            .order_by(SectorFundFlowSnapshot.sector_name.asc())
        ).all()
        return [
            {
                "industry": sector_name,
                "industryCode": sector_code,
                "days": int(count_days or 0),
                "firstDate": first_date.isoformat() if first_date else None,
                "lastDate": last_date.isoformat() if last_date else None,
            }
            for sector_name, sector_code, count_days, first_date, last_date in rows
        ]

    def get_sector_breadth_input(self, trade_date: date | str, *, scope: str = "industry") -> dict[str, Any] | None:
        td = _to_date(trade_date)
        if td is None:
            return None
        row = self.db.execute(
            select(
                func.sum(case((SectorFundFlowSnapshot.change_pct > 0, 1), else_=0)),
                func.sum(case((SectorFundFlowSnapshot.change_pct < 0, 1), else_=0)),
                func.sum(case((SectorFundFlowSnapshot.change_pct == 0, 1), else_=0)),
                func.count(SectorFundFlowSnapshot.id),
            ).where(
                SectorFundFlowSnapshot.scope == scope,
                SectorFundFlowSnapshot.trade_date == td,
                SectorFundFlowSnapshot.deleted_at.is_(None),
            )
        ).one()
        total = int(row[3] or 0)
        if total == 0:
            return None
        return {
            "advancing": int(row[0] or 0),
            "declining": int(row[1] or 0),
            "flat": int(row[2] or 0),
            "total": total,
        }

    def coverage(self, *, scope: str = "industry") -> dict[str, Any]:
        row = self.db.execute(
            select(
                func.min(SectorFundFlowBatch.trade_date),
                func.max(SectorFundFlowBatch.trade_date),
                func.sum(SectorFundFlowBatch.row_count),
                func.count(SectorFundFlowBatch.id),
            ).where(
                SectorFundFlowBatch.scope == scope,
                SectorFundFlowBatch.deleted_at.is_(None),
            )
        ).one()
        return {
            "firstDate": row[0].isoformat() if row[0] else None,
            "lastDate": row[1].isoformat() if row[1] else None,
            "rowCount": int(row[2] or 0),
            "tradeDayCount": int(row[3] or 0),
        }

    def soft_delete_trade_date(self, trade_date: date | str, *, scope: str = "industry") -> int:
        td = _to_date(trade_date)
        if td is None:
            return 0
        snapshots = self.db.execute(
            update(SectorFundFlowSnapshot)
            .where(
                SectorFundFlowSnapshot.scope == scope,
                SectorFundFlowSnapshot.trade_date == td,
                SectorFundFlowSnapshot.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        self.db.execute(
            update(SectorFundFlowBatch)
            .where(
                SectorFundFlowBatch.scope == scope,
                SectorFundFlowBatch.trade_date == td,
                SectorFundFlowBatch.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        self.db.flush()
        return int(snapshots.rowcount or 0)

    def purge_non_trading_days(self, *, scope: str = "industry") -> list[str]:
        alive_dates = self.list_trade_dates(scope=scope, limit=2000)
        removed: list[str] = []
        for trade_date in alive_dates:
            if is_trade_date_confirmed_by_tencent(trade_date) is True:
                continue
            self.soft_delete_trade_date(trade_date, scope=scope)
            removed.append(trade_date)
        return removed


__all__ = ["ThsIndustryFundFlowRepository"]
