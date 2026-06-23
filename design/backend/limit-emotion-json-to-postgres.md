# Limit Emotion JSON → PostgreSQL Migration

## Required Entry

Before reading, modifying, or refactoring any code related to 涨跌停情绪 (limit up/down sentiment), read this document first, then go to the code.

Related files:

- `F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md` (this file)
- `F:\dev-repo\mp4-to-word-new\backend\models\market_limit.py`
- `F:\dev-repo\mp4-to-word-new\backend\repositories\market\market_limit_pg_repo.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\limit_emotion_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock_chart.py`
- `F:\dev-repo\mp4-to-word-new\backend\scripts\backfill_market_limit_postgres.py`
- `F:\dev-repo\mp4-to-word-new\backend\config\settings.py`
- `F:\dev-repo\mp4-to-word-new\backend\models\market_overview.py` (existing model pattern reference)
- `F:\dev-repo\mp4-to-word-new\backend\repositories\market\market_overview_pg_repo.py` (existing repo pattern reference)
- `F:\dev-repo\mp4-to-word-new\backend\design\backend\market-overview-json-to-postgres.md` (parallel migration reference)

Requirements:

1. Read this document first, then modify code.
2. After modifying code, sync updates back to this document.
3. All new code must reference this document in module docstring.

---

## Scope

This migration covers:

1. **涨跌停情绪** (limit up/down sentiment) — computed by `limit_emotion_service.build_limit_emotion()`
2. **涨停/跌停/触板/炸板** stock lists per trading day
3. **连板体系** (streak system): max height, distribution, promotion rates, broken feedback
4. **连板情绪判断** (streak sentiment): ice/weak/normal/active/hot

Target: Persist computed limit emotion snapshots from JSON file storage under `reference/market-pulse/` to PostgreSQL `app.market_limit_daily_snapshots` table.

### What is NOT migrated

Individual stock-level data (5279 stocks per day in `reference/market-limit/daily/*.json`) remains in JSON files. Only the **computed/aggregated results** are stored in PG, plus the full computed payload in `extra` jsonb for reconstruction.

---

## Business Rules

### 1. One Row Per Trading Day

- Each trading day has one logical row in `app.market_limit_daily_snapshots`.
- The row stores the **final computed payload** after the market closes for that day.
- `trade_date` is the unique business key.

### 2. Write Path

The `build_limit_emotion()` function in `limit_emotion_service.py` already writes:
- `reference/market-pulse/latest.json` (current day's computed result)
- `reference/market-pulse/snapshots/<date>/<time>.json` (snapshots during trading hours)
- `reference/market-limit/daily/<date>.json` (raw daily stock data)

After PG migration, it also writes to PG via `upsert_limit_snapshot()`:
- After computing the full payload (trading day or non-trading day)
- The full payload is stored in the `extra` jsonb field
- Summary fields (counts, rates, sentiment) are stored as columns for fast querying

### 3. Read Path

1. **Latest snapshot** (market-pulse/limit-emotion): Keep existing logic — compute from live data or read JSON cache. PG is not primary for "today" data since it's computed dynamically.
2. **History queries** (sparklines, trends): Read PG first, fallback to JSON snapshots archive.
3. **Non-trading day fallback**: PG latest row on or before the requested date.

### 4. Source Tracking

The `source` field indicates where the data was computed from:
- `"realtime"` — computed from live eltdx quotes
- `"daily_archive"` — aggregated from `market-limit/daily/<date>.json`
- `"duckdb"` — computed from DuckDB daily_raw
- `"empty"` — no data available

### 5. History Query

- Returns rows ordered by `trade_date ASC`
- Supports pagination via `limit` and `offset`
- Default range: last 60 trading days

---

## Schema

### `app.market_limit_daily_snapshots`

Purpose: One row per trading day, storing the aggregated limit emotion results (counts, rates, streak distribution, sentiment).

Fields:

```
id                              uuid PK
trade_date                      date NOT NULL

-- 涨跌停 (limit up/down)
limit_up_count                  integer         -- 涨停家数
limit_down_count                integer         -- 跌停家数

-- 触板/炸板 (touch board / break board)
touched_count                   integer         -- 触板家数
broken_count                    integer         -- 炸板家数
break_board_rate                numeric(6,4)    -- 炸板率

-- 连板 (streak)
max_streak_height               integer         -- 最高连板
promotion_overall_rate          numeric(6,4)    -- 整体晋级率

-- 连板情绪 (streak sentiment)
sentiment_level                 varchar(32)     -- ice/weak/normal/active/hot
sentiment_text                  text            -- 情绪文案

-- 元数据 (metadata)
stock_count                     integer         -- 有效股票总数
market_status                   varchar(32)     -- trading/closed/pre_open
data_status                     varchar(32)     -- normal/empty/partial/stale
source                          varchar(64)     -- 数据来源

-- 扩展字段
extra                           jsonb           -- 完整 computed payload (full reconstruction)

-- 标准时间戳
created_at                      timestamptz NOT NULL DEFAULT now()
updated_at                      timestamptz NOT NULL DEFAULT now()
deleted_at                      timestamptz     -- 软删除
```

Indexes:

- `uk_market_limit_daily_trade_date` — unique alive index on `trade_date`
- `idx_market_limit_daily_trade_date` — alive index on `trade_date DESC` for history queries

### `app.market_limit_daily_stocks`

Purpose: One row per stock per trading day, recording limit up/down/broken stocks and their streak (板数).

```
id                              uuid PK
trade_date                      date NOT NULL

-- 股票信息
code                            varchar(16) NOT NULL
name                            varchar(64)

-- 分类: limit_up / limit_down / broken
category                        varchar(16) NOT NULL

-- 板数 (limit_up: 当前连板数; broken: 前一日连板数; limit_down: 0)
streak                          integer

-- 价格/涨跌幅
change_pct                      numeric(8,4)
limit_up_price                  numeric(12,4)
limit_down_price                numeric(12,4)

-- 标准时间戳
created_at                      timestamptz NOT NULL DEFAULT now()
updated_at                      timestamptz NOT NULL DEFAULT now()
deleted_at                      timestamptz
```

Indexes:

- `uk_market_limit_daily_stocks_trade_date_code` — unique alive index on `(trade_date, code)`
- `idx_market_limit_daily_stocks_trade_date_category` — alive index on `(trade_date DESC, category)`

---

## File Structure

### `backend\models\market_limit.py`

ORM model: `MarketLimitDailySnapshot`

- Maps to `app.market_limit_daily_snapshots`
- Follows same pattern as `backend/models/market_overview.py`
- Imports from `backend.db.base`
- Uses SQLAlchemy 2.0 mapped_column style

### `backend\repositories\market\market_limit_pg_repo.py`

Repository: `MarketLimitPgRepository`

Summary methods:

- `upsert(trade_date, fields, source_tag)` — INSERT ON CONFLICT DO UPDATE (COALESCE merge)
- `get(trade_date)` — single day query
- `get_latest(trade_date)` — latest available row on or before `trade_date`
- `get_history(days, end_date)` — time-series history
- `coverage()` — first/last/row count stats
- `has_trade_date(trade_date)` — existence check

Stock-level methods:

- `upsert_stocks(trade_date, stocks)` — batch write stocks for a trading day (soft-deletes old, inserts new)
- `get_stocks(trade_date, category)` — query stocks by date, optionally filtered by category (limit_up / limit_down / broken)

### `backend\services\stock\limit_emotion_service.py`

Modifications:

- After computing payload in `build_limit_emotion()`, upsert to PG via `MarketLimitPgRepository`
- Extract summary fields from the computed payload for column storage
- Store full payload in `extra` jsonb

### `backend\services\stock\_limit_pg_writer.py`

Shared PG write helper (parallel to `_pg_writer.py` for market overview):

- `upsert_limit_snapshot_to_pg(payload, source_tag)` — extract fields from payload and upsert to PG

### `backend\api\stock_chart.py`

Modifications:

- `market_pulse_limit_emotion()` — no change (always computes fresh for current day)
- Add `/api/stock-chart/market-pulse/limit-emotion/history` endpoint — reads PG first, falls back to JSON snapshots

Parsing of PG rows to frontend-compatible payload:

```
PG snake_case → frontend expects snake_case fields from history endpoint
The full payload reconstruction comes from extra jsonb
```

### `backend\scripts\backfill_market_limit_postgres.py`

Script to backfill existing `reference/market-pulse/snapshots/<date>/<time>.json` data into PostgreSQL.

Logic:

1. Scan `reference/market-pulse/snapshots/*/*.json` — sorted by date, for each date take the latest snapshot
2. Scan `reference/market-limit/daily/*.json` for additional stock counts
3. Upsert each day to PG via `MarketLimitPgRepository.upsert()`

---

## API Contract Notes

### New Endpoint

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/stock-chart/market-pulse/limit-emotion/history` | GET | History of limit emotion snapshots |

Query params: `?days=60&end=YYYY-MM-DD`

Returns:
```json
{
  "ok": true,
  "days": 60,
  "count": 60,
  "source": "postgres",
  "items": [
    {
      "trade_date": "2026-06-22",
      "limit_up_count": 219,
      "limit_down_count": 32,
      "touched_count": 425,
      "broken_count": 206,
      "break_board_rate": 0.4847,
      "max_streak_height": 5,
      "promotion_overall_rate": 0.35,
      "sentiment_level": "active",
      "stock_count": 5279,
      "market_status": "closed",
      "data_status": "normal",
      "source": "realtime"
    }
  ]
}
```

### Existing Endpoints (unchanged)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/stock-chart/market-pulse/limit-emotion` | GET | Current limit emotion (computed fresh/cached) |
| `/api/stock-chart/market-pulse/limit-emotion/refresh` | POST | Force recompute |
| `/api/stock-chart/market-pulse/limit-emotion/daily-snapshot` | POST | Close-of-day snapshot |
| `/api/stock-chart/market-pulse/limit-emotion/config` | GET/PUT | Configuration |

---

## Migration / Backfill Steps

### 1. Create Table

Run:
```powershell
alembic upgrade head
```

### 2. Backfill Historical Data

Run:
```powershell
python -m backend.scripts.backfill_market_limit_postgres
```

This imports:
- `reference/market-pulse/snapshots/<date>/*.json` — computed snapshots
- `reference/market-limit/daily/<date>.json` — daily stock data for stock_count

### 3. Verify

Check:
- PG `app.market_limit_daily_snapshots` has correct row count
- Frontend limit emotion panel shows data from PG history
- Non-trading day fallback still works

---

## Current Decisions

- Dual-write during transition: both JSON and PG receive writes.
- Read path: PG first for history, JSON fallback.
- No physical foreign keys (follows project convention).
- `extra` jsonb stores the full computed payload for complete reconstruction.
- Stock-level individual data remains in JSON files (not migrated to PG).
- `source` field uses simple VARCHAR without CHECK (values are dynamic).

---

## Change Log

### 2026-06-23

- Design document created.
- Schema defined: `app.market_limit_daily_snapshots`.
- Migration, model, repository, writer, backfill scope defined.

### 2026-06-23 (Implementation)

- **Migration**: `alembic/versions/l4m5n6o7p8q9_create_market_limit_daily_snapshots.py` executed.
- **ORM**: `backend/models/market_limit.py` — `MarketLimitDailySnapshot` model.
- **Repository**: `backend/repositories/market/market_limit_pg_repo.py` — `MarketLimitPgRepository` with upsert (COALESCE merge), get, get_latest, get_history, coverage.
- **PG Writer Helper**: `backend/services/stock/_limit_pg_writer.py` — `upsert_limit_snapshot_to_pg()` shared across all code paths.
- **Service layer updated**: `limit_emotion_service.py` — `build_limit_emotion()` now writes PG after computing (7 branches: pre_open daily/duckdb, non-trading duckdb/daily/empty, closed daily, realtime).
- **API added**: `GET /api/stock-chart/market-pulse/limit-emotion/history` — reads PG first, falls back to JSON snapshots.
- **Stock-level table**: `alembic/versions/q0r1s2t3u4v5_create_market_limit_daily_stocks.py` executed. `MarketLimitDailyStock` model + `upsert_stocks()` / `get_stocks()` repo methods. `_limit_pg_writer.py` extracts stocks from payload and writes to PG.
- **Backfill**: `backend/scripts/backfill_market_limit_postgres.py` executed — 5 rows summary + stock records imported (2026-06-15 ~ 2026-06-22).
- **Frontend**: No changes needed. Existing endpoints return same shape. History endpoint is new for future use.
