# Market Overview JSON → PostgreSQL Migration

## Required Entry

Before reading, modifying, or refactoring any code related to 大盘成交额 (total market turnover) and 主力净流入 (main net fund flow), read this document first, then go to the code.

Related files:

- `F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md` (this file)
- `F:\dev-repo\mp4-to-word-new\backend\models\market_overview.py`
- `F:\dev-repo\mp4-to-word-new\backend\repositories\market\market_overview_pg_repo.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_overview_akshare_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_overview_eltdx_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_overview_manual_fund_flow_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock_chart.py`
- `F:\dev-repo\mp4-to-word-new\backend\scripts\backfill_market_overview_postgres.py`
- `F:\dev-repo\mp4-to-word-new\backend\config\settings.py`
- `F:\dev-repo\mp4-to-word-new\backend\models\market_pulse.py` (existing model pattern reference)
- `F:\dev-repo\mp4-to-word-new\backend\repositories\market\market_pulse_pg_repo.py` (existing repo pattern reference)

Requirements:

1. Read this document first, then modify code.
2. After modifying code, sync updates back to this document.
3. All new code must reference this document in module docstring.

---

## Scope

This migration covers:

1. **大盘成交额** (total market turnover) — `totalAmount` in JSON archives
2. **涨跌家数** (up/down counts) — `risingCount`, `fallingCount`, `flatCount`, etc.
3. **主力净流入** (main net fund flow) — `mainNetInflow` and 4 sub-order types (super-large/large/medium/small)
4. **涨停跌停** (limit up/down counts) — `limitUpCount`, `limitDownCount`

Target: Migrate from JSON file storage under `reference/market-overview/` to PostgreSQL `app.market_overview_snapshots` table.

---

## Business Rules

### 1. One Row Per Trading Day

- Each trading day has exactly one logical row in `app.market_overview_snapshots`.
- Fields come from multiple sources (akshare, eltdx, manual), merged via COALESCE-style upsert.
- `trade_date` is the unique business key.

### 2. Multi-Source Merge Strategy

Different sources write different fields to the same row:

| Source | Fields |
|--------|--------|
| **akshare** `capture_snapshot()` | `main_net_inflow`, `super_large_net_inflow`, ... (fund flow) |
| **eltdx** `capture_overview()` | `total_amount`, `rising_count`, `falling_count`, ... (market overview) |
| **manual** `save_manual_fund_flow()` | Fund flow fields (overrides akshare fund flow) |

Merge rule: Fields already set by a higher-priority source are NOT overwritten by a lower-priority source.

Priority: manual > latest live capture > archive

### 3. Read Path

1. Try PostgreSQL first (primary source).
2. Fall back to JSON archive (legacy compat, in case PG is empty for a date).
3. For "today" (current trading day): try PG first, if no data, try JSON `latest.json`, if still no data, try last available archive.

### 4. Write Paths

Three independent write paths, all writing to both PG and JSON (dual-write during migration):

1. **akshare fund-flow** (`capture_snapshot()` in `market_overview_akshare_service.py`):
   - Writes fund flow fields to PG via `upsert_overview()`
   - Keeps existing JSON write for backward compat

2. **eltdx overview** (`capture_overview()` in `market_overview_eltdx_service.py`):
   - Writes market overview fields to PG via `upsert_overview()`
   - Keeps existing JSON write for backward compat

3. **manual fund-flow** (`save_manual_fund_flow()` in `market_overview_manual_fund_flow_service.py`):
   - Writes manual fund flow fields to PG via `upsert_overview()`
   - Sets `is_manual_override = true`
   - Keeps existing JSON write for backward compat

### 5. Source Tracking

The `source` field records which source contributed data:
- `"akshare"` — akshare fund flow
- `"eltdx"` — eltdx overview  
- `"manual"` — manual fund flow (user pasted)
- `"akshare+eltdx"` — both akshare and eltdx
- `"manual+akshare+eltdx"` — all three

When any source writes, it updates `source` to append its tag if not already present.

### 6. History Query

- Returns rows ordered by `trade_date ASC`
- Supports `limit` and `offset` for pagination
- Default range: last 60 trading days / user-specified `days`

---

## Schema

### `app.market_overview_snapshots`

Purpose: One row per trading day, storing market-wide snapshot data (turnover, up/down counts, fund flow).

Fields:

```
id                              uuid PK
trade_date                      date NOT NULL

-- 大盘成交额 (total market turnover)
total_amount                    numeric(18,4)   -- 全A成交额 (亿)
total_volume                    numeric(18,4)   -- 全A成交量

-- 涨跌家数 (up/down counts)
rising_count                    integer         -- 上涨家数
falling_count                   integer         -- 下跌家数
flat_count                      integer         -- 平盘家数
limit_up_count                  integer         -- 涨停家数
limit_down_count                integer         -- 跌停家数
stock_count                     integer         -- 股票总数

-- 资金流 (fund flow) — 单位: 亿
main_net_inflow                 numeric(18,4)   -- 主力净流入
super_large_net_inflow          numeric(18,4)   -- 超大单净流入
large_net_inflow                numeric(18,4)   -- 大单净流入
medium_net_inflow               numeric(18,4)   -- 中单净流入
small_net_inflow                numeric(18,4)   -- 小单净流入

-- 资金流净比 (fund flow ratio) — 单位: %
main_net_inflow_ratio           numeric(6,2)    -- 主力净占比
super_large_net_ratio           numeric(6,2)    -- 超大单净占比
large_net_ratio                 numeric(6,2)    -- 大单净占比
medium_net_ratio                numeric(6,2)    -- 中单净占比
small_net_ratio                 numeric(6,2)    -- 小单净占比

-- 元数据 (metadata)
source                          varchar(32)     -- 数据来源标识
is_manual_override              boolean NOT NULL DEFAULT false
manual_updated_at               timestamptz     -- 手动覆盖时间

extra                           jsonb           -- 扩展字段
remark                          text

created_at                      timestamptz NOT NULL DEFAULT now()
updated_at                      timestamptz NOT NULL DEFAULT now()
deleted_at                      timestamptz     -- 软删除
```

Indexes:

- `uk_market_overview_snapshots_trade_date` — unique alive index on `trade_date`
- `idx_market_overview_snapshots_trade_date` — alive index on `trade_date DESC` for history queries

Constraints:

- No CHECK constraint on `source` (values vary across source combinations)

---

## File Structure

### `backend\models\market_overview.py`

ORM model: `MarketOverviewSnapshot`

- Maps to `app.market_overview_snapshots`
- Follows same pattern as `backend/models/market_pulse.py`
- Imports from `backend.db.base`
- Uses SQLAlchemy 2.0 mapped_column style

### `backend\repositories\market\market_overview_pg_repo.py`

Repository: `MarketOverviewPgRepository`

Methods:

- `upsert(trade_date, fields)` — COALESCE-style upsert (INSERT ON CONFLICT DO UPDATE)
- `get(trade_date)` — single day query
- `get_latest(trade_date)` — latest available row on or before `trade_date`
- `get_history(days, end_date)` — time-series history
- `coverage()` — first/last/row count stats
- `backfill_from_json(days)` — import legacy JSON archives into PG

### `backend\services\stock\market_overview_akshare_service.py`

Modifications:

- `capture_snapshot()` → after saving JSON, also upsert to PG via `MarketOverviewPgRepository`
- `get_latest_snapshot()` → try PG first, fallback to JSON
- `get_history_points()` → try PG first, fallback to JSON

### `backend\services\stock\market_overview_eltdx_service.py`

Modifications:

- `save_overview()` → after saving JSON, also upsert to PG via `MarketOverviewPgRepository`
- `get_latest_overview()` → try PG first, fallback to JSON

### `backend\services\stock\market_overview_manual_fund_flow_service.py`

Modifications:

- `save_manual_fund_flow()` → after saving JSON, also upsert to PG with `is_manual_override = true`
- `load_manual_fund_flow()` → try PG first, fallback to JSON

### `backend\api\stock_chart.py`

Modifications:

- All endpoints remain path-compatible
- Data source shifts from JSON to PG (transparent to frontend)

### `backend\scripts\backfill_market_overview_postgres.py`

Script to import all existing JSON archive data into PostgreSQL.

Logic:

1. Scan `reference/market-overview/archive/*.json` (akshare + merged data)
2. Scan `reference/market-overview/market-overview/archive/*.json` (eltdx data)
3. Merge both into PG via `MarketOverviewPgRepository.upsert()`
4. Mark source appropriately

---

## API Contract Notes

Endpoints (unchanged paths, data source changed to PG):

| Endpoint | Method | Purpose | Data Source Change |
|---|---|---|---|
| `/api/stock-chart/market-overview-akshare` | GET | Today's latest snapshot | PG → JSON fallback |
| `/api/stock-chart/market-overview-akshare/history` | GET | History points | PG → JSON fallback |
| `/api/stock-chart/market-overview-eltdx` | GET | Today's eltdx overview | PG → JSON fallback |
| `/api/stock-chart/market-overview-manual-fund-flow` | GET/POST | Manual fund flow CRUD | PG → JSON fallback |

The `history` endpoint now returns `total_amount` instead of `totalAmount` for PG-sourced data.
Frontend should handle both camelCase (JSON legacy) and snake_case (PG) field names.

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
python -m backend.scripts.backfill_market_overview_postgres
```

This imports:
- `reference/market-overview/archive/*.json` — akshare + merged manual data
- `reference/market-overview/market-overview/archive/*.json` — eltdx data

### 3. Verify

Check:
- PG `app.market_overview_snapshots` has correct row count
- Frontend market pulse page shows data from PG
- Manual fund flow save → reads from PG correctly
- Non-trading day fallback still works

---

## Current Decisions

- Dual-write during transition: both JSON and PG receive writes.
- Read path: PG first, JSON fallback.
- No physical foreign keys (follows project convention).
- No GIN index on `extra` (rarely queried).
- `source` field uses simple VARCHAR without CHECK (values are dynamic).

---

## Change Log

### 2026-06-23

- Design document created.
- Schema defined: `app.market_overview_snapshots`.
- Migration, model, repository, service, API, backfill scope defined.

### 2026-06-23 (Implementation)

- **Migration**: `alembic/versions/g8h9j0k1l2m3_create_market_overview_snapshots.py` executed.
- **ORM**: `backend/models/market_overview.py` — `MarketOverviewSnapshot` model.
- **Repository**: `backend/repositories/market/market_overview_pg_repo.py` — `MarketOverviewPgRepository` with upsert (COALESCE merge), get, get_latest, get_history, coverage.
- **PG Writer Helper**: `backend/services/stock/_pg_writer.py` — `upsert_overview_to_pg()` shared across 3 services.
- **Write paths updated**:
  - `market_overview_akshare_service.py` → capture_snapshot() writes PG
  - `market_overview_eltdx_service.py` → save_overview() writes PG
  - `market_overview_manual_fund_flow_service.py` → save_manual_fund_flow() writes PG
- **Read path updated**: `stock_chart.py` history endpoint reads PG first, falls back to JSON.
- **Backfill**: `backend/scripts/backfill_market_overview_postgres.py` executed — 126 rows imported (2025-12-11 ~ 2026-06-22).
- **Frontend**: No changes needed (API returns camelCase).
