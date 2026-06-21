# Industry / Concept Fund-Flow Postgres Migration

本文档是 `Industry / Concept Application` 资金流持久化链路的维护入口。后续任何涉及表结构、抓取写入、repository、service、API、UI 协议、交易日归档口径的修改，先读本文，再改代码；改完后同步更新本文。

## 背景

原实现的运行时链路是混合持久化：

- 爬虫抓同花顺行业资金流后先写 `reference/ths-fund-flow/latest.json`
- 盘后再写 `reference/ths-fund-flow/history/YYYY-MM-DD.json`
- 另外再通过 service 写穿或 scheduler/backfill 回填到 DuckDB

这套方式有几个业务问题：

- 真正的运行时事实源不是数据库，而是 JSON 文件
- `latest` 和 `history`、DuckDB 三套口径容易漂移
- “按交易日记录”的业务规则没有被数据库模型直接表达
- 后续 Industry / Concept Application 的历史查询、跨日序列、统计聚合都要跨 JSON 与 DuckDB 拼装

本次迁移的目标是把运行时主链重建为：

1. 网页爬取完成后直接写 Postgres
2. 以交易日为核心记录快照
3. 所有 API 历史/序列查询统一从 Postgres 读取
4. JSON 仅保留为历史导入来源，不再作为运行时主事实源

## 业务模型

这个功能的真实业务不是“一个 latest.json + 若干 history.json”，而是两层实体：

1. 抓取批次
   - 某个 scope 在某个交易日的一次完整抓取
   - 记录抓取时间、总页数、行数、来源、状态
   - 用于定位“这一天的数据是哪次抓的”

2. 交易日快照行
   - 某个交易日、某个板块的一行资金流事实
   - 包含排名、涨跌幅、流入/流出/净额、公司家数、领涨股等
   - 是 API 和 UI 真正消费的业务数据

当前 scope 先落 `industry`，但表结构预留了 `concept`，后续概念资金流可复用同一模型。

## 表设计

### `app.sector_fund_flow_capture_batches`

含义：某个 scope 在某个交易日的一次抓取批次。

关键字段：

- `id uuid pk`
- `scope varchar(32)`：`industry | concept`
- `trade_date date`
- `source_type varchar(32)`：`crawler | json_import`
- `status varchar(32)`：`success | partial | failed`
- `source varchar(128)`：当前为 `ths.10jqka.com.cn`
- `total_pages integer`
- `row_count integer`
- `page_row_counts jsonb`
- `fetched_at timestamptz`
- `extra jsonb`
- `created_at / updated_at / deleted_at`
- `remark text`

约束与索引：

- `scope + trade_date` 做 alive 唯一索引
- `scope + fetched_at desc` 做列表索引
- `status + created_at desc` 做诊断索引

### `app.sector_fund_flow_daily_snapshots`

含义：某个交易日下每个板块的一行资金流快照。

关键字段：

- `id uuid pk`
- `batch_id uuid`
- `scope varchar(32)`：`industry | concept`
- `trade_date date`
- `sector_code varchar(64)`：当前行业场景使用 THS 行业 code
- `sector_name varchar(128)`
- `rank integer`
- `change_pct numeric(10,4)`
- `inflow numeric(24,6)`
- `outflow numeric(24,6)`
- `net numeric(24,6)`
- `company_count integer`
- `leader_stock varchar(128)`
- `leader_change numeric(10,4)`
- `leader_price numeric(24,6)`
- `source varchar(128)`
- `source_type varchar(32)`：`crawler | json_import`
- `captured_at timestamptz`
- `extra jsonb`
- `created_at / updated_at / deleted_at`
- `remark text`

约束与索引：

- `scope + trade_date + sector_name` 做 alive 唯一索引
- `scope + trade_date + net desc + rank asc` 支撑单日列表 / topN
- `scope + sector_name + trade_date desc` 支撑跨日序列
- `batch_id` 索引支撑批次追踪

## 为什么这样建模

### 不直接镜像 JSON

旧 JSON 只是导入来源，不是目标 schema。业务真正关心的是：

- 这一天是哪一个交易日
- 这一天抓到了哪些板块
- 每个板块的资金流是多少
- 这一天的数据是何时抓的

所以表围绕“交易日快照”和“抓取批次”建，不围绕 `latest/history` 文件名建。

### 为什么没有物理外键

遵循 `skills/sql.md`，默认不建物理外键。这里的 `batch_id` 是逻辑关联，通过 repository 保证写入顺序和查询约束。

### 为什么保留 `extra jsonb`

`extra` 只保存原始行/扩展字段，便于：

- 导入旧 JSON 时做兼容
- 未来修正字段解析时回看源值
- 临时保留第三方页面上的非核心字段

核心查询字段都已拆成强类型列，不依赖 JSON 过滤。

## 分层设计

### ORM

文件：

- [sector_fund_flow.py](/F:/dev-repo/mp4-to-word-new/backend/models/sector_fund_flow.py)

职责：

- 描述 `capture_batches` 和 `daily_snapshots` 两个实体
- 明确 scope/source_type/status 约束
- 作为 Alembic metadata 来源

### Repository

文件：

- [ths_industry_fund_flow_repo.py](/F:/dev-repo/mp4-to-word-new/backend/repositories/market/ths_industry_fund_flow_repo.py)

职责：

- 管理 Postgres 交易日快照的 CRUD
- 首次访问时从旧 JSON 历史导入
- 历史导入时跳过腾讯指数确认后的非交易日文件
- 提供单日列表、topN、历史天序列、单行业跨日序列
- 为 `sector_breadth` 提供上游聚合输入

### Service

文件：

- [ths_fund_flow_service.py](/F:/dev-repo/mp4-to-word-new/backend/services/stock/f10/ths_fund_flow_service.py)

职责：

- 作为资金流功能的 use-case 入口
- 保证先 bootstrap 再对外服务
- 抓取成功后直接按交易日写 Postgres
- 非交易日或盘前不发起抓取，不写数据库，直接回退读取上一交易日快照
- 抓取失败时回退到数据库里最近一次已落库快照，并标记 `stale`

### Trading-Day Util

文件：

- [trading_day.py](/F:/dev-repo/mp4-to-word-new/backend/utils/trading_day.py)

职责：

- 用腾讯 `sh000001` / `sz399001` 日线确认某个历史日期是否真的是交易日
- 封装“资金流当前应该读哪一天、能不能抓今天”这套规则
- 明确盘前不能用“腾讯该日是否已有日线”来否定今天是否会交易

### API

文件：

- [stock_chart.py](/F:/dev-repo/mp4-to-word-new/backend/api/stock_chart.py)

相关路由：

- `/api/stock-chart/ths-industry/fund-flow`
- `/api/stock-chart/ths-industry/fund-flow/refresh`
- `/api/stock-chart/ths-industry/fund-flow/history`
- `/api/stock-chart/ths-industry/fund-flow/db-history`
- `/api/stock-chart/ths-industry/fund-flow/industry-series`

职责：

- 保持前端现有中文表头字段兼容
- 把原本读 JSON / DuckDB 的入口改成统一读 Postgres
- API 层继续是事务边界

### Scheduler

文件：

- [ths_industry_fund_flow_daily_scheduler.py](/F:/dev-repo/mp4-to-word-new/backend/services/scheduler/ths_industry_fund_flow_daily_scheduler.py)

职责：

- 工作日 17:15 直接爬同花顺页面
- 仅在可抓取的交易日窗口写当日快照
- 不再依赖 subprocess 扫 JSON backfill 作为日常主链

### 下游聚合

文件：

- [sector_breadth_repo.py](/F:/dev-repo/mp4-to-word-new/backend/repositories/market/sector_breadth_repo.py)

职责：

- `sector_breadth` 仍落到 DuckDB 供 MSI 现有链路消费
- 但其上游原始数据已改为读取 Postgres `sector_fund_flow_daily_snapshots`

### Frontend

关键文件：

- [api.ts](/F:/dev-repo/mp4-to-word-new/frontend/src/lib/api.ts)
- [industry-fund-flow-table.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/industry-application/components/industry-fund-flow-table.tsx)
- [index.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/industry-application/index.tsx)

职责：

- 页面交互保持不变
- 文案不能再把运行时持久化写成 `reference/...`
- stale 提示要表达“展示的是数据库里的最近快照”，不是“磁盘缓存”

## 交易日规则

这是本次迁移最重要的业务约束之一。

规则：

1. 抓取结果必须归属到明确的 `trade_date`
2. 历史日期是否是交易日，统一用腾讯上证/深证指数日线是否存在该日数据来确认
3. 盘前不能用“腾讯今天还没有日线”来否定今天是否为交易日
4. 非交易日或盘前不抓资金流页面、不写数据库，直接读上一交易日快照
5. 同一 `scope + trade_date` 只保留一组 alive 快照
6. 当天重抓时，旧快照软删，新快照替换

这样能保证：

- 历史查询按交易日稳定
- topN、跨日序列不会混入“抓取日期”和“交易日期”两个口径

## JSON -> Postgres 迁移策略

历史导入策略：

1. runtime 首次访问时检查 Postgres 是否已有资金流快照
2. 如果没有，则扫描：
   - `reference/ths-fund-flow/history/*.json`
   - 若 history 为空，再兜底 `reference/ths-fund-flow/latest.json`
3. 每个历史文件按文件名或 payload 时间映射为 `trade_date`
4. 先用腾讯指数校验该日是否为真实交易日；非交易日文件跳过，不写库
5. 导入时走统一的 `replace_trade_day_snapshot()`，保证逻辑和新抓取一致
6. 导入完成后，运行时主链只读写 Postgres

注意：

- JSON 只作为导入源保留
- 不要求删除旧 JSON 文件，但不再把它们视为运行时主事实源

## 兼容策略

为了减少前端改动，API 仍保持这些兼容点：

- 中文表头字段不变
- `code` 仍由后端补齐
- `fetchedAt` / `rowCount` / `totalPages` / `pageRowCounts` 继续返回
- `stale` / `staleReason` 继续支持

内部实现已经变成：

- 不再读 `latest.json`
- 不再把 DuckDB 作为主资金流历史库

## 修改清单

涉及这个模块时，至少同步检查这些位置：

- Alembic migration
- ORM models
- `ths_industry_fund_flow_repo`
- `ths_fund_flow_service`
- `stock_chart.py` 相关路由
- `ths_industry_fund_flow_daily_scheduler`
- `sector_breadth_repo`
- `industry-fund-flow-table.tsx`
- `industry-application/index.tsx`
- 本文档

## 后续演进建议

后面如果要继续扩展，优先沿用这套模型：

- 新增 `concept` 资金流抓取并写同表
- 增加抓取失败批次记录而不是只在状态文件里留痕
- 给跨日序列增加板块类型筛选
- 给 UI 增加按交易日切换查看历史快照
