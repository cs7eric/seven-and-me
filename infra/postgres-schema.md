# PostgreSQL Schema 设计 (Persistence → DB)

> **作用**: 把 `infra/persistence-inventory.md` 中所有需要持久化的内容, 落到 PostgreSQL 15+ 的表结构.
> **生成时间**: 2026-06-09
> **配套文件**: [`infra/persistence-inventory.md`](file:///f:/dev-repo/mp4-to-word-new/infra/persistence-inventory.md) (持久化全景) · [`infra/postgres-schema.sql`](file:///f:/dev-repo/mp4-to-word-new/infra/postgres-schema.sql) (可直接执行的 DDL)
> **不入库部分** (文件系统保留): `uploads/` `outputs/` `models/` `runtime/` `prompt/*.md` `static/` `templates/`

---

## 1. 设计原则 (关键决定)

| 决定 | 理由 |
| --- | --- |
| **一个 schema, 命名为 `app`** | 单一业务域, 不用拆多 schema; 用 `seven_and_me.` 前缀避免与 `public` 冲突 |
| **JSONB vs 规范化**: 缓存类用 JSONB, 关系类规范化 | K线/分时/auction/F10 是"原文落盘, 业务层不查内部字段" → JSONB; self-selected / THS constituents 是真关系 → 规范化 |
| **复合主键**: cache 类用 (target_id, period, adjust) 等天然键 | 与现有文件命名规则 1:1 对应, 迁移脚本简单 |
| **单例表**: scheduler 实时状态用 PK=1 + CHECK 约束 | 与当前 "1 个 JSON 文件 = 1 个对象" 语义一致, 不会重复行 |
| **时间序列 PK 含 trade_date**: turnover / intraday / auction | 与现有 `{YYYY-MM-DD}.json` 文件命名对应, 方便按日期 upsert |
| **所有表都有 `created_at` / `updated_at`** | 现有 JSON 几乎都有这俩字段, 平迁 |
| **数组列 (TEXT[])**: tags / fallback_providers / indicators | 现有 JSON 数组语义保留 |
| **UPSERT**: cache 全部用 `ON CONFLICT (...) DO UPDATE` | 复用现有 "首次读落盘 + 后续覆写" 逻辑 |
| **索引策略**: 高频查询字段加 B-tree, JSONB 字段加 GIN (仅业务真查的) | 防止过度索引 |
| **分区暂不做**: 所有表先单表 | stock_universe_daily / app_analysis_history 后续如果 > 1000 万行再考虑 RANGE 分区 |
| **UUID 用 `gen_random_uuid()`** (pgcrypto) | MP4 历史天然是 UUID |

---

## 2. 持久化域 → 表 映射矩阵 (不漏)

> 行 = 持久化域 (按 `infra/persistence-inventory.md` §1-§7 顺序), 列 = 落到 PG 后的表名.

| 持久化域 | 路径 | 表 | 类型 |
| --- | --- | --- | --- |
| MP4 转写历史 | `reference/parse/data/*.json` + `index.json` | `seven_and_me.mp4_history` | 规范化 |
| 个股 workspace 配置 | `reference/stock/index/workspaces.json` | `seven_and_me.stock_workspaces` | 规范化 |
| Workspace 渲染配置 | `reference/stock/data/snapshots/*.json` | `seven_and_me.workspace_configs` | 规范化 (FK→workspaces) |
| 标线 / B/S 标记 | `reference/stock/data/annotations/*.json` | `seven_and_me.annotations` | 规范化 |
| K线缓存 | `reference/stock/cache/klines/*.json` | `seven_and_me.kline_cache` | JSONB |
| 分时缓存 | `reference/stock/cache/intraday/*.json` | `seven_and_me.intraday_cache` | JSONB |
| 集合竞价缓存 | `reference/stock/cache/auction/*.json` | `seven_and_me.auction_cache` | JSONB |
| 涨跌家数 (latest + series) | `reference/stock/cache/breadth/*.json` | `seven_and_me.market_breadth_latest` + `seven_and_me.market_breadth_series` | 混合 |
| F10 业务缓存 (12 类) | `reference/stock/cache/f10/*` | `seven_and_me.f10_cache` (通用) + `seven_and_me.f10_limit_count` (独立, 见 §11) | JSONB + 1 规范化 |
| 行业 index 覆盖 | `reference/stock/cache/industry_index_overrides.json` | `seven_and_me.industry_index_overrides` | 规范化 |
| 换手率 | `reference/stock/turnover/*.json` | `seven_and_me.turnover_files` (元) + `seven_and_me.turnover_entries` (明细) | 规范化 |
| 个股应用分析 - targets | `reference/application-analysis/targets.json` | `seven_and_me.app_analysis_targets` | 规范化 |
| 个股应用分析 - scheduler 状态 | `reference/application-analysis/scheduler.json` | `seven_and_me.app_analysis_scheduler_state` (单例) | 规范化 |
| 个股应用分析 - 最新结果 | `reference/application-analysis/results/*.json` | `seven_and_me.app_analysis_results` | JSONB |
| 个股应用分析 - 历史 | `reference/application-analysis/history/*/*.json` | `seven_and_me.app_analysis_history` | JSONB |
| 个股应用分析 - 集合竞价 AI | `reference/application-analysis/auction/*/*.json` | `seven_and_me.app_analysis_auction` | JSONB |
| 个股应用分析 - 盘后快照 | `reference/application-analysis/snapshots/*/*.json` | `seven_and_me.app_analysis_snapshots` | JSONB |
| 行业应用分析 - targets | `reference/industry-application/targets.json` | `seven_and_me.industry_app_targets` | 规范化 |
| 行业应用分析 - 结果/历史 | `reference/industry-application/results + history/` | `seven_and_me.industry_app_results` + `seven_and_me.industry_app_history` | JSONB |
| 自选股 groups | `reference/self-selected/groups.json` | `seven_and_me.self_selected_groups` | 规范化 |
| 自选股 items | `reference/self-selected/items.json` | `seven_and_me.self_selected_items` | 规范化 (FK→groups) |
| 同花顺全行业资金 | `reference/ths-fund-flow/{latest,history/*}.json` | `seven_and_me.ths_fund_flow_daily` | JSONB |
| 同花顺 90 行业 - 列表 | `reference/ths-industry/industry_list.json` | `seven_and_me.ths_industries` | 规范化 |
| 同花顺 90 行业 - 实时 9 项 | `reference/ths-industry/industry_info.json` | `seven_and_me.ths_industry_info` | JSONB |
| 同花顺 90 行业 - K线 | `reference/ths-industry/kline/*.json` | `seven_and_me.ths_industry_klines` | JSONB |
| 同花顺 90 行业 - 成分股 | `reference/ths-industry/constituents/*.json` + `constituents_index.json` | `seven_and_me.ths_industry_constituents` + `seven_and_me.ths_industry_constituents_meta` | 规范化 |
| A股全市场 - 每日快照 | `reference/stock-universe/YYYY-MM-DD.json` | `seven_and_me.stock_universe_daily` + `seven_and_me.stock_universe_daily_topics` | 规范化 |
| A股全市场 - 全 code 列表 | `reference/stock-universe/_codes.json` | `seven_and_me.stock_universe_codes` | 规范化 |
| A股全市场 - 失败 code | `reference/stock-universe/_failed_codes.json` | `seven_and_me.stock_universe_failed_codes` | 规范化 |
| A股全市场 - 进度 | `reference/stock-universe/_progress.json` | `seven_and_me.stock_universe_progress` (单例) | JSONB |
| A股全市场 - 板块分类 | `reference/stock-universe/sectors/*.json` + `sectors.json` | `seven_and_me.sectors_concepts` + `seven_and_me.sectors_industries` + `seven_and_me.sectors_styles` + `seven_and_me.sectors_index` | 规范化 |
| A股全市场 - TDX 56 行业 | `reference/stock-universe/tdx_industry_56.json` | `seven_and_me.tdx_industry_56` | 规范化 |
| A股全市场 - 分片 | `reference/stock-universe/groups/*.json` | `seven_and_me.stock_universe_groups` | JSONB |
| A股全市场 - 行情缓存 | `reference/stock-universe/_quote_cache/*.json` | `seven_and_me.stock_universe_quote_cache` | JSONB |
| A股全市场 - 股本缓存 | `reference/stock-universe/_shares_cache/*.json` | `seven_and_me.stock_universe_shares_cache` | JSONB |
| A股全市场 - qt 个股资金流 | `reference/stock-universe/qt_fund_flow/*.json` | `seven_and_me.stock_universe_qt_fund_flow` | JSONB |
| 行情页轮动快照 | `reference/stock-universe/market_pulse/rotation/*.json` | `seven_and_me.market_pulse_rotation` | JSONB |
| Scheduler 注册表 | `scheduler/jobs.json` | `seven_and_me.scheduler_jobs` | 规范化 |
| Scheduler 状态 (5 个) | `scheduler/{turnover,auction_analysis,market_pulse,stock_universe,ths_industry_constituents}_job.json` | `seven_and_me.scheduler_turnover_state` `seven_and_me.scheduler_auction_state` `seven_and_me.scheduler_market_pulse_state` `seven_and_me.scheduler_stock_universe_state` `seven_and_me.scheduler_ths_industry_constituents_state` | 单例 JSONB |
| K线数据源配置 | `reference/stock/index/stock_chart_config.json` | `seven_and_me.stock_chart_config` + `seven_and_me.stock_chart_mootdx_servers` | 规范化 |
| 顶层索引 (legacy) | `reference/index.json` | **删除**, 用 SQL 视图替代 | - |

> **覆盖率: 22 个持久化域 → 55 张表** (单 schema `seven_and_me`, 含 6 张单例 + 4 个便利视图). 不入库的部分 (`uploads / outputs / models / runtime / prompt / static / templates`) 见本文 §19.

---

## 3. 表分组 (DDL 章节索引)

- §4 [`seven_and_me.mp4_history`](#4-mp4-转写历史-1-张) — MP4 历史 (1)
- §5 [`seven_and_me.stock_workspaces` `seven_and_me.workspace_configs` `seven_and_me.annotations`](#5-个股-workspace--标线-3-张) — Workspace (3)
- §6 [`seven_and_me.kline_cache` `seven_and_me.intraday_cache` `seven_and_me.auction_cache`](#6-行情缓存-3-张) — 行情缓存 (3)
- §7 [`seven_and_me.market_breadth_latest` `seven_and_me.market_breadth_series`](#7-涨跌家数-2-张) — 涨跌家数 (2)
- §8 [`seven_and_me.f10_cache` `seven_and_me.f10_limit_count`](#8-f10-业务缓存-2-张) — F10 缓存 (2)
- §9 [`seven_and_me.industry_index_overrides`](#9-行业-index-覆盖-1-张) — 行业 index 覆盖 (1)
- §10 [`seven_and_me.turnover_files` `seven_and_me.turnover_entries`](#10-换手率-2-张) — 换手率 (2)
- §11 [`seven_and_me.app_analysis_*`](#11-个股应用分析-7-张) — application-analysis (7, 含 horizon 单例)
- §12 [`seven_and_me.industry_app_*`](#12-行业应用分析-3-张) — industry-application (3)
- §13 [`seven_and_me.self_selected_groups` `seven_and_me.self_selected_items`](#13-自选股-2-张) — 自选股 (2)
- §14 [`seven_and_me.ths_*`](#14-同花顺行业--资金-6-张) — 同花顺 (6)
- §15 [`seven_and_me.stock_universe_*` `seven_and_me.market_pulse_rotation` `seven_and_me.sectors_*` `seven_and_me.tdx_industry_56`](#15-a股全市场-15-张) — stock-universe (15)
- §16 [`seven_and_me.scheduler_jobs` `seven_and_me.scheduler_*_state`](#16-scheduler-6-张) — Scheduler (6)
- §17 [`seven_and_me.stock_chart_config` `seven_and_me.stock_chart_mootdx_servers`](#17-k线数据源配置-2-张) — K线数据源 (2)

**合计 55 张表** (`grep -c '^CREATE TABLE seven_and_me\.' infra/postgres-schema.sql` = 55).

---

## 4-17. 每张表的设计说明 + DDL (合并在 `infra/postgres-schema.sql`)

> 每张表在 SQL 文件中按 **"表注释 (说明 + 来源文件 + 当前数据量)" → DDL → 索引** 三段呈现.
> 文件: [`infra/postgres-schema.sql`](file:///f:/dev-repo/mp4-to-word-new/infra/postgres-schema.sql)

### 关键设计取舍示例

#### 4.1 `seven_and_me.mp4_history` (MP4 历史)

```
源: reference/parse/data/mp4-{uuid}.json (5 条)
PK: text (UUID 前缀)
JSONB: transcript / polished / summary / metadata
外键: 无 (MP4 历史是孤岛数据)
```

#### 5.1 `seven_and_me.stock_workspaces` (workspace 配置)

```
源: reference/stock/index/workspaces.json (10 条)
PK: text (id, e.g. 'stock-600415')
自然键: (target_type, symbol) — 唯一约束, 防止用户重复加同标的
JSONB: 不需要, 字段全规范化
```

#### 5.2 `seven_and_me.workspace_configs` (workspace 渲染配置)

```
源: reference/stock/data/snapshots/stock-{symbol}.json (14 条)
PK: workspace_id (FK → stock_workspaces.id, ON DELETE CASCADE)
说明: 这是 workspaces.json 的 "data_file" 反向指向; 1:1 关系
字段: period / adjust / indicators[] / drawing_tool / show_auction_panel
```

#### 5.3 `seven_and_me.annotations` (标线 / B/S 标记)

```
源: reference/stock/data/annotations/{id}-{period}.json (7 个文件, 多条)
表设计选择: 每个 JSON 文件是一条 annotation, 内部 items[] 拆成多行
PK: text (annotation_id, 原文件中已存在, e.g. 'anno-1780585536128')
索引: (target_id, period, overlay_type) 复合 — 业务常用 "取某标的某周期的 B/S"
CHECK: side IN ('B','S') 仅对 overlay_type='bs_point' 有效 (业务层保证)
```

#### 6.1 `seven_and_me.kline_cache` (K线缓存)

```
源: reference/stock/cache/klines/{target}-{period}-{adjust}.json (86 个)
PK: (target_id, period, adjust) 复合
JSONB: items — 单条 OHLCV 数组
upsert: ON CONFLICT (target_id, period, adjust) DO UPDATE
保留字段: source / updated_at
```

#### 6.2 `seven_and_me.intraday_cache` (分时)

```
源: reference/stock/cache/intraday/{target}-{YYYY-MM-DD}.json (10 个)
PK: (target_id, trade_date) 复合
JSONB: timeshare[]
```

#### 6.3 `seven_and_me.auction_cache` (集合竞价)

```
源: reference/stock/cache/auction/{symbol}.json (15 个)
PK: (symbol, trade_date) 复合
JSONB: opening{}
```

#### 7.1 `seven_and_me.market_breadth_latest` + `seven_and_me.market_breadth_series` (涨跌家数)

```
源: reference/stock/cache/breadth/{latest,series,eltdx_latest}.json (3 个)
设计: latest 用单例表 (PK=1 CHECK), series 用时序表
字段: upCount / downCount / limitUpCount / limitDownCount / totalCount
```

#### 8.1 `seven_and_me.f10_cache` (F10 通用) + `seven_and_me.f10_limit_count` (独立)

```
源: reference/stock/cache/f10/{12 个子目录}/ (110+ 个)
设计选择: 12 类业务里 11 类走通用 f10_cache(category, key, payload); 
        limit_count 数据大 (5万只) 且需要分页查询 → 独立规范化
f10_cache.PK: (category, key)
f10_limit_count.PK: trade_date (每日一份全量)
```

#### 10.1 `seven_and_me.turnover_files` + `seven_and_me.turnover_entries` (换手率)

```
源: reference/stock/turnover/{target}.json (5 个, 每个含 entries[])
设计: 文件元数据 (含 circulating_shares / source) → turnover_files;
      明细 entries → turnover_entries (按 trade_date 时序)
PK:
  turnover_files: (symbol, period, adjust)
  turnover_entries: (symbol, period, adjust, trade_date) — 复合
```

#### 11.1 `seven_and_me.app_analysis_targets` (应用分析 target 列表)

```
源: reference/application-analysis/targets.json (6 个)
字段: 保留现有所有字段 (id / target_type / symbol / name / adjust / enabled / interval_minutes / tags[])
PK: text (id, e.g. 'stock-600415')
额外: horizon 提到表头 (days / segments / monthly_keep / weekly_keep) — 当前 JSON 里有, 但每个 target 共享, 可上提到单例
```

#### 11.2 `seven_and_me.app_analysis_scheduler_state` (应用分析 scheduler 状态, **单例**)

```
源: reference/application-analysis/scheduler.json (单文件, 1 个对象)
设计: 单例表, PK=1, CHECK (id = 1)
字段: running / started_at / tick_count / runs_count / last_tick_at
JSONB: last_run — 嵌套 {stock-xxx: {...}}
```

#### 11.3 `seven_and_me.app_analysis_results` (最新结果)

```
源: reference/application-analysis/results/{target}.json (6 个)
PK: target_id (FK → app_analysis_targets.id)
JSONB: target / analysis_input / analysis_output
字段: overlay_count / segments / horizon (从 JSON 提到表头, 方便 SQL 查询)
```

#### 11.4 `seven_and_me.app_analysis_history` (历史)

```
源: reference/application-analysis/history/{target}/YYYYMMDD-HHMMSS.json (523 个)
PK: text (history_id, 由 target_id + finished_at 生成)
外键: target_id → app_analysis_targets.id
JSONB: analysis_input / analysis_output / horizon
字段: status / elapsed_seconds / source / finished_at / segments / overlay_count
索引: (target_id, finished_at DESC) — "取最近 N 条历史"
```

#### 11.5 `seven_and_me.app_analysis_auction` (集合竞价 AI, **每日每 target 一份**)

```
源: reference/application-analysis/auction/{target}/{YYYY-MM-DD}.json (7 个)
PK: (target_id, trade_date) 复合
JSONB: target / analysis_input / analysis_output
```

#### 11.6 `seven_and_me.app_analysis_snapshots` (盘后 15:30 recent30 快照)

```
源: reference/application-analysis/snapshots/{target}/{YYYY-MM-DD}.json (13 个)
PK: (target_id, trade_date) 复合
JSONB: snapshot — recent30 K线分段 + AI 摘要
```

#### 12.x 行业应用分析 (3 张)

```
同 §11, 但 target_type ∈ {'industry', 'concept'}, 字段 symbol = 'sh880xxx'
seven_and_me.industry_app_targets / seven_and_me.industry_app_results / seven_and_me.industry_app_history
```

#### 13.1 `seven_and_me.self_selected_groups` + `seven_and_me.self_selected_items`

```
源: reference/self-selected/{groups,items}.json
groups.PK: text (id, e.g. 'ss-grp-1780655499955-ix6z')
items.PK: text (id, e.g. 'ss-itm-1780675958974-0wwe')
items.FK: group_id → self_selected_groups.id, ON DELETE CASCADE
          (复刻现有 "删 group 级联删 item" 语义)
UNIQUE: items (group_id, symbol, market) — 同 group 不重复加同标的
CHECK: market IN ('SH','SZ','BJ','HK','US') — 现有值 'SH'
```

#### 14.1 `seven_and_me.ths_fund_flow_daily` (同花顺全行业资金)

```
源: reference/ths-fund-flow/{latest,history/YYYY-MM-DD}.json
PK: trade_date (单日一份)
JSONB: rows (11 列 × 90 行业)
"latest" 不单建表, 用 SELECT * FROM seven_and_me.ths_fund_flow_daily ORDER BY trade_date DESC LIMIT 1
```

#### 14.2 `seven_and_me.ths_industries` + `seven_and_me.ths_industry_info` + `seven_and_me.ths_industry_klines` + `seven_and_me.ths_industry_constituents` + `seven_and_me.ths_industry_constituents_meta`

```
源: reference/ths-industry/*
ths_industries.PK: code (text, e.g. '881121') — 90 行
ths_industry_info.PK: (industry_code, trade_date) — 90 行业 × 每日
ths_industry_klines.PK: (industry_code, trade_date) — 5 年 × 250 交易日 × 90
ths_industry_constituents.PK: (industry_code, snapshot_date, stock_code) — 90 × 4666 = 420K 行
ths_industry_constituents_meta.PK: (industry_code, snapshot_date) — 90 × 周频
JSONB 用法:
  info: data (9 项: 今开/昨收/最高/最低/成交量/成交额/涨跌幅/涨跌额/振幅)
  klines: data (OHLCV)
  constituents: data (14 列: 序号/代码/名称/现价/涨跌幅/涨跌/涨速/换手/量比/振幅/成交额/流通股/流通市值/市盈率)
设计选择: info / klines / constituents 都保留 JSONB (业务不查内部字段),
          但拆 3 张表, 不要塞进 ths_industries (会爆炸)
```

#### 15.x A股全市场 (14 张)

```
源: reference/stock-universe/* (含 ths_industry/ 冗余, 复用 §14)

stock_universe_daily.PK: (trading_day, code) — 每日 5530 行
stock_universe_daily_topics.PK: (trading_day, code, topic_id) — 多对多
stock_universe_codes.PK: code — 全 A 股 ~5530 行
stock_universe_failed_codes.PK: code
stock_universe_progress.PK: 1 (单例) — JSONB payload
stock_universe_groups.PK: group_id — 7 行, JSONB
stock_universe_quote_cache.PK: trade_date — JSONB
stock_universe_shares_cache.PK: trade_date — JSONB
stock_universe_qt_fund_flow.PK: (code, snapshot_date) — JSONB
market_pulse_rotation.PK: date — JSONB
sectors_concepts.PK: topic_id
sectors_industries.PK: industry_id
sectors_styles.PK: style_id
sectors_index.PK: 1 (单例) — 顶层 sector 索引
tdx_industry_56.PK: industry_code — 56 行

设计选择:
  - stock_universe_daily 规范化 (code / name / industry), 但 topics 拆多对多
  - 冗余的 ths_industry/ 不再单独建表, 用视图 v_stock_universe_ths_industry 指向 §14
  - _quote_cache / _shares_cache / groups 保留 JSONB, 因为是分片临时数据
```

#### 16.1 `seven_and_me.scheduler_jobs` (注册表) + 5 个 `*_state` (单例)

```
源: scheduler/jobs.json (8 个 job) + scheduler/{5 个}_job.json
jobs.PK: text (id, e.g. 'turnover_refresh')
字段: name / description / config_file / service_module / service_class / enabled / registered_at

5 个 state 表 (turnover / auction / market_pulse / stock_universe / ths_industry_constituents):
  PK=1 CHECK (id=1)
  JSONB payload (各 job 字段差异大, 不强行规范化)
  created_at / updated_at

为什么不合并 1 张 generic 表:
  - 每 job 的 last_run / last_log_file / last_topN 等字段差异极大
  - 单例表 + CHECK 比单表 + WHERE job_id=X 更直观, 不易出错
```

#### 17.1 `seven_and_me.stock_chart_config` + `seven_and_me.stock_chart_mootdx_servers`

```
源: reference/stock/index/stock_chart_config.json
config.PK: 1 (单例) — JSONB kline_config
servers.PK: serial — host / port / timeout
fallback_providers / indicators 等数组用 TEXT[] 而不是 JSONB
```

---

## 18. 索引 / 性能要点 (SQL 文件里有完整版)

| 表 | 关键索引 | 理由 |
| --- | --- | --- |
| `mp4_history` | `(created_at DESC)` | 历史列表按时间倒序 |
| `annotations` | `(target_id, period, overlay_type)` | 取某标的某周期某类型 |
| `kline_cache` | PK 已覆盖; 加 `(target_id, period)` 用于 "最新落盘时间" 查询 | - |
| `app_analysis_history` | `(target_id, finished_at DESC)` | 取最近 N 条 |
| `app_analysis_auction` | `(trade_date DESC)` | 跨 target 拉当日所有 |
| `app_analysis_snapshots` | `(trade_date DESC)` | 同上 |
| `ths_industry_constituents` | `(industry_code, snapshot_date)` + `(stock_code)` | "某股票所属行业" 反查 |
| `stock_universe_daily` | `(trading_day)` + `(code)` | 双方向 |
| `stock_universe_daily_topics` | `(topic_id, trading_day)` | 行业→成分股 |
| `scheduler_jobs` | `(enabled)` | 启停 job 时快速过滤 |
| `self_selected_items` | `(group_id)` + UNIQUE `(group_id, symbol, market)` | - |
| `market_breadth_series` | `(trade_date DESC)` | 时序 |
| `f10_cache` | `(category)` | 按业务路由 |

---

## 19. 不入库的部分 (文件系统保留)

| 路径 | 大小 | 处置 |
| --- | --- | --- |
| `uploads/` | 24 GB | **保留文件**, 用 MinIO / S3 替代本地 FS 是后续话题 |
| `outputs/` | 0 (空) | **保留**, export_service 写入点 |
| `models/` | 3 GB | **保留**, Whisper fp32 双份权重 |
| `runtime/application-analysis-dumps/` | 1 GB | **保留 + 清理策略**: 保留最近 7 天, 老的删 |
| `runtime/auction-analysis-dumps/` | < 100 MB | 同上 |
| `runtime/pycache-verify/` | < 50 MB | **建议清理**, 是早期 .pyc 校验脚本残留 |
| `prompt/*.md` | < 1 MB | **保留**, 在 repo 里, 不应入库 |
| `static/` `templates/` | - | **保留**, Flask 静态资源 / 模板 |

---

## 20. 迁移策略 (3 阶段)

### 阶段 1: 双写 (1 周)
- DB schema 落地, 写 migration 脚本
- 所有落盘点加 `if env == 'db': INSERT INTO ... ELSE: 写 JSON`
- 默认仍走 JSON, DB 仅做"影子写入"

### 阶段 2: DB 优先 (1 周)
- 切换默认读路径到 DB
- JSON 兜底 (DB miss → 读 JSON → 写回 DB)
- 应用层所有 `os.path.exists` → `SELECT 1 FROM ...`

### 阶段 3: JSON 归档 (3 天)
- 停 JSON 写入
- 把现有 JSON 文件移到 `reference/archive/2026-06-XX/` 备份目录
- 1 个月后确认无问题, 删除归档

---

## 21. 关联

- 全景: [`infra/persistence-inventory.md`](file:///f:/dev-repo/mp4-to-word-new/infra/persistence-inventory.md)
- DDL: [`infra/postgres-schema.sql`](file:///f:/dev-repo/mp4-to-word-new/infra/postgres-schema.sql)
- 结构索引: [`infra/index.md`](file:///f:/dev-repo/mp4-to-word-new/infra/index.md)
- 路径常量源 (待废弃): [`backend/config/settings.py`](file:///f:/dev-repo/mp4-to-word-new/backend/config/settings.py)