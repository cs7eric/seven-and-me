# Market Pulse Postgres Migration

## Required Entry

后续任何人如果要看、改、重构以下功能，请先看本文，再去代码：

- `F:\dev-repo\mp4-to-word-new\backend\models\market_pulse.py`
- `F:\dev-repo\mp4-to-word-new\backend\repositories\market\market_pulse_pg_repo.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_pulse_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\scheduler\market_pulse_scheduler.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock_chart.py`
- `F:\dev-repo\mp4-to-word-new\backend\scripts\backfill_market_pulse_postgres.py`
- `F:\dev-repo\mp4-to-word-new\backend\utils\trading_day.py`

要求：

- 先更新本文档，再改代码。
- 改完代码后，必须同步把本文档回写到最新状态。

## Scope

本次迁移覆盖 `Stock Overview -> market` 下的三块：

- 强势板块
- 主力净流入
- 行业轮动

目标是把原来混杂的 JSON / DuckDB / 运行时抓取，统一到 Postgres 日快照。

## Business Rules

### 1. 交易日规则

- 数据按 `trade_date` 归档。
- 非交易日不写库。
- 非交易日访问时，直接回退读取上一个已确认交易日。
- 交易日是否确认，统一走 `backend.utils.trading_day.is_trade_date_confirmed_by_tencent`。
- 是否允许抓取“今天”的网页快照，统一走 `backend.utils.trading_day.can_request_live_fund_flow_snapshot`。
- 读取时应该读哪一天，统一走 `backend.utils.trading_day.resolve_fund_flow_read_trade_date`。

### 2. 抓取写入规则

- 盘中允许抓取时，服务会优先尝试抓今天的 akshare 行业资金流，并覆盖今天快照。
- 如果今天不能抓，或者今天不是交易日，则直接读取最近一个已确认交易日的快照。
- 非交易日绝不新增 `trade_date=非交易日` 的记录。

### 3. 历史回填规则

优先级：

1. 先从 DuckDB `market_pulse_sector_daily` 导入
2. 再用 `reference/stock-universe/market_pulse/rotation/*.json` 补缺

导入时统一先过交易日确认，非交易日直接跳过。

## Schema

### `app.market_pulse_capture_batches`

用途：

- 一天一批，记录某个交易日的抓取批次元数据

字段：

- `id uuid pk`
- `trade_date date not null`
- `source_kind varchar(32)`:
  - `live_capture`
  - `duckdb_import`
  - `json_import`
- `status varchar(32)`:
  - `success`
  - `partial`
  - `failed`
- `source_name varchar(128)`
- `row_count integer`
- `fetched_at timestamptz`
- `extra jsonb`
- `remark text`
- `created_at / updated_at / deleted_at`

索引：

- 存活唯一索引：`trade_date`
- `fetched_at desc`

### `app.market_pulse_sector_daily_snapshots`

用途：

- 一天一行一个行业，保存 90 行业日快照

字段：

- `id uuid pk`
- `batch_id uuid`
- `trade_date date not null`
- `sector_name varchar(128) not null`
- `sector_index varchar(64)`
- `rank_by_change integer`
- `change_pct numeric(10,4)`
- `inflow numeric(24,6)`
- `outflow numeric(24,6)`
- `main_net numeric(24,6)`
- `stock_count integer`
- `leading_stock varchar(128)`
- `leading_change_pct numeric(10,4)`
- `leading_price numeric(24,6)`
- `source_kind varchar(32)`
- `source_name varchar(128)`
- `captured_at timestamptz`
- `extra jsonb`
- `remark text`
- `created_at / updated_at / deleted_at`

索引：

- 存活唯一索引：`(trade_date, sector_name)`
- `(trade_date, rank_by_change)`
- `(trade_date, main_net desc)`
- `(sector_name, trade_date desc)`
- `(batch_id)`

## Runtime Architecture

### Read path

1. API 调 `market_pulse_service`
2. service 用 `resolve_fund_flow_read_trade_date()` 先算应该读取哪一天
3. 如果允许抓今天，先尝试 live capture today
4. 最终从 `MarketPulseRepository` 读取 Postgres 快照
5. 强势板块 / 主力净流入 / 行业轮动 都基于同一份日快照派生

### Write path

1. 盘中或手动 refresh 触发 live capture
2. service 抓 `ak.stock_fund_flow_industry()`
3. repository `replace_trade_day_snapshot()` 软删旧批次和旧快照
4. 插入新 batch 和新 snapshot rows

### Scheduler path

- `market_pulse_scheduler` 继续负责盘内刷新和收盘后归档
- 但不再把 rotation JSON 当成运行时真相源
- 真相源是 Postgres

## File Responsibilities

### `backend\models\market_pulse.py`

- 定义 Market Pulse 新表 ORM

### `backend\repositories\market\market_pulse_pg_repo.py`

- 历史导入
- 日快照替换写入
- 单日读取
- 交易日列表
- 覆盖度统计
- 非交易日数据清理

### `backend\services\stock\market_pulse_service.py`

- 交易日读写规则编排
- live capture 触发
- 三个业务视图聚合：
  - strong
  - capital-flow
  - rotation
- rotation trend 派生

### `backend\scripts\backfill_market_pulse_postgres.py`

- migration 后执行一次
- 把 DuckDB / JSON 历史数据导入 PG
- 再做一次非交易日清理

## API Contract Notes

当前前端依然走这些端点：

- `/api/stock-chart/market-pulse/strong`
- `/api/stock-chart/market-pulse/capital-flow`
- `/api/stock-chart/market-pulse/rotation`
- `/api/stock-chart/market-pulse/all`
- `/api/stock-chart/market-pulse/rotation-trend`
- `/api/stock-chart/market-pulse/industry-detail`
- `/api/stock-chart/market-pulse-scheduler/trigger`

兼容原则：

- 路径不改
- 主要字段名尽量保持不变
- 底层改为 Postgres

前端状态展示约定：

- `market` 页头需要明确展示：
  - `tradeDate`
  - `requestedTradeDate`
  - `isFallbackTradeDate`
  - `sourceKind`
  - `source`
- 目的：
  - 让用户知道当前页面是不是在读上一交易日
  - 让后续排查数据来源时不需要再猜

## Migration / Backfill Steps

### 1. 建表

执行：

```powershell
alembic upgrade head
```

### 2. 导历史数据

执行：

```powershell
python -m backend.scripts.backfill_market_pulse_postgres
```

### 3. 验证

建议检查：

- PG 中 `trade_date` 是否只包含确认交易日
- `2026-06-21` 这类非交易日不应存在
- 交易日行数是否合理
- 页面接口能否在非交易日正确回退到上一个交易日

## Current Decisions

- 不复用旧 schema，按当前业务重新设计。
- 不为“行业轮动”单独建历史表，直接从统一的 sector daily snapshot 派生。
- rotation JSON 只作为补历史数据的 legacy source，不再作为运行时主数据源。
- 允许盘中覆盖今天快照，但前提是通过统一交易日抓取规则。

## Change Log

### 2026-06-21

- 新增 `market_pulse_capture_batches`
- 新增 `market_pulse_sector_daily_snapshots`
- 新增 `MarketPulseRepository`
- 新增回填脚本 `backend/scripts/backfill_market_pulse_postgres.py`
- 运行时读路径切到 Postgres
- 明确非交易日不写库、只回退读取上一交易日
- 已执行 `alembic upgrade head`
- 已执行 backfill，当前 PG 覆盖范围:
  - `2026-06-08 ~ 2026-06-18`
  - 共 `9` 个交易日
  - 共 `174` 行
- 已补前端 `market` 页状态展示:
  - 明确显示 `tradeDate / requestedTradeDate / isFallbackTradeDate / sourceKind / source`
- 当前历史覆盖限制:
  - 旧 DuckDB 在 `2026-06-08 ~ 2026-06-17` 只有 TopN/部分行，不是完整 90 行
  - `2026-06-18` 起已有完整 90 行
  - `2026-06-21` 这类非交易日未写入 PG
