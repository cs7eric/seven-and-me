r"""Market Overview Postgres repository — 大盘成交额 / 主力净流入.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md`

后续如果调整表结构、写读规则、API 返回字段或历史导入逻辑，
请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.models.market_overview import MarketOverviewSnapshot

logger = logging.getLogger(__name__)

# 所有数值字段 (用于 upsert 时 COALESCE 合并)
_NUMERIC_FIELDS = [
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
]

# 字段类型分组 (用于 COALESCE 时类型转换)
_NUMERIC_TYPES = {"numeric(18,4)", "numeric(6,2)"}
_INT_TYPES = {"integer"}


def _to_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _merge_source(existing_source: str | None, new_source: str) -> str:
    """合并 source 标记: 去重 + '+' 拼接."""
    if not existing_source:
        return new_source
    parts = set(existing_source.split("+"))
    parts.add(new_source)
    return "+".join(sorted(parts))


def _row_to_dict(row: MarketOverviewSnapshot) -> dict[str, Any]:
    """ORM row → 前端兼容 dict (snake_case)."""
    return {
        "trade_date": row.trade_date.isoformat(),
        "total_amount": float(row.total_amount) if row.total_amount is not None else None,
        "total_volume": float(row.total_volume) if row.total_volume is not None else None,
        "rising_count": row.rising_count,
        "falling_count": row.falling_count,
        "flat_count": row.flat_count,
        "limit_up_count": row.limit_up_count,
        "limit_down_count": row.limit_down_count,
        "stock_count": row.stock_count,
        "main_net_inflow": float(row.main_net_inflow) if row.main_net_inflow is not None else None,
        "super_large_net_inflow": float(row.super_large_net_inflow) if row.super_large_net_inflow is not None else None,
        "large_net_inflow": float(row.large_net_inflow) if row.large_net_inflow is not None else None,
        "medium_net_inflow": float(row.medium_net_inflow) if row.medium_net_inflow is not None else None,
        "small_net_inflow": float(row.small_net_inflow) if row.small_net_inflow is not None else None,
        "main_net_inflow_ratio": float(row.main_net_inflow_ratio) if row.main_net_inflow_ratio is not None else None,
        "super_large_net_ratio": float(row.super_large_net_ratio) if row.super_large_net_ratio is not None else None,
        "large_net_ratio": float(row.large_net_ratio) if row.large_net_ratio is not None else None,
        "medium_net_ratio": float(row.medium_net_ratio) if row.medium_net_ratio is not None else None,
        "small_net_ratio": float(row.small_net_ratio) if row.small_net_ratio is not None else None,
        "source": row.source,
        "is_manual_override": row.is_manual_override,
        "manual_updated_at": row.manual_updated_at.isoformat() if row.manual_updated_at else None,
    }


def _alive() -> Select[tuple[MarketOverviewSnapshot]]:
    return select(MarketOverviewSnapshot).where(MarketOverviewSnapshot.deleted_at.is_(None))


class MarketOverviewPgRepository:
    """PostgreSQL 读写 market_overview_snapshots."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(
        self,
        trade_date: date | str,
        fields: dict[str, Any],
        source_tag: str = "unknown",
    ) -> dict[str, Any]:
        """COALESCE 风格 upsert: 已有字段不被覆盖, 缺失字段补入.

        Args:
            trade_date: 交易日
            fields: 要写入的字段 (snake_case, e.g. total_amount, main_net_inflow, ...)
            source_tag: 数据来源标记 (akshare / eltdx / manual)

        Returns:
            写入/更新后的完整行 dict.
        """
        td = _to_date(trade_date)
        if td is None:
            raise ValueError(f"invalid trade_date: {trade_date}")

        # 读当前行 (如有)
        existing = self.db.scalar(
            _alive().where(MarketOverviewSnapshot.trade_date == td).limit(1)
        )

        if existing is None:
            # INSERT
            cleaned = {"trade_date": td, "source": source_tag}
            for k in _NUMERIC_FIELDS:
                v = fields.get(k)
                if v is not None:
                    if k in {"rising_count", "falling_count", "flat_count",
                             "limit_up_count", "limit_down_count", "stock_count"}:
                        cleaned[k] = _parse_int(v)
                    else:
                        cleaned[k] = _parse_decimal(v)

            if source_tag == "manual":
                cleaned["is_manual_override"] = True
                cleaned["manual_updated_at"] = datetime.now()

            row = MarketOverviewSnapshot(**cleaned)
            self.db.add(row)
            self.db.flush()
            logger.info("market_overview_pg: inserted %s (source=%s)", td, source_tag)
            return _row_to_dict(row)

        # UPDATE — COALESCE 字段 (已有值保留, 新值补入)
        changed = False
        for k in _NUMERIC_FIELDS:
            v = fields.get(k)
            if v is None:
                continue
            current = getattr(existing, k)
            if current is not None:
                continue  # 不覆盖已有值
            if k in {"rising_count", "falling_count", "flat_count",
                     "limit_up_count", "limit_down_count", "stock_count"}:
                setattr(existing, k, _parse_int(v))
            else:
                setattr(existing, k, _parse_decimal(v))
            changed = True

        if source_tag == "manual":
            existing.is_manual_override = True
            existing.manual_updated_at = datetime.now()
            changed = True

        # 合并 source 标记
        new_source = _merge_source(existing.source, source_tag)
        if new_source != existing.source:
            existing.source = new_source
            changed = True

        if changed:
            self.db.flush()
            logger.info("market_overview_pg: updated %s (source=%s)", td, source_tag)

        return _row_to_dict(existing)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, trade_date: date | str) -> dict[str, Any] | None:
        """查询指定交易日数据."""
        td = _to_date(trade_date)
        if td is None:
            return None
        row = self.db.scalar(
            _alive().where(MarketOverviewSnapshot.trade_date == td).limit(1)
        )
        return _row_to_dict(row) if row else None

    def get_latest(self, trade_date: date | str | None = None) -> dict[str, Any] | None:
        """获取 <= trade_date 的最新一条数据 (用于非交易日回退)."""
        td = _to_date(trade_date) if trade_date else date.today()
        if td is None:
            td = date.today()
        row = self.db.scalar(
            _alive()
            .where(MarketOverviewSnapshot.trade_date <= td)
            .order_by(MarketOverviewSnapshot.trade_date.desc())
            .limit(1)
        )
        return _row_to_dict(row) if row else None

    def get_history(
        self,
        days: int = 60,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """获取历史序列, 按 trade_date ASC."""
        end = _to_date(end_date) if end_date else date.today()
        stmt = (
            _alive()
            .where(MarketOverviewSnapshot.trade_date <= end)
            .order_by(MarketOverviewSnapshot.trade_date.desc())
            .limit(max(1, min(days, 1000)))
        )
        rows = self.db.scalars(stmt).all()
        rows.reverse()  # ASC
        return [_row_to_dict(r) for r in rows]

    def coverage(self) -> dict[str, Any]:
        """统计: 首日 / 末日 / 行数."""
        row = self.db.execute(
            select(
                func.min(MarketOverviewSnapshot.trade_date),
                func.max(MarketOverviewSnapshot.trade_date),
                func.count(MarketOverviewSnapshot.id),
            ).where(MarketOverviewSnapshot.deleted_at.is_(None))
        ).one()
        return {
            "first_date": row[0].isoformat() if row[0] else None,
            "last_date": row[1].isoformat() if row[1] else None,
            "row_count": int(row[2] or 0),
        }

    def has_trade_date(self, trade_date: date | str) -> bool:
        td = _to_date(trade_date)
        if td is None:
            return False
        return bool(
            self.db.scalar(
                select(func.count()).select_from(MarketOverviewSnapshot).where(
                    MarketOverviewSnapshot.trade_date == td,
                    MarketOverviewSnapshot.deleted_at.is_(None),
                )
            )
        )


__all__ = ["MarketOverviewPgRepository"]
