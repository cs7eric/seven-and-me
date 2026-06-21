r"""THS industry fund-flow service backed by Postgres.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\industry-concept-fund-flow-postgres-migration.md`

后续如果调整抓取写库时机、交易日判定、历史导入策略或 API 契约，
请先更新设计文档，再改这里；改完代码后也要同步回写设计文档。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository
from backend.utils.trading_day import (
    beijing_today,
    can_request_live_fund_flow_snapshot,
    resolve_fund_flow_read_trade_date,
)

logger = logging.getLogger(__name__)


def _resolve_trade_date(explicit_trade_date: date | str | None = None) -> date:
    if explicit_trade_date is not None:
        if isinstance(explicit_trade_date, date):
            return explicit_trade_date
        return date.fromisoformat(str(explicit_trade_date))
    return beijing_today()


def _enrich_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from backend.services.stock.f10.ths_industry_service import name_to_code

    for row in rows:
        if row.get("code"):
            continue
        industry_name = row.get("行业")
        if isinstance(industry_name, str) and industry_name:
            row["code"] = name_to_code(industry_name) or None
    return rows


class ThsIndustryFundFlowService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ThsIndustryFundFlowRepository(db)

    def ensure_bootstrapped(self) -> None:
        self.repo.ensure_bootstrapped(scope="industry")

    def get_industry_fund_flow(
        self,
        *,
        refresh: bool = False,
        trade_date: date | str | None = None,
        top: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_bootstrapped()
        if refresh:
            try:
                payload = self.refresh_industry_fund_flow(trade_date=trade_date)
            except Exception as exc:  # noqa: BLE001
                logger.exception("refresh_industry_fund_flow failed")
                fallback = self.repo.get_daily_payload(
                    resolve_fund_flow_read_trade_date(trade_date),
                    scope="industry",
                )
                if fallback is None:
                    return {
                        "ok": False,
                        "tradeDate": _resolve_trade_date(trade_date).isoformat(),
                        "rowCount": 0,
                        "rows": [],
                        "error": str(exc),
                    }
                fallback = dict(fallback)
                fallback["stale"] = True
                fallback["staleReason"] = str(exc)
                fallback["rows"] = _enrich_codes(list(fallback.get("rows") or []))
                if top is not None:
                    fallback["rows"] = fallback["rows"][:top]
                    fallback["rowCount"] = len(fallback["rows"])
                return fallback
            payload["rows"] = _enrich_codes(list(payload.get("rows") or []))
            if top is not None:
                payload["rows"] = payload["rows"][:top]
                payload["rowCount"] = len(payload["rows"])
            return payload

        payload = self.repo.get_daily_payload(
            resolve_fund_flow_read_trade_date(trade_date),
            scope="industry",
        )
        if payload is None:
            return {
                "ok": False,
                "tradeDate": _resolve_trade_date(trade_date).isoformat(),
                "rowCount": 0,
                "rows": [],
                "error": "no industry fund-flow snapshot found",
            }
        payload = dict(payload)
        payload["rows"] = _enrich_codes(list(payload.get("rows") or []))
        if top is not None:
            payload["rows"] = payload["rows"][:top]
            payload["rowCount"] = len(payload["rows"])
        return payload

    def refresh_industry_fund_flow(self, *, trade_date: date | str | None = None) -> dict[str, Any]:
        from backend.adapters.market.ths_fund_flow_adapter import fetch_industry_fund_flow_all

        target_trade_date = _resolve_trade_date(trade_date)
        if not can_request_live_fund_flow_snapshot(target_trade_date):
            read_trade_date = resolve_fund_flow_read_trade_date(target_trade_date)
            payload = self.repo.get_daily_payload(read_trade_date, scope="industry")
            if payload is None:
                return {
                    "ok": False,
                    "tradeDate": read_trade_date.isoformat(),
                    "rowCount": 0,
                    "rows": [],
                    "error": "non-trading day or pre-market; no persisted previous trading-day snapshot",
                }
            payload = dict(payload)
            payload["rows"] = _enrich_codes(list(payload.get("rows") or []))
            payload["skippedFetch"] = True
            payload["skipReason"] = "non_trading_day_or_pre_market"
            return payload
        raw = fetch_industry_fund_flow_all()
        payload = self.repo.replace_trade_day_snapshot(
            trade_date=target_trade_date,
            raw_payload=raw,
            scope="industry",
            source_type="crawler",
            source="ths.10jqka.com.cn",
        )
        payload["rows"] = _enrich_codes(list(payload.get("rows") or []))
        return payload

    def list_history_dates(self) -> list[str]:
        self.ensure_bootstrapped()
        return self.repo.list_trade_dates(scope="industry")

    def read_history(self, trade_date: date | str) -> dict[str, Any] | None:
        self.ensure_bootstrapped()
        payload = self.repo.get_daily_payload(trade_date, scope="industry")
        if payload is None:
            return None
        payload = dict(payload)
        payload["rows"] = _enrich_codes(list(payload.get("rows") or []))
        return payload


def get_industry_fund_flow(
    db: Session,
    *,
    refresh: bool = False,
    trade_date: date | str | None = None,
    top: int | None = None,
) -> dict[str, Any]:
    return ThsIndustryFundFlowService(db).get_industry_fund_flow(
        refresh=refresh,
        trade_date=trade_date,
        top=top,
    )


def refresh_industry_fund_flow(db: Session, *, trade_date: date | str | None = None) -> dict[str, Any]:
    return ThsIndustryFundFlowService(db).refresh_industry_fund_flow(trade_date=trade_date)


def list_history_dates(db: Session) -> list[str]:
    return ThsIndustryFundFlowService(db).list_history_dates()


def read_history(db: Session, trade_date: date | str) -> dict[str, Any] | None:
    return ThsIndustryFundFlowService(db).read_history(trade_date)


__all__ = ["ThsIndustryFundFlowService"]
