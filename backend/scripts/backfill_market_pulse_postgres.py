r"""Backfill market pulse Postgres tables from legacy DuckDB / JSON sources.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-pulse-postgres-migration.md`
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.config.database import session_scope
from backend.repositories.market.market_pulse_pg_repo import MarketPulseRepository
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    with session_scope() as db:
        repo = MarketPulseRepository(db)
        stats = repo.backfill_from_legacy_sources()
        removed = repo.purge_non_trading_days()
        coverage = repo.coverage()
    print(
        json.dumps(
            {
                "ok": True,
                "backfill": stats,
                "removedNonTradingDates": removed,
                "coverage": coverage,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
