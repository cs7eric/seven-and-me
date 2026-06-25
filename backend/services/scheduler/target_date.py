"""Helpers for scheduler manual target-date overrides."""
from __future__ import annotations

from datetime import date
from typing import Any

from backend.services.stock.trading_day_resolver import resolve_target_trading_day


def normalize_target_date(value: Any) -> date | None:
    """Parse an optional YYYY-MM-DD value into a date."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError("target_date must be YYYY-MM-DD")


def resolve_scheduler_target_date(today: date, requested: Any = None) -> date:
    """Resolve the scheduler target trade date.

    Automatic runs pass no requested value and keep the existing behavior:
    resolve from the current Beijing date. Manual runs may pass a selected
    date, which is also normalized to a target trading day.
    """
    selected = normalize_target_date(requested) or today
    return resolve_target_trading_day(selected)
