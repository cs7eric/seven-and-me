r"""Market Pulse Postgres repository.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-pulse-postgres-migration.md`

后续如果调整表结构、交易日回退规则、抓取写入时机、历史导入逻辑或 API 返回字段，
请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from backend.config.settings import STOCK_UNIVERSE_DIR
from backend.models.market_pulse import MarketPulseCaptureBatch, MarketPulseSectorDailySnapshot
from backend.utils.json_io import read_json_file
from backend.utils.trading_day import is_trade_date_confirmed_by_tencent

logger = logging.getLogger(__name__)

_ROTATION_DIR = STOCK_UNIVERSE_DIR / "market_pulse" / "rotation"


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
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _snapshot_to_payload(row: MarketPulseSectorDailySnapshot) -> dict[str, Any]:
    return {
        "tradeDate": row.trade_date.isoformat(),
        "name": row.sector_name,
        "index": row.sector_index,
        "rank": int(row.rank_by_change or 0) if row.rank_by_change is not None else None,
        "changePct": _to_float(row.change_pct),
        "inflow": _to_float(row.inflow),
        "outflow": _to_float(row.outflow),
        "mainNet": _to_float(row.main_net),
        "stockCount": _to_int(row.stock_count),
        "leadingStock": row.leading_stock,
        "leadingChangePct": _to_float(row.leading_change_pct),
        "leadingPrice": _to_float(row.leading_price),
        "source": row.source_name,
    }


def _normalize_live_row(row: dict[str, Any]) -> dict[str, Any] | None:
    sector_name = _strip(row.get("name"))
    if not sector_name:
        return None
    return {
        "sector_name": sector_name,
        "sector_index": _strip(row.get("index")),
        "change_pct": _to_float(row.get("changePct")),
        "inflow": _to_float(row.get("inflow")),
        "outflow": _to_float(row.get("outflow")),
        "main_net": _to_float(row.get("mainNet")),
        "stock_count": _to_int(row.get("stockCount")),
        "leading_stock": _strip(row.get("leadingStock")),
        "leading_change_pct": _to_float(row.get("leadingChangePct")),
        "leading_price": _to_float(row.get("leadingPrice")),
        "extra": dict(row),
    }


def _normalize_duckdb_row(row: Any) -> dict[str, Any] | None:
    sector_name = _strip(getattr(row, "sector_name", None))
    if not sector_name:
        return None
    return {
        "sector_name": sector_name,
        "sector_index": _strip(getattr(row, "sector_index", None)),
        "change_pct": _to_float(getattr(row, "change_pct", None)),
        "inflow": _to_float(getattr(row, "inflow", None)),
        "outflow": _to_float(getattr(row, "outflow", None)),
        "main_net": _to_float(getattr(row, "main_net", None)),
        "stock_count": _to_int(getattr(row, "stock_count", None)),
        "leading_stock": _strip(getattr(row, "leading_stock", None)),
        "leading_change_pct": _to_float(getattr(row, "leading_change_pct", None)),
        "leading_price": _to_float(getattr(row, "leading_price", None)),
        "extra": {
            "legacy": "duckdb.market_pulse_sector_daily",
            "source": getattr(row, "source", None),
        },
    }


def _normalize_rotation_item(row: dict[str, Any]) -> dict[str, Any] | None:
    sector_name = _strip(row.get("name"))
    if not sector_name:
        return None
    return {
        "sector_name": sector_name,
        "sector_index": None,
        "change_pct": _to_float(row.get("changePct")),
        "inflow": _to_float(row.get("inflow")),
        "outflow": _to_float(row.get("outflow")),
        "main_net": _to_float(row.get("mainNet")),
        "stock_count": _to_int(row.get("stockCount")),
        "leading_stock": _strip(row.get("leadingStock")),
        "leading_change_pct": _to_float(row.get("leadingChangePct")),
        "leading_price": _to_float(row.get("leadingPrice")),
        "extra": dict(row),
    }


class MarketPulseRepository:
    def __init__(self, db: Session):
        self.db = db

    def _alive_batches(self) -> Select[tuple[MarketPulseCaptureBatch]]:
        return select(MarketPulseCaptureBatch).where(MarketPulseCaptureBatch.deleted_at.is_(None))

    def _alive_snapshots(self) -> Select[tuple[MarketPulseSectorDailySnapshot]]:
        return select(MarketPulseSectorDailySnapshot).where(MarketPulseSectorDailySnapshot.deleted_at.is_(None))

    def ensure_bootstrapped(self) -> dict[str, int]:
        if self.latest_trade_date() is not None:
            return {"duckdbImportedDates": 0, "jsonImportedDates": 0}
        return self.backfill_from_legacy_sources()

    def backfill_from_legacy_sources(self) -> dict[str, int]:
        duckdb_imported = self._import_from_duckdb()
        json_imported = self._import_from_rotation_json()
        return {
            "duckdbImportedDates": duckdb_imported,
            "jsonImportedDates": json_imported,
        }

    def _import_from_duckdb(self) -> int:
        return 0

    def _import_from_rotation_json(self) -> int:
        if not _ROTATION_DIR.exists():
            return 0
        imported = 0
        for path in sorted(_ROTATION_DIR.glob("*.json")):
            trade_date = _to_date(path.stem)
            if trade_date is None or self.has_trade_date(trade_date):
                continue
            if is_trade_date_confirmed_by_tencent(trade_date) is not True:
                logger.info("skip rotation json non-trading snapshot: %s", path.name)
                continue
            payload = read_json_file(path, {})
            if not isinstance(payload, dict):
                continue
            rows = [_normalize_rotation_item(row) for row in (payload.get("items") or []) if isinstance(row, dict)]
            rows = [row for row in rows if row is not None]
            if not rows:
                continue
            self.replace_trade_day_snapshot(
                trade_date=trade_date,
                rows=rows,
                source_kind="json_import",
                source_name="reference.stock-universe.market_pulse.rotation",
                fetched_at=_to_datetime(payload.get("fetchedAt")) or datetime.now(),
                extra={"importedFrom": str(path)},
                remark="bootstrapped from legacy rotation top-n json",
            )
            imported += 1
        return imported

    def has_trade_date(self, trade_date: date | str) -> bool:
        td = _to_date(trade_date)
        if td is None:
            return False
        stmt = select(func.count()).select_from(MarketPulseCaptureBatch).where(
            MarketPulseCaptureBatch.trade_date == td,
            MarketPulseCaptureBatch.deleted_at.is_(None),
        )
        return bool(self.db.scalar(stmt))

    def latest_trade_date(self, *, end: date | str | None = None) -> date | None:
        stmt = select(func.max(MarketPulseCaptureBatch.trade_date)).where(MarketPulseCaptureBatch.deleted_at.is_(None))
        end_date = _to_date(end)
        if end_date is not None:
            stmt = stmt.where(MarketPulseCaptureBatch.trade_date <= end_date)
        return self.db.scalar(stmt)

    def list_trade_dates(self, *, limit: int = 365, end: date | str | None = None) -> list[str]:
        stmt = select(MarketPulseCaptureBatch.trade_date).where(MarketPulseCaptureBatch.deleted_at.is_(None))
        end_date = _to_date(end)
        if end_date is not None:
            stmt = stmt.where(MarketPulseCaptureBatch.trade_date <= end_date)
        stmt = stmt.order_by(MarketPulseCaptureBatch.trade_date.desc()).limit(max(1, min(limit, 2000)))
        return [item.isoformat() for item in self.db.scalars(stmt).all()]

    def get_trade_day_batch(self, trade_date: date | str) -> MarketPulseCaptureBatch | None:
        td = _to_date(trade_date)
        if td is None:
            return None
        return self.db.scalar(
            self._alive_batches()
            .where(MarketPulseCaptureBatch.trade_date == td)
            .order_by(MarketPulseCaptureBatch.fetched_at.desc())
            .limit(1)
        )

    def get_trade_day_rows(self, trade_date: date | str) -> list[dict[str, Any]]:
        td = _to_date(trade_date)
        if td is None:
            return []
        rows = self.db.scalars(
            self._alive_snapshots()
            .where(MarketPulseSectorDailySnapshot.trade_date == td)
            .order_by(
                MarketPulseSectorDailySnapshot.rank_by_change.asc().nullslast(),
                MarketPulseSectorDailySnapshot.change_pct.desc().nullslast(),
                MarketPulseSectorDailySnapshot.sector_name.asc(),
            )
        ).all()
        return [_snapshot_to_payload(row) for row in rows]

    def get_sector_row(self, trade_date: date | str, sector_name: str) -> dict[str, Any] | None:
        td = _to_date(trade_date)
        if td is None or not sector_name:
            return None
        row = self.db.scalar(
            self._alive_snapshots()
            .where(
                MarketPulseSectorDailySnapshot.trade_date == td,
                MarketPulseSectorDailySnapshot.sector_name == sector_name,
            )
            .limit(1)
        )
        return _snapshot_to_payload(row) if row else None

    def replace_trade_day_snapshot(
        self,
        *,
        trade_date: date | str,
        rows: list[dict[str, Any]],
        source_kind: str,
        source_name: str,
        fetched_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        td = _to_date(trade_date)
        if td is None:
            raise ValueError("trade_date is required")
        if source_kind not in {"live_capture", "duckdb_import", "json_import"}:
            raise ValueError("unsupported source_kind")
        normalized = [self._normalize_snapshot_row(row) for row in rows]
        normalized = [row for row in normalized if row is not None]
        normalized.sort(
            key=lambda row: (
                row.get("change_pct") is None,
                -(row.get("change_pct") or 0),
                row.get("sector_name") or "",
            )
        )
        for idx, row in enumerate(normalized, start=1):
            row["rank_by_change"] = idx

        self.db.execute(
            update(MarketPulseSectorDailySnapshot)
            .where(
                MarketPulseSectorDailySnapshot.trade_date == td,
                MarketPulseSectorDailySnapshot.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        self.db.execute(
            update(MarketPulseCaptureBatch)
            .where(
                MarketPulseCaptureBatch.trade_date == td,
                MarketPulseCaptureBatch.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), status="partial")
        )

        row_count = len(normalized)
        batch = MarketPulseCaptureBatch(
            trade_date=td,
            source_kind=source_kind,
            status="success" if row_count >= 80 else "partial",
            source_name=source_name,
            row_count=row_count,
            fetched_at=fetched_at or datetime.now(),
            extra=extra or {},
            remark=remark,
        )
        self.db.add(batch)
        self.db.flush()

        for row in normalized:
            self.db.add(
                MarketPulseSectorDailySnapshot(
                    batch_id=batch.id,
                    trade_date=td,
                    sector_name=row["sector_name"],
                    sector_index=row.get("sector_index"),
                    rank_by_change=row.get("rank_by_change"),
                    change_pct=row.get("change_pct"),
                    inflow=row.get("inflow"),
                    outflow=row.get("outflow"),
                    main_net=row.get("main_net"),
                    stock_count=row.get("stock_count"),
                    leading_stock=row.get("leading_stock"),
                    leading_change_pct=row.get("leading_change_pct"),
                    leading_price=row.get("leading_price"),
                    source_kind=source_kind,
                    source_name=source_name,
                    captured_at=fetched_at or datetime.now(),
                    extra=row.get("extra") or {},
                    remark=remark,
                )
            )
        self.db.flush()
        return {
            "tradeDate": td.isoformat(),
            "rowCount": row_count,
            "sourceKind": source_kind,
            "sourceName": source_name,
        }

    def purge_non_trading_days(self) -> list[str]:
        removed: list[str] = []
        for trade_date in self.list_trade_dates(limit=2000):
            if is_trade_date_confirmed_by_tencent(trade_date) is True:
                continue
            td = _to_date(trade_date)
            if td is None:
                continue
            self.db.execute(
                update(MarketPulseSectorDailySnapshot)
                .where(
                    MarketPulseSectorDailySnapshot.trade_date == td,
                    MarketPulseSectorDailySnapshot.deleted_at.is_(None),
                )
                .values(deleted_at=func.now())
            )
            self.db.execute(
                update(MarketPulseCaptureBatch)
                .where(
                    MarketPulseCaptureBatch.trade_date == td,
                    MarketPulseCaptureBatch.deleted_at.is_(None),
                )
                .values(deleted_at=func.now(), status="partial")
            )
            removed.append(trade_date)
        self.db.flush()
        return removed

    def coverage(self) -> dict[str, Any]:
        row = self.db.execute(
            select(
                func.min(MarketPulseCaptureBatch.trade_date),
                func.max(MarketPulseCaptureBatch.trade_date),
                func.sum(MarketPulseCaptureBatch.row_count),
                func.count(MarketPulseCaptureBatch.id),
            ).where(MarketPulseCaptureBatch.deleted_at.is_(None))
        ).one()
        return {
            "firstDate": row[0].isoformat() if row[0] else None,
            "lastDate": row[1].isoformat() if row[1] else None,
            "rowCount": int(row[2] or 0),
            "tradeDayCount": int(row[3] or 0),
        }

    @staticmethod
    def _normalize_snapshot_row(row: dict[str, Any]) -> dict[str, Any] | None:
        if "sector_name" in row:
            sector_name = _strip(row.get("sector_name"))
            if not sector_name:
                return None
            return {
                "sector_name": sector_name,
                "sector_index": _strip(row.get("sector_index")),
                "change_pct": _to_float(row.get("change_pct")),
                "inflow": _to_float(row.get("inflow")),
                "outflow": _to_float(row.get("outflow")),
                "main_net": _to_float(row.get("main_net")),
                "stock_count": _to_int(row.get("stock_count")),
                "leading_stock": _strip(row.get("leading_stock")),
                "leading_change_pct": _to_float(row.get("leading_change_pct")),
                "leading_price": _to_float(row.get("leading_price")),
                "extra": dict(row.get("extra") or {}),
            }
        return _normalize_live_row(row)


class _DuckRowAdapter:
    def __init__(self, row: Any):
        self.trade_date = row[0]
        self.sector_name = row[1]
        self.sector_index = row[2]
        self.change_pct = row[3]
        self.inflow = row[4]
        self.outflow = row[5]
        self.main_net = row[6]
        self.stock_count = row[7]
        self.leading_stock = row[8]
        self.leading_change_pct = row[9]
        self.leading_price = row[10]
        self.source = row[11]


__all__ = ["MarketPulseRepository"]
