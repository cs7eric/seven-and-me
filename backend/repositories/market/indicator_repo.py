"""技术指标与 MA 计数仓储 — ClickHouse source + PostgreSQL cache.

This module preserves the long-lived public function names used by the API and
maintenance scripts, but the runtime data source has moved from DuckDB to
ClickHouse/PostgreSQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import logging

from backend.adapters.market.clickhouse_store import command, query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.repositories.market.percentile_helper import enrich_history_scores, percentile_score
from backend.services.stock.trading_calendar import is_trading_day
from backend.repositories.market.stock_meta_repo import get_board_type, get_stock_meta, _codes_json

logger = logging.getLogger(__name__)
_DEFAULT_MA_WINDOWS = (5, 10, 20, 30, 60, 120, 250)


class _ClickHouseResult:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _ClickHouseCompatConn:
    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> _ClickHouseResult:
        sql_str = sql.lstrip().lower()
        if sql_str.startswith(("select", "with", "show", "describe")):
            rows = query_rows(sql.replace("?", "%s"), tuple(params or ()))
            return _ClickHouseResult(rows)
        command(sql.replace("?", "%s"), tuple(params or ()))
        return _ClickHouseResult([])

    def executemany(self, sql: str, params_seq: list[tuple[Any, ...]]) -> None:
        for params in params_seq:
            self.execute(sql, params)


@contextmanager
def conn(read_only: bool = False):
    yield _ClickHouseCompatConn()


def get_conn(read_only: bool = False) -> _ClickHouseCompatConn:
    return _ClickHouseCompatConn()


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


def _build_ma_select(windows: list[int]) -> str:
    parts = []
    for n in sorted(set(windows)):
        if n < 1:
            continue
        parts.append(
            f"AVG(close) OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW) AS ma{n}"
        )
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# 1. 单股技术指标
# ---------------------------------------------------------------------------

def calc_ma(
    code: str,
    windows: list[int] | tuple[int, ...] = _DEFAULT_MA_WINDOWS,
    end_date: date | str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    windows = sorted(set(int(w) for w in windows if int(w) >= 1))
    if not windows:
        return []
    ma_cols = _build_ma_select(windows)
    where = ["code = %s"]
    params: list[Any] = [code]
    if end_date is not None:
        where.append("trade_date <= %s")
        params.append(_to_date(end_date))
    where_sql = " AND ".join(where)
    if limit is not None:
        sql = f"SELECT trade_date, close, {ma_cols} FROM (SELECT trade_date, close, {ma_cols} FROM daily_qfq WHERE {where_sql} ORDER BY trade_date DESC LIMIT %s) ORDER BY trade_date ASC"
        params.append(int(limit))
    else:
        sql = f"SELECT trade_date, close, {ma_cols} FROM daily_qfq WHERE {where_sql} ORDER BY trade_date ASC"
    rows = query_rows(sql, tuple(params))
    out: list[dict[str, Any]] = []
    for r in rows:
        d: dict[str, Any] = {"trade_date": r[0].isoformat(), "close": float(r[1])}
        for i, n in enumerate(windows):
            val = r[2 + i]
            d[f"ma{n}"] = float(val) if val is not None else None
        out.append(d)
    return out


def _ema_expr(col_name: str, span: int) -> str:
    alpha = 2.0 / (span + 1)
    decay = 1.0 - alpha
    parts = []
    for i in range(span):
        w = decay ** (span - 1 - i)
        parts.append(f"{w:.10f} * COALESCE(lag({col_name}, {i}) OVER w_, {col_name})")
    weights = " + ".join(parts)
    weight_sum = sum(decay ** i for i in range(span))
    return f"({weights}) / {weight_sum:.10f}"


def calc_macd(code: str, end_date: date | str | None = None, limit: int | None = None, fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict[str, Any]]:
    where = ["code = %s"]
    params: list[Any] = [code]
    if end_date is not None:
        where.append("trade_date <= %s")
        params.append(_to_date(end_date))
    where_sql = " AND ".join(where)
    if limit is not None:
        limit_sql = f" ORDER BY trade_date DESC LIMIT {int(limit)}"
        order_sql = " ORDER BY trade_date ASC"
    else:
        limit_sql = ""
        order_sql = " ORDER BY trade_date ASC"
    sql = f"""
        WITH base AS (
          SELECT trade_date, close,
                 {_ema_expr("close", fast)} AS ema_fast,
                 {_ema_expr("close", slow)} AS ema_slow
            FROM daily_qfq
           WHERE {where_sql}
           WINDOW w_ AS (PARTITION BY code ORDER BY trade_date ROWS BETWEEN {slow - 1} PRECEDING AND CURRENT ROW)
        ), macd_line AS (
          SELECT trade_date, close, ema_fast, ema_slow, (ema_fast - ema_slow) AS macd FROM base
        ), signal_line AS (
          SELECT trade_date, close, ema_fast, ema_slow, macd,
                 {_ema_expr("macd", signal)} AS signal
            FROM macd_line
           WINDOW w_ AS (ORDER BY trade_date ROWS BETWEEN {signal - 1} PRECEDING AND CURRENT ROW)
        )
        SELECT trade_date, close, ema_fast, ema_slow, macd, signal, (macd - signal) * 2 AS hist
          FROM signal_line
          {limit_sql}
    """
    if limit is not None:
        sql = f"SELECT * FROM ({sql}){order_sql}"
    rows = query_rows(sql, tuple(params))
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({"trade_date": r[0].isoformat(), "close": float(r[1]), "ema_fast": float(r[2]) if r[2] is not None else None, "ema_slow": float(r[3]) if r[3] is not None else None, "macd": float(r[4]) if r[4] is not None else None, "signal": float(r[5]) if r[5] is not None else None, "hist": float(r[6]) if r[6] is not None else None})
    return out


def calc_kdj(code: str, n: int = 9, m1: int = 3, m2: int = 3, end_date: date | str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    where = ["code = %s"]
    params: list[Any] = [code]
    if end_date is not None:
        where.append("trade_date <= %s")
        params.append(_to_date(end_date))
    where_sql = " AND ".join(where)
    if limit is not None:
        limit_sql = f" ORDER BY trade_date DESC LIMIT {int(limit)}"
        order_sql = " ORDER BY trade_date ASC"
    else:
        limit_sql = ""
        order_sql = " ORDER BY trade_date ASC"
    k_weights = [(1.0 / m1) * ((m1 - 1) / m1) ** i for i in range(m1)]
    k_weight_sum = sum(k_weights)
    d_weights = [(1.0 / m2) * ((m2 - 1) / m2) ** i for i in range(m2)]
    d_weight_sum = sum(d_weights)
    k_parts = [f"{w:.10f} * COALESCE(lag(rsv, {m1 - 1 - i}) OVER (ORDER BY trade_date ROWS BETWEEN {m1 - 1} PRECEDING AND CURRENT ROW), rsv, 50.0)" for i, w in enumerate(k_weights)]
    d_parts = [f"{w:.10f} * COALESCE(lag(k_smoothed, {m2 - 1 - i}) OVER (ORDER BY trade_date ROWS BETWEEN {m2 - 1} PRECEDING AND CURRENT ROW), k_smoothed, 50.0)" for i, w in enumerate(d_weights)]
    k_smoothed_expr = "(" + " + ".join(k_parts) + f") / {k_weight_sum:.10f}"
    d_smoothed_expr = "(" + " + ".join(d_parts) + f") / {d_weight_sum:.10f}"
    sql = f"""
        WITH base AS (
          SELECT trade_date, close,
                 MAX(close) OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW) AS hhv_c,
                 MIN(close) OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW) AS llv_c
            FROM daily_qfq
           WHERE {where_sql}
        ), rsv AS (
          SELECT trade_date, close,
                 CASE WHEN (hhv_c - llv_c) > 0 THEN (close - llv_c) / (hhv_c - llv_c) * 100.0 ELSE 50.0 END AS rsv
            FROM base
        ), k_step AS (
          SELECT trade_date, close, rsv, {k_smoothed_expr} AS k_smoothed FROM rsv WINDOW _ AS (ORDER BY trade_date ROWS BETWEEN {m1 - 1} PRECEDING AND CURRENT ROW)
        ), d_step AS (
          SELECT trade_date, close, rsv, k_smoothed, {d_smoothed_expr} AS d_smoothed FROM k_step WINDOW _ AS (ORDER BY trade_date ROWS BETWEEN {m2 - 1} PRECEDING AND CURRENT ROW)
        )
        SELECT trade_date, close, rsv, k_smoothed, d_smoothed, (3 * k_smoothed - 2 * d_smoothed) AS j
          FROM d_step
          {limit_sql}
    """
    if limit is not None:
        sql = f"SELECT * FROM ({sql}){order_sql}"
    rows = query_rows(sql, tuple(params))
    return [{"trade_date": r[0].isoformat(), "close": float(r[1]), "rsv": float(r[2]) if r[2] is not None else None, "k": float(r[3]) if r[3] is not None else None, "d": float(r[4]) if r[4] is not None else None, "j": float(r[5]) if r[5] is not None else None} for r in rows]


def calc_boll(code: str, n: int = 20, k: float = 2.0, end_date: date | str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    where = ["code = %s"]
    params: list[Any] = [code]
    if end_date is not None:
        where.append("trade_date <= %s")
        params.append(_to_date(end_date))
    where_sql = " AND ".join(where)
    if limit is not None:
        limit_sql = f" ORDER BY trade_date DESC LIMIT {int(limit)}"
        order_sql = " ORDER BY trade_date ASC"
    else:
        limit_sql = ""
        order_sql = " ORDER BY trade_date ASC"
    sql = f"""
        SELECT trade_date, close,
               AVG(close) OVER w_ AS mid,
               AVG(close) OVER w_ + {float(k)} * STDDEV_SAMP(close) OVER w_ AS upper,
               AVG(close) OVER w_ - {float(k)} * STDDEV_SAMP(close) OVER w_ AS lower
          FROM daily_qfq
         WHERE {where_sql}
         WINDOW w_ AS (PARTITION BY code ORDER BY trade_date ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW)
          {limit_sql}
    """
    if limit is not None:
        sql = f"SELECT * FROM ({sql}){order_sql}"
    rows = query_rows(sql, tuple(params))
    return [{"trade_date": r[0].isoformat(), "close": float(r[1]), "mid": float(r[2]) if r[2] is not None else None, "upper": float(r[3]) if r[3] is not None else None, "lower": float(r[4]) if r[4] is not None else None} for r in rows]


def calc_ma_codes(code: str, trade_date: date | str, windows: list[int] | tuple[int, ...] = _DEFAULT_MA_WINDOWS) -> dict[str, Any] | None:
    windows = sorted(set(int(w) for w in windows if int(w) >= 1))
    if not windows:
        return None
    td = _to_date(trade_date)
    assert td is not None
    ma_cols = _build_ma_select(windows)
    sql = f"""
        SELECT trade_date, close, {ma_cols}
          FROM daily_qfq
         WHERE code = %s AND trade_date <= %s
         QUALIFY ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) = 1
    """
    row = query_rows(sql, (code, td))
    if not row:
        return None
    row = row[0]
    actual_date = row[0]
    close = float(row[1])
    ma_vals: dict[int, float | None] = {}
    bits: list[str] = []
    for i, n in enumerate(windows):
        val = row[2 + i]
        v = float(val) if val is not None else None
        ma_vals[n] = v
        bits.append("-") if v is None else bits.append("1" if close >= v else "0")
    return {"code": code, "trade_date": actual_date.isoformat(), "close": close, "ma_codes": "".join(bits), **{f"ma{n}": v for n, v in ma_vals.items()}}


# ---------------------------------------------------------------------------
# 2. 全市场 MA 计数 + 宽度
# ---------------------------------------------------------------------------

def _eligible_meta(code: str) -> dict[str, Any] | None:
    meta = get_stock_meta(code)
    if meta is None or not meta.get("is_active", True) or meta.get("is_st"):
        return None
    return meta


def calc_ma_count(trade_date: date | str) -> dict[str, Any]:
    td = _to_date(trade_date)
    assert td is not None
    t0 = __import__("time").time()
    rows = query_rows(
        """
        SELECT code, close,
               AVG(close) OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
               AVG(close) OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
               lag(close, 1)   OVER (PARTITION BY code ORDER BY trade_date) AS close_1d_ago,
               lag(close, 5)   OVER (PARTITION BY code ORDER BY trade_date) AS close_5d_ago,
               lag(close, 59)  OVER (PARTITION BY code ORDER BY trade_date) AS close_59d_ago,
               MIN(close)      OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS min_60d,
               lag(close, 251) OVER (PARTITION BY code ORDER BY trade_date) AS close_251d_ago,
               MAX(close)      OVER (PARTITION BY code ORDER BY trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS max_252d
          FROM daily_qfq
         WHERE trade_date <= %s
         QUALIFY trade_date = %s
        """,
        (td, td),
    )
    above_ma20 = above_ma60 = above_both = 0
    up_5d = new_low_60d = new_high_252d = advancing = 0
    eligible = 0
    by_board: dict[str, dict[str, int]] = {}
    for (code, close, ma20, ma60, close_1d_ago, close_5d_ago, close_59d_ago, min_60d, close_251d_ago, max_252d) in rows:
        if ma20 is None or ma60 is None:
            continue
        meta = _eligible_meta(str(code))
        if meta is None:
            continue
        eligible += 1
        close_f = float(close)
        ma20_f = float(ma20)
        ma60_f = float(ma60)
        board = meta.get("board") or get_board_type(str(code))
        slot = by_board.setdefault(board, {"total": 0, "aboveMa20": 0, "aboveMa60": 0, "aboveBoth": 0, "up5d": 0, "newLow60d": 0, "newHigh252d": 0, "advancing": 0})
        slot["total"] += 1
        a20 = close_f > ma20_f
        a60 = close_f > ma60_f
        if a20:
            above_ma20 += 1
            slot["aboveMa20"] += 1
        if a60:
            above_ma60 += 1
            slot["aboveMa60"] += 1
        if a20 and a60:
            above_both += 1
            slot["aboveBoth"] += 1
        if close_5d_ago is not None and close_f > float(close_5d_ago):
            up_5d += 1
            slot["up5d"] += 1
        if close_59d_ago is not None and min_60d is not None and close_f <= float(min_60d):
            new_low_60d += 1
            slot["newLow60d"] += 1
        if close_251d_ago is not None and max_252d is not None and close_f >= float(max_252d):
            new_high_252d += 1
            slot["newHigh252d"] += 1
        if close_1d_ago is not None and close_f > float(close_1d_ago):
            advancing += 1
            slot["advancing"] += 1

    def pct(num: int, den: int) -> float:
        return round(num / den * 100, 2) if den > 0 else 0.0

    by_board_out = {
        board: {
            "total": slot["total"],
            "aboveMa20": slot["aboveMa20"],
            "aboveMa60": slot["aboveMa60"],
            "aboveBoth": slot["aboveBoth"],
            "pctMa20": pct(slot["aboveMa20"], slot["total"]),
            "pctMa60": pct(slot["aboveMa60"], slot["total"]),
            "pctBoth": pct(slot["aboveBoth"], slot["total"]),
            "up5d": slot["up5d"],
            "pctUp5d": pct(slot["up5d"], slot["total"]),
            "newLow60d": slot["newLow60d"],
            "pctNewLow60d": pct(slot["newLow60d"], slot["total"]),
            "newHigh252d": slot["newHigh252d"],
            "pctNewHigh252d": pct(slot["newHigh252d"], slot["total"]),
            "advancing": slot["advancing"],
            "pctAdvancing": pct(slot["advancing"], slot["total"]),
        }
        for board, slot in by_board.items()
    }

    elapsed_ms = int((__import__("time").time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "totalEligible": eligible,
        "aboveMa20": above_ma20,
        "aboveMa60": above_ma60,
        "aboveBoth": above_both,
        "pctAboveMa20": pct(above_ma20, eligible),
        "pctAboveMa60": pct(above_ma60, eligible),
        "pctAboveBoth": pct(above_both, eligible),
        "up5dCount": up_5d,
        "pctUp5d": pct(up_5d, eligible),
        "newLow60dCount": new_low_60d,
        "pctNewLow60d": pct(new_low_60d, eligible),
        "newHigh252dCount": new_high_252d,
        "pctNewHigh252d": pct(new_high_252d, eligible),
        "advancingCount": advancing,
        "pctAdvancing": pct(advancing, eligible),
        "byBoard": by_board_out,
        "elapsedMs": elapsed_ms,
        "source": "clickhouse.daily_qfq",
    }


def save_ma_count(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate") or payload.get("trade_date"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_ma_count skipped non-trading day: %s", td)
        return
    breadth_raw = round(0.40 * float(payload.get("pctAdvancing") or 0) + 0.35 * float(payload.get("pctAboveMa20") or 0) + 0.25 * float(payload.get("pctAboveMa60") or 0), 2)
    with session_scope() as db:
        execute_upsert(db, table="msi_ma_count_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "total_eligible": int(payload.get("totalEligible") or 0),
            "above_ma20": int(payload.get("aboveMa20") or 0),
            "above_ma60": int(payload.get("aboveMa60") or 0),
            "above_both": int(payload.get("aboveBoth") or 0),
            "pct_ma20": float(payload.get("pctAboveMa20") or 0),
            "pct_ma60": float(payload.get("pctAboveMa60") or 0),
            "pct_both": float(payload.get("pctAboveBoth") or 0),
            "up_5d_count": int(payload.get("up5dCount") or 0),
            "up_5d_pct": float(payload.get("pctUp5d") or 0),
            "new_low_60d_count": int(payload.get("newLow60dCount") or 0),
            "new_low_60d_pct": float(payload.get("pctNewLow60d") or 0),
            "new_high_252d_count": int(payload.get("newHigh252dCount") or 0),
            "new_high_252d_pct": float(payload.get("pctNewHigh252d") or 0),
            "advancing_count": int(payload.get("advancingCount") or 0),
            "advancing_pct": float(payload.get("pctAdvancing") or 0),
            "breadth_raw": breadth_raw,
            "by_board": payload.get("byBoard") or {},
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "clickhouse.daily_qfq"),
            "ingested_at": datetime.now(),
        })


_MA_COUNT_COLS = (
    "trade_date", "total_eligible", "above_ma20", "above_ma60", "above_both",
    "pct_ma20", "pct_ma60", "pct_both",
    "up_5d_count", "up_5d_pct", "new_low_60d_count", "new_low_60d_pct",
    "new_high_252d_count", "new_high_252d_pct",
    "advancing_count", "advancing_pct",
    "breadth_raw",
    "by_board", "elapsed_ms", "source",
)
_MA_COUNT_SELECT = ", ".join(_MA_COUNT_COLS)


def _row_to_ma_payload(row: tuple) -> dict:
    breadth_raw = float(row[16]) if row[16] is not None else None
    by_board = row[17] if isinstance(row[17], dict) else (row[17] or {})
    return {
        "tradeDate": row[0].isoformat(),
        "totalEligible": int(row[1]),
        "aboveMa20": int(row[2]),
        "aboveMa60": int(row[3]),
        "aboveBoth": int(row[4]),
        "pctAboveMa20": float(row[5]),
        "pctAboveMa60": float(row[6]),
        "pctAboveBoth": float(row[7]),
        "up5dCount": int(row[8]) if row[8] is not None else 0,
        "pctUp5d": float(row[9]) if row[9] is not None else 0.0,
        "newLow60dCount": int(row[10]) if row[10] is not None else 0,
        "pctNewLow60d": float(row[11]) if row[11] is not None else 0.0,
        "newHigh252dCount": int(row[12]) if row[12] is not None else 0,
        "pctNewHigh252d": float(row[13]) if row[13] is not None else 0.0,
        "advancingCount": int(row[14]) if row[14] is not None else 0,
        "pctAdvancing": float(row[15]) if row[15] is not None else 0.0,
        "breadthRaw": breadth_raw,
        "byBoard": by_board,
        "elapsedMs": int(row[18]) if row[18] is not None else None,
        "source": str(row[19]),
        "fromCache": True,
    }


def get_ma_count(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_MA_COUNT_SELECT} FROM cynexus_appl_market.msi_ma_count_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_ma_payload(row) if row else None


def get_ma_count_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_MA_COUNT_SELECT} FROM cynexus_appl_market.msi_ma_count_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    items = [_row_to_ma_payload(r) for r in rows]
    enrich_history_scores(items, "ma_count_daily", "new_high_252d_pct", e, score_key="newHigh252dScore")
    enrich_history_scores(items, "ma_count_daily", "breadth_raw", e, score_key="breadthScore")
    return items


def _add_new_high_score(payload: dict, trade_date: date | str) -> None:
    pct = payload.get("pctNewHigh252d")
    if pct is not None:
        payload["newHigh252dScore"] = percentile_score("ma_count_daily", "new_high_252d_pct", trade_date, pct)
        payload["newHigh252dRawValue"] = pct


def _add_breadth_score(payload: dict, trade_date: date | str) -> None:
    raw = payload.get("breadthRaw")
    if raw is not None:
        payload["breadthScore"] = percentile_score("ma_count_daily", "breadth_raw", trade_date, raw)
        payload["breadthRawValue"] = raw


def calc_ma_count_cached(trade_date: date | str, *, force: bool = False) -> dict:
    if not force:
        cached = get_ma_count(trade_date)
        if cached is not None:
            _add_new_high_score(cached, trade_date)
            _add_breadth_score(cached, trade_date)
            return cached
    payload = calc_ma_count(trade_date)
    try:
        save_ma_count(payload)
    except Exception:
        pass
    _add_new_high_score(payload, trade_date)
    _add_breadth_score(payload, trade_date)
    return payload


def bulk_calc_ma_count(start: date, end: date) -> dict[date, dict[str, Any]]:
    s = _to_date(start)
    e = _to_date(end)
    assert s is not None and e is not None
    if s > e:
        return {}
    out: dict[date, dict[str, Any]] = {}
    cur = s
    while cur <= e:
        payload = calc_ma_count(cur)
        out[cur] = payload
        cur = cur.fromordinal(cur.toordinal() + 1)
    return out


def bulk_save_ma_count(payloads: dict[date, dict[str, Any]]) -> int:
    if not payloads:
        return 0
    n = 0
    for td, payload in payloads.items():
        if not is_trading_day(td):
            logger.debug("bulk_save_ma_count skipped non-trading day: %s", td)
            continue
        save_ma_count(payload)
        n += 1
    return n


if __name__ == "__main__":
    import json as _json
    print("=== MA5/10/20 for 000001 last 5 ===")
    print(_json.dumps(calc_ma("000001", windows=[5, 10, 20], limit=5), indent=2, ensure_ascii=False))
    print("\n=== ma_codes for 000001 on 2026-06-15 ===")
    print(_json.dumps(calc_ma_codes("000001", "2026-06-15"), indent=2, ensure_ascii=False))
