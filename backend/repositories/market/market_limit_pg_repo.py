r"""Market Limit Postgres repository — 涨跌停情绪 (limit up/down sentiment).

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md`

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

from backend.models.market_limit import MarketLimitDailySnapshot, MarketLimitDailyStock

logger = logging.getLogger(__name__)

# 汇总字段 (写入时自 payload 提取)
_SUMMARY_FIELDS = [
    "limit_up_count",
    "limit_down_count",
    "touched_count",
    "broken_count",
    "break_board_rate",
    "max_streak_height",
    "promotion_overall_rate",
    "sentiment_level",
    "sentiment_text",
    "stock_count",
    "market_status",
    "data_status",
    "source",
]


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


def _row_to_dict(row: MarketLimitDailySnapshot) -> dict[str, Any]:
    """ORM row → dict (snake_case, 前兼容)."""
    return {
        "trade_date": row.trade_date.isoformat(),
        "limit_up_count": row.limit_up_count,
        "limit_down_count": row.limit_down_count,
        "touched_count": row.touched_count,
        "broken_count": row.broken_count,
        "break_board_rate": float(row.break_board_rate) if row.break_board_rate is not None else None,
        "max_streak_height": row.max_streak_height,
        "promotion_overall_rate": float(row.promotion_overall_rate) if row.promotion_overall_rate is not None else None,
        "sentiment_level": row.sentiment_level,
        "sentiment_text": row.sentiment_text,
        "stock_count": row.stock_count,
        "market_status": row.market_status,
        "data_status": row.data_status,
        "source": row.source,
    }


def _alive() -> Select[tuple[MarketLimitDailySnapshot]]:
    return select(MarketLimitDailySnapshot).where(MarketLimitDailySnapshot.deleted_at.is_(None))


class MarketLimitPgRepository:
    """PostgreSQL 读写 market_limit_daily_snapshots."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(
        self,
        trade_date: date | str,
        fields: dict[str, Any],
        *,
        source_tag: str = "realtime",
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """COALESCE 风格 upsert: 已有字段不被覆盖, 缺失字段补入.

        Args:
            trade_date: 交易日
            fields: 要写入的字段 (snake_case)
            source_tag: 数据来源标记
            extra_payload: 完整 computed payload (写入 extra jsonb)

        Returns:
            写入/更新后的完整行 dict.
        """
        td = _to_date(trade_date)
        if td is None:
            raise ValueError(f"invalid trade_date: {trade_date}")

        existing = self.db.scalar(
            _alive().where(MarketLimitDailySnapshot.trade_date == td).limit(1)
        )

        if existing is None:
            # INSERT
            cleaned: dict[str, Any] = {"trade_date": td, "source": source_tag}
            for k in _SUMMARY_FIELDS:
                v = fields.get(k)
                if v is not None:
                    if k in ("sentiment_level", "sentiment_text", "market_status", "data_status", "source"):
                        cleaned[k] = str(v)
                    elif k in ("limit_up_count", "limit_down_count", "touched_count",
                               "broken_count", "max_streak_height", "stock_count"):
                        cleaned[k] = _parse_int(v)
                    elif k in ("break_board_rate", "promotion_overall_rate"):
                        cleaned[k] = _parse_decimal(v)

            if extra_payload is not None:
                cleaned["extra"] = extra_payload

            row = MarketLimitDailySnapshot(**cleaned)
            self.db.add(row)
            self.db.flush()
            logger.debug("market_limit_pg: inserted %s (source=%s)", td, source_tag)
            return _row_to_dict(row)

        # UPDATE — COALESCE (已有值保留, 新值补入)
        changed = False
        for k in _SUMMARY_FIELDS:
            v = fields.get(k)
            if v is None:
                continue
            current = getattr(existing, k)
            if current is not None:
                continue
            setattr(existing, k, v)
            changed = True

        # 永远更新 extra (如果提供了)
        if extra_payload is not None:
            existing.extra = extra_payload
            changed = True

        # 合并 source
        if source_tag:
            existing.source = source_tag
            changed = True

        if changed:
            self.db.flush()
            logger.debug("market_limit_pg: updated %s (source=%s)", td, source_tag)

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
            _alive().where(MarketLimitDailySnapshot.trade_date == td).limit(1)
        )
        return _row_to_dict(row) if row else None

    def get_latest(self, trade_date: date | str | None = None) -> dict[str, Any] | None:
        """获取 <= trade_date 的最新一条数据 (非交易日回退)."""
        td = _to_date(trade_date) if trade_date else date.today()
        if td is None:
            td = date.today()
        row = self.db.scalar(
            _alive()
            .where(MarketLimitDailySnapshot.trade_date <= td)
            .order_by(MarketLimitDailySnapshot.trade_date.desc())
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
            .where(MarketLimitDailySnapshot.trade_date <= end)
            .order_by(MarketLimitDailySnapshot.trade_date.desc())
            .limit(max(1, min(days, 1000)))
        )
        rows = self.db.scalars(stmt).all()
        rows_reversed: list[MarketLimitDailySnapshot] = list(rows)[::-1]  # ASC
        return [_row_to_dict(r) for r in rows_reversed]

    def coverage(self) -> dict[str, Any]:
        """统计: 首日 / 末日 / 行数."""
        row = self.db.execute(
            select(
                func.min(MarketLimitDailySnapshot.trade_date),
                func.max(MarketLimitDailySnapshot.trade_date),
                func.count(MarketLimitDailySnapshot.id),
            ).where(MarketLimitDailySnapshot.deleted_at.is_(None))
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
                select(func.count()).select_from(MarketLimitDailySnapshot).where(
                    MarketLimitDailySnapshot.trade_date == td,
                    MarketLimitDailySnapshot.deleted_at.is_(None),
                )
            )
        )


    # ------------------------------------------------------------------
    # Stock-level data (涨跌停/炸板股票明细)
    # ------------------------------------------------------------------

    def upsert_stocks(
        self,
        trade_date: date | str,
        stocks: list[dict[str, Any]],
    ) -> int:
        """批量写入股票明细 (清旧写新).

        Args:
            trade_date: 交易日
            stocks: [{code, name, category, streak, changePct, limitUpPrice, limitDownPrice}, ...]

        Returns:
            写入行数.
        """
        td = _to_date(trade_date)
        if td is None:
            raise ValueError(f"invalid trade_date: {trade_date}")

        # 软删旧数据
        old = self.db.scalars(
            select(MarketLimitDailyStock).where(
                MarketLimitDailyStock.trade_date == td,
                MarketLimitDailyStock.deleted_at.is_(None),
            )
        ).all()
        now_dt = datetime.now()
        for o in old:
            o.deleted_at = now_dt

        count = 0
        for s in stocks:
            code = str(s.get("code") or "").strip()
            if not code:
                continue
            row = MarketLimitDailyStock(
                trade_date=td,
                code=code,
                name=str(s.get("name") or "")[:64] or None,
                category=str(s.get("category") or "limit_up"),
                streak=_parse_int(s.get("streak")),
                change_pct=_parse_decimal(s.get("changePct")),
                limit_up_price=_parse_decimal(s.get("limitUpPrice")),
                limit_down_price=_parse_decimal(s.get("limitDownPrice")),
            )
            self.db.add(row)
            count += 1

        self.db.flush()
        logger.debug("market_limit_pg: upserted %d stocks for %s", count, td)
        return count

    def get_stocks(
        self,
        trade_date: date | str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询指定交易日的股票明细.

        Args:
            trade_date: 交易日
            category: 过滤分类 (limit_up / limit_down / broken), None=全部

        Returns:
            [{code, name, category, streak, changePct, limitUpPrice, limitDownPrice}, ...]
        """
        td = _to_date(trade_date)
        if td is None:
            return []
        stmt = (
            select(MarketLimitDailyStock)
            .where(
                MarketLimitDailyStock.trade_date == td,
                MarketLimitDailyStock.deleted_at.is_(None),
            )
            .order_by(MarketLimitDailyStock.streak.desc().nulls_last(),
                      MarketLimitDailyStock.code)
        )
        if category:
            stmt = stmt.where(MarketLimitDailyStock.category == category)
        rows = self.db.scalars(stmt).all()
        return [
            {
                "code": r.code,
                "name": r.name,
                "category": r.category,
                "streak": r.streak,
                "changePct": float(r.change_pct) if r.change_pct is not None else None,
                "limitUpPrice": float(r.limit_up_price) if r.limit_up_price is not None else None,
                "limitDownPrice": float(r.limit_down_price) if r.limit_down_price is not None else None,
            }
            for r in rows
        ]


__all__ = ["MarketLimitPgRepository"]
