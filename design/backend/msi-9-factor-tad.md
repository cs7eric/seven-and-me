# MSI 9 Factor 技术设计文档 (TAD)

> 维护人: cs7eric
> 更新: 2026-06-21
> 用途: 描述市场情绪指数 (MSI) 9 个子因子的实现逻辑、公式、数据源、取值方式、前端接口、调度链

---

## 1. 总览

```
composite_score = Σ weight_i × factor_i    (i = 1..9)
```

| # | 因子 | 字段名 | 权重 | 得分范围 | 百分位? |
|---|------|--------|------|----------|---------|
| 1 | 波动率情绪 | `vol` | 15% | 0–100 | ❌ 直接 (反向) |
| 2 | 成交活跃度 | `turnover` | 15% | 0–100 | ✅ (T−3y, T) |
| 3 | 价格强度 | `price_strength` | 10% | 0–100 | ✅ (T−3y, T) |
| 4 | 风险偏好 | `risk_appetite` | 10% | 0–100 | ✅ (T−3y, T) |
| 5 | 市场广度 | `breadth` | 15% | 0–100 | ✅ (T−3y, T) |
| 6 | 涨跌停情绪 | `limit_emotion` | 15% | 0–100 | ✅ (T−3y, T) |
| 7 | 赚钱效应 | `profit_effect` | 10% | 0–100 | ✅ (T−3y, T) |
| 8 | 板块扩散 | `sector_breadth` | 5% | 0–100 | ❌ 直接 (%×100) |
| 9 | 风格风险偏好 | `style_risk` | 5% | 0–100 | ✅ (T−3y, T) |

**缺失处理**: 某日某因子无数据时视为 `50`（中性），不参与计算也不报错。
**落盘**: `duckdb.market_sentiment_index_daily`（INSERT OR REPLACE by trade_date）
**非交易日拒绝落盘**（`is_trading_day` 守卫，防止调休周末脏数据）

---

## 2. 百分位算法

所有 "✅ 百分位" 因子共用同一个 helper:

```python
# backend/repositories/market/percentile_helper.py
percentile_score(table, column, target_date, current_value)
# SQL: COUNT(历史值 < current) / COUNT(*) × 100
# 窗口: trade_date ∈ (T-1060d, T)   ← 严格左开右闭，不含 T 当天
# 无历史数据时默认返回 50.0
```

**为什么需要历史分位？**
- 固定经验范围（如 spread > 2% → 100分）会随市场漂移失效
- 历史分位始终在 0–100 范围内，天然可比："当前风险偏好高于过去 3 年中 82% 的时间"

**look-ahead bias 修复**（2026-06-18）:
- 窗口严格取 `(T-1060d, T)`，不含 T 当天及之后的数据
- `WHERE trade_date >= (td - 1060 days) AND trade_date < td`

---

## 3. 各因子详解

---

### 3.1 vol — 波动率情绪（权重 15%）

**字段**: `vol_score`
**百分位**: ❌ 直接值（反向）
**数据源**: `duckdb.volatility_sentiment_daily.sentiment_score`

**算法**:

```
1. 标的: 沪深300 (sh000300)，来自 index_daily_raw
2. 20 日年化波动率: realized_vol = std(r_{t-19}..r_t) × √252 × 100   单位: %
3. 历史分位数 (252 日滚动窗口):
   sample = 过去 252 天的 vol 值（不含今天）
   percentile_1y = count(sample <= current_vol) / len(sample)   ∈ [0, 1]
4. 情绪得分（反向）:
   sentiment_score = (1 - percentile_1y) × 100   ∈ [0, 100]
   波动率越低 → percentile 越低 → 得分越高（平静情绪）
   波动率越高 → percentile 越高 → 得分越低（恐慌情绪）
```

**落盘表**: `volatility_sentiment_daily`
**落盘守卫**: `is_trading_day`（防止调休脏数据）
**缺失返回**: `None`（上游 MSI 走中性 50）

---

### 3.2 turnover — 成交活跃度（权重 15%）

**字段**: `turnover_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.turnover_activity_daily.score`（已落盘则直接读；无则现算 ratio 后调 percentile_score）

**算法**:

```
1. total_amount = 当日全市场成交额（亿元）
   来源: market_overview_daily.total_amount（sh000001 + sz399001 TDX day 文件回填）
2. avg_20d_amount = 当日之前 20 个交易日成交额均值（不含 today）
3. ratio = total_amount / avg_20d_amount
4. score = percentile_score("turnover_activity_daily", "ratio", td, ratio)
   即: ratio 在过去 3 年滚动窗口内的百分位
```

**原始 ratio 用途**: `turnover_activity_daily.ratio` 本身存入表，前端用 `rawValue` 展示
**落盘守卫**: `is_trading_day`
**回填**: `scripts/backfill_turnover_from_index.py`（用 sh000001 + sz399001 TDX amount 回填 2018-01-02 起）

---

### 3.3 price_strength — 价格强度（权重 10%）

**字段**: `price_strength_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.ma_count_daily.new_high_252d_pct`

**算法**:

```
pct = 当日创 252 日新高的股票数 / 全部合格股票数  （%）
score = percentile_score("ma_count_daily", "new_high_252d_pct", td, pct)
```

**"创新高"判定**（`indicator_repo.calc_ma_count`）:
```sql
-- 窗口必须满 252 行 (LAG(close, 251) IS NOT NULL) 才有资格算新高
MAX(close) OVER (ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)  AS max_252d
is_new_high = close >= max_252d AND LAG(close, 251) IS NOT NULL
-- "持平"也算新高
```

---

### 3.4 risk_appetite — 风险偏好（权重 10%）

**字段**: `risk_appetite_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.risk_appetite_daily.spread_weighted`

**算法**:

```
spread = 沪深300近20日累计收益率 - 国债ETF近20日累计收益率（等权 511010 + 511090）

spread > 0 → 股票跑赢债市 → 风险偏好积极
spread < 0 → 避险情绪

score = percentile_score("risk_appetite_daily", "spread_weighted", td, spread)
```

**窗口**: 20 个交易日（≈ 1 个月）
**ETF**: 上证国债ETF (511010) 50% + 30年国债ETF (511090) 50%

---

### 3.5 breadth — 市场广度（权重 15%）

**字段**: `breadth_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.ma_count_daily.breadth_raw`

**算法**:

```
breadth_raw = 0.40 × pctAdvancing        (当日上涨股票占比)
            + 0.35 × pctAboveMa20        (站 MA20 股票占比)
            + 0.25 × pctAboveMa60        (站 MA60 股票占比)

score = percentile_score("ma_count_daily", "breadth_raw", td, breadth_raw)
```

**`pctAdvancing`**: close > LAG(close, 1)（前一日收盘价）
**`pctAboveMa20/60`**: close > MA20 / MA60（窗口须满，排除次新股）
**合格股票**: is_active=true + 非ST + 有≥60天历史

---

### 3.6 limit_emotion — 涨跌停情绪（权重 15%）

**字段**: `limit_emotion_score`
**百分位**: ✅ (T−3y, T)，CompositeScore 自身百分位
**数据源**: `duckdb.limit_emotion_summary_daily.composite_score`

**子因子**（三个原始指标各自的固定公式，存于表）:

| 子指标 | 公式 | 说明 |
|--------|------|------|
| `up_down_score` | `50 + 25 × log₂(ratio)` | 涨停/跌停比，ratio=1锚定50 |
| `break_board_score` | `100 - 100 × 炸板率` | 反向：炸板率越高得分越低 |
| `yesterday_return_score` | `50 + 10 × 昨日涨停股今日平均涨跌%` | 衡量昨日涨停股今日表现 |

```
composite_raw = 0.4 × up_down_score + 0.3 × break_board_score + 0.3 × yesterday_return_score
composite_score = percentile_score("limit_emotion_summary_daily", "composite_score", td, composite_raw)
```

**注意**: `composite_score` 自身做了历史分位（而非 raw 值），解决原公式在涨停潮时饱和到 100 的问题。
**涨停判定**: `close >= pre_close × (1 + threshold) × (1 - 0.0001)`（容差 0.01%）
**连板逻辑**: `gaps-and-islands`（ROW_NUMBER 差值法），`streak ≥ 2` 为连板

---

### 3.7 profit_effect — 赚钱效应（权重 10%）

**字段**: `profit_effect_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.profit_effect_daily.score`

**算法**:

```
raw_score = 0.60 × up_5d_pct + 0.40 × (100 - new_low_60d_pct)

score = percentile_score("profit_effect_daily", "score", td, raw_score)
```

**含义**: 近5日上涨面越宽 + 60日新低越少 → 赚钱效应越好

---

### 3.8 sector_breadth — 板块扩散（权重 5%）

**字段**: `sector_breadth_score`
**百分位**: ❌ 直接（已是 0–100）
**数据源**: `duckdb.market_pulse_sector_breadth_daily.advance_pct`

**算法**:

```
score = advance_pct × 100

# advance_pct = 上涨行业数 / 全部行业数
# 来源: ths_industry_fund_flow_daily (同花顺 90 行业)
```

**不需要百分位的原因**: `advance_pct` 本身已经是 0–1 的比例，乘以 100 后直接就是 0–100 情绪分，与上涨家数占比同口径。

---

### 3.9 style_risk — 风格风险偏好（权重 5%）

**字段**: `style_risk_score`
**百分位**: ✅ (T−3y, T)
**数据源**: `duckdb.style_risk_appetite_daily.spread`

**算法**:

```
spread = 中证1000近5日累计收益率 - 沪深300近5日累计收益率

spread > 0 → 小盘股跑赢大盘股 → 风格偏风险
spread < 0 → 大盘股跑赢小盘股 → 风格偏避险

score = percentile_score("style_risk_appetite_daily", "spread", td, spread)
```

**窗口**: 5 个交易日

---

## 4. 数据流与调度链

### 4.1 收盘后 cron 调度链（完整 pipeline）

```
16:30  tdx_hsjday_download           → download_tdx_hsjday.py → 全A日线 hsjday.zip (~538MB)
16:45  initial_backfill              → initial_backfill.py → TDX .day 解析 → duckdb daily_raw (INSERT OR IGNORE)
16:50  qfq_reconciliation            → fetch_one_date_eltdx.py → qfq/hfq 复权对账补拉 (daily_qfq / daily_hfq)
-----  daily_eod_incremental 已废弃, 所有步骤拆分到上面 3 个独立 job -----
17:03  limit_emotion                 → backfill_limit_emotion_summary.py → limit_emotion_summary_daily
17:05  risk_appetite                 → backfill_risk_appetite.py → risk_appetite_daily
17:06  ma_count                      → backfill_ma_count_and_returns.py → ma_count_daily + index_returns_daily
17:07  volatility_sentiment          → backfill_volatility_sentiment.py → volatility_sentiment_daily
17:08  style_risk_appetite           → backfill_style_risk_appetite.py → style_risk_appetite_daily
17:09  profit_effect                 → backfill_profit_effect.py → profit_effect_daily
17:10  market_overview_daily         → backfill_market_overview_daily.py → total_amount (成交额) 等大盘数据
17:12  turnover_activity             → backfill_turnover_activity.py → total_amount/20日均 → turnover_activity_daily
17:15  ths_industry_fund_flow        → backfill_ths_industry_fund_flow.py (不再算 sector_breadth)
17:17  sector_breadth                → backfill_sector_breadth.py → market_pulse_sector_breadth_daily
17:20  market_sentiment_index        → backfill_market_sentiment_index.py --require-full
                                       ↑ 前置检查: 8 张子表全部有当天数据; 不全则 skip
```

每个 job 只负责一件事。加上 `turnover` (个股换手率, F10 数据) 线程常驻盘内刷新 (与 MSI 无关)。

### 4.2 Market Sentiment Category（DB `app.scheduler_jobs` 注册, 14 个 job）

| Job | Cron | MSI 角色 |
|-----|------|----------|
| `tdx_hsjday_download` | 16:30 | **上游**: 原始数据下载 |
| `initial_backfill_refresh` | 16:45 | **上游**: TDX .day → duckdb daily_raw |
| `qfq_reconciliation_refresh` | 16:50 | **上游**: qfq/hfq 复权对账 |
| `limit_emotion_refresh` | 17:03 | **Factor 6**: limit_emotion 涨跌停情绪, weight 15% |
| `risk_appetite_refresh` | 17:05 | **Factor 4**: risk_appetite 风险偏好, weight 10% |
| `ma_count` | 17:06 | **Factor 3+5**: price_strength(10%) + breadth(15%) |
| `volatility_sentiment_refresh` | 17:07 | **Factor 1**: vol 波动率情绪, weight 15% |
| `style_risk_appetite_refresh` | 17:08 | **Factor 9**: style_risk 风格风险偏好, weight 5% |
| `profit_effect_refresh` | 17:09 | **Factor 7**: profit_effect 赚钱效应, weight 10% |
| `market_overview_daily` | 17:10 | **Factor 2 数据源**: total_amount 全市场成交额 |
| `turnover_activity_refresh` | 17:12 | **Factor 2**: turnover 成交活跃度, weight 15% |
| `sector_breadth_refresh` | 17:17 | **Factor 8**: sector_breadth 板块扩散, weight 5% |
| `market_sentiment_index_refresh` | 17:20 | **Composite**: 9 factor weighted sum → 0-100 |
| `daily_eod_incremental` | (废弃) | 所有子步骤已拆分到独立 job |

### 4.3 cache-aside 模式

---

## 5. 关键设计决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-06-18 | 全部 9 因子改用 (T−1060d, T) 百分位 | 避免未来数据漂移，保持 0–100 可比性 |
| 2026-06-18 | `enrich_history_scores` 改 expanding-window 自连接 | 原 PERCENT_RANK batch 脚本用全窗排序，存在 look-ahead bias |
| 2026-06-18 | `WORKDAYS_OVERTIME` 清空，11 个调休日期移入 HOLIDAYS | A 股从不开调休补班日，原数据全错 |
| 2026-06-18 | `limit_emotion` 的 `composite_score` 自身也做百分位 | 原 raw 值在涨停潮时饱和到 100，无法区分极端情况 |
| 2026-06-18 | `breadth_raw = 0.40×pctAdvancing + 0.35×pctMA20 + 0.25×pctMA60` | 原来用 `pct_both`（站双均线比例），覆盖不足 |
| 2026-06-16 | `turnover` 数据从 sh000001 + sz399001 TDX amount 回填 | `market_overview_daily` 只有 2023-06 以降数据，20日均值严重偏低 |
| 2026-06-21 | 全部 14 个 job 归入 market-sentiment category | 统一管理 MSI 9 factor 全链路: 上游数据 + 9 factor + composite |
| 2026-06-21 | initial_backfill / qfq_reconciliation / turnover_activity 拆成独立 cron job | 从 daily_eod_incremental 拆出, 每个 job 只做一件事; daily_eod_incremental 废弃 |
| 2026-06-21 | limit_emotion / sector_breadth 拆成独立 scheduler job | 原来寄生在 daily_eod_incremental / ths_industry_fund_flow_daily 里, 没有独立 cron |
| 2026-06-21 | breadth / profit_effect 子卡改用百分位 | 原来子卡显示 raw 值, MSI composite 用 percentile, 不一致 |
| 2026-06-21 | MSI cron 17:10 → 17:20 + 前置检查 9 factor 全就绪 | turnover_activity 17:12 才跑完, MSI 必须在所有 factor 之后; 不全则 skip |

---

## 6. 相关文件索引

| 文件 | 职责 |
|------|------|
| `backend/repositories/market/market_sentiment_index_repo.py` | MSI 主入口，9 因子 fetchers，cache-aside |
| `backend/repositories/market/percentile_helper.py` | `percentile_score` + `enrich_history_scores` |
| `backend/repositories/market/volatility_sentiment_repo.py` | 波动率情绪（沪深300 vol） |
| `backend/repositories/market/turnover_activity_repo.py` | 成交活跃度（ratio + 20日均） |
| `backend/repositories/market/risk_appetite_repo.py` | 风险偏好（沪深300 vs 国债 ETF） |
| `backend/repositories/market/indicator_repo.py` | MA 计数（市场广度、252日新高、5日上涨、60日新低） |
| `backend/repositories/market/limit_repo.py` | 涨跌停情绪（连板/炸板统计） |
| `backend/repositories/market/profit_effect_repo.py` | 赚钱效应（up_5d + new_low_60d） |
| `backend/repositories/market/sector_breadth_repo.py` | 板块扩散（同花顺行业涨跌比） |
| `backend/repositories/market/style_risk_appetite_repo.py` | 风格风险偏好（中证1000 vs 沪深300） |
| `backend/services/scheduler/tdx_hsjday_download_scheduler.py` | 数据下载 scheduler (16:30) |
| `backend/services/scheduler/initial_backfill_scheduler.py` | TDX 解析入库 scheduler (16:45, 独立) |
| `backend/services/scheduler/qfq_reconciliation_scheduler.py` | qfq/hfq 复权对账 scheduler (16:50, 独立) |
| `backend/services/scheduler/limit_emotion_scheduler.py` | 涨跌停情绪 scheduler (17:03, 独立) |
| `backend/services/scheduler/risk_appetite_scheduler.py` | 风险偏好 scheduler (17:05) |
| `backend/services/scheduler/ma_count_scheduler.py` | MA 计数 + 指数收益 scheduler (17:06) |
| `backend/services/scheduler/volatility_sentiment_scheduler.py` | 波动率情绪 scheduler (17:07) |
| `backend/services/scheduler/style_risk_appetite_scheduler.py` | 风格风险偏好 scheduler (17:08) |
| `backend/services/scheduler/profit_effect_scheduler.py` | 赚钱效应 scheduler (17:09) |
| `backend/services/scheduler/market_overview_daily_scheduler.py` | 大盘概况 scheduler (17:10) |
| `backend/services/scheduler/turnover_activity_scheduler.py` | 成交活跃度 scheduler (17:12, 独立) |
| `backend/services/scheduler/sector_breadth_scheduler.py` | 板块扩散 scheduler (17:17, 独立) |
| `backend/services/scheduler/market_sentiment_index_scheduler.py` | MSI composite scheduler (17:20, 前置 9/9 检查) |
| `backend/services/scheduler/turnover_scheduler.py` | 个股换手率线程 (盘内实时, 与 MSI 无关) |
| `backend/services/stock/trading_calendar.py` | `is_trading_day`，`WORKDAYS_OVERTIME` 清空 |
| `scripts/backfill_turnover_from_index.py` | TDX sh+sz amount 回填 turnover_activity |
| `scripts/backfill_limit_emotion_summary_batch.py` | expanding-window 重算 limit_emotion 4 个 score 列 |

---

## 7. 前端实现

### 7.1 页面布局

```
/market/sentiment
├── MarketSentimentIndexCard        (顶部大卡, 3/4 高)
│   ├── MSI 大数字 (0-100, 颜色阈值: ≥70红/≥60橙/≥50琥珀/≥40天蓝/≥30蓝/＜30灰)
│   ├── ECharts SentimentLine        (双Y轴: 左0-100情绪分 + 右auto-scale上证指数叠加)
│   └── 日期选择 Popover
├── RiskAppetiteCard                (右侧竖列, 第1行)
├── MarketBreadthCard                (右侧竖列, 第2行)
├── NewHigh252dCard                 (右侧竖列, 第3行)
├── SectorBreadthCard               (右侧竖列, 第4行)
├── TurnoverActivityCard            (右侧竖列, 第5行)
├── LimitEmotionCard                (右侧竖列, 第6行)
├── VolatilitySentimentCard         (右侧竖列, 第7行)
├── StyleRiskAppetiteCard           (右侧竖列, 第8行)
└── ProfitEffectCard               (右侧竖列, 第9行)
```

布局: `md:grid-cols-[5fr_2fr]` — 左侧 5/6 放合成指数大卡（撑满高度），右侧 1/6 放 9 张子卡（`overflow-y-auto` 独立滚动）。

---

### 7.2 前端 API fetcher 函数

| 因子 | fetcher 函数 | 所在行 | 端点 |
|------|-------------|--------|------|
| MSI composite | `fetchMarketSentimentIndex(date?)` | api.ts:2618 | `GET /api/stock-chart/market-sentiment/index` |
| MSI history | `fetchMarketSentimentIndexHistory(start, end)` | api.ts:2653 | `GET /api/stock-chart/market-sentiment/index/history` |
| vol | `fetchMarketSentimentVolatilitySentiment(date?)` | api.ts:2146 | `GET /api/stock-chart/market-sentiment/volatility-sentiment` |
| turnover | `fetchMarketSentimentTurnoverActivity(date?)` | api.ts:2276 | `GET /api/stock-chart/market-sentiment/turnover-activity` |
| risk_appetite | `fetchMarketSentimentRiskAppetite(date?)` | api.ts:1826 | `GET /api/stock-chart/market-sentiment/risk-appetite` |
| breadth (ma_count) | `fetchMarketSentimentMaCount(date?)` | api.ts:1432 | `GET /api/stock-chart/market-sentiment/ma-count` |
| limit_emotion | `fetchMarketSentimentLimitEmotionSummary(date?)` | api.ts:1987 | `GET /api/stock-chart/market-sentiment/limit-emotion-summary` |
| profit_effect | `fetchMarketSentimentProfitEffect(date?)` | api.ts:2476 | `GET /api/stock-chart/market-sentiment/profit-effect` |
| sector_breadth | `fetchMarketSentimentSectorBreadth(date?)` | api.ts:1712 | `GET /api/stock-chart/market-sentiment/sector-breadth` |
| style_risk | `fetchMarketSentimentStyleRiskAppetite(date?)` | api.ts:2367 | `GET /api/stock-chart/market-sentiment/style-risk-appetite` |
| 上证指数叠加 | `fetchIndexDailyHistory({code, start, end})` | api.ts:2844 | `GET /api/stock-chart/index/daily` |

---

### 7.3 前端类型定义

**MSI 合成指数响应** (`MarketSentimentIndexResponse`, api.ts:2581):
```typescript
interface MarketSentimentIndexResponse {
  ok: boolean
  tradeDate: string
  components: {
    vol: number | null          // 波动率情绪
    turnover: number | null     // 成交活跃度
    price_strength: number | null  // 价格强度
    risk_appetite: number | null  // 风险偏好
    breadth: number | null     // 市场广度
    limit_emotion: number | null  // 涨跌停情绪
    profit_effect: number | null  // 赚钱效应
    sector_breadth: number | null  // 板块扩散
    style_risk: number | null  // 风格风险偏好
  }
  weights: { ... }              // 9 个权重, 合计 1.0
  compositeScore: number | null // 0-100
  componentCount: number        // 实际有数据的因子数 (1-9)
  level: "hot"|"active"|"normal"|"weak"|"ice"
  fromCache?: boolean
}
```

**SubMetric 组件** (`sub-metric.tsx:35`):
```typescript
interface SubMetricProps {
  title: string
  value: string           // 主值 (大字)
  subValue: string | null // 副值 (小字)
  score: number | null    // 0-100 情绪分
  invertTone?: boolean    // 是否反向 (低分=绿, 高分=红, 默认 false)
}
```

---

### 7.4 颜色阈值（前端渲染）

**MSI 大数字颜色** (`market-sentiment-index-card.tsx:140`):
```typescript
const tone = score >= 70 ? "text-red-600"    // 极热
           : score >= 60 ? "text-orange-600"  // 偏热
           : score >= 50 ? "text-amber-600"   // 偏多
           : score >= 40 ? "text-sky-500"      // 偏弱
           : score >= 30 ? "text-blue-600"    // 低迷
           : "text-slate-400"                 // 冰点
```

**SentimentLine tooltip moodColor** (`sentiment-line.tsx`):
与 MSI 大数字阈值完全一致 (6 档: 70/60/50/40/30)。

**SubMetric 组件内评分颜色** (`sub-metric.tsx:42`):
```typescript
// 非反向模式 (默认):
score >= 70 ? "text-red-600"
: score >= 40 ? "text-amber-600"
: "text-emerald-600"

// 反向模式 (invertTone=true, 如 vol):
score >= 70 ? "text-emerald-600"
: score >= 40 ? "text-amber-600"
: "text-red-600"
```

**MSI Level 元数据** (`sub-metric.tsx:19`):
```typescript
const MSI_LEVEL_META = {
  hot:    { label: "火热", tone: "text-red-600",    chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃", tone: "text-orange-600",  chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性", tone: "text-slate-700",   chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak:   { label: "弱势", tone: "text-blue-600",    chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice:    { label: "冰点", tone: "text-slate-400",   chip: "border-slate-300 bg-slate-100 text-slate-500" },
}
```

---

### 7.5 ECharts X 轴对齐策略

**问题**: msi 历史有周末脏数据，sh 指数 API 不收录调休周六，两边日期不完全对齐会导致断线。

**解法** (`market-sentiment-index-card.tsx:158`):
```typescript
// 取 msi ∩ sh 的交集，只有两边都有的日期才渲染
const shDates = new Set(shIndex.map((it) => it.tradeDate))
const alignedHistory = (history ?? []).filter(it => shDates.has(it.tradeDate))
```

**断线处理**: ECharts 默认 `connectNulls: false`，任一数据源缺日期则断线，不使用 `connectNulls: true`（避免视觉假象）。

---

### 7.6 日期导航行为

- `date = null` → 默认行为（后端返回上一交易日）
- 用户选择历史日期 → 所有 9 张子卡 + history 一起重拉
- 重置按钮 → `setDate(null)`，回退到上一交易日
- 日历禁用规则: 周末（`getDay() === 0 || getDay() === 6`）+ 未来日期

---

### 7.7 前端组件文件索引

| 组件文件 | 职责 |
|---------|------|
| `frontend/src/views/market/market-sentiment/index.tsx` | 页面入口，布局（5/6 + 1/6 Grid） |
| `frontend/src/views/market/market-sentiment/components/market-sentiment-index-card.tsx` | 顶部合成指数大卡，ECharts 双Y轴叠加 |
| `frontend/src/views/market/market-sentiment/components/sentiment-line.tsx` | ECharts 折线图组件，支持 `overlay` prop |
| `frontend/src/views/market/market-sentiment/components/sub-metric.tsx` | SubMetric 通用子卡组件 + LEVEL_META / MSI_LEVEL_META |
| `frontend/src/views/market/market-sentiment/components/volatility-sentiment-card.tsx` | 波动率情绪子卡 |
| `frontend/src/views/market/market-sentiment/components/turnover-activity-card.tsx` | 成交活跃度子卡 |
| `frontend/src/views/market/market-sentiment/components/risk-appetite-card.tsx` | 风险偏好了卡 |
| `frontend/src/views/market/market-sentiment/components/market-breadth-card.tsx` | 市场广度子卡 |
| `frontend/src/views/market/market-sentiment/components/new-high-252d-card.tsx` | 252日新高子卡 |
| `frontend/src/views/market/market-sentiment/components/limit-emotion-card.tsx` | 涨跌停情绪子卡 |
| `frontend/src/views/market/market-sentiment/components/profit-effect-card.tsx` | 赚钱效应子卡 |
| `frontend/src/views/market/market-sentiment/components/sector-breadth-card.tsx` | 板块扩散子卡 |
| `frontend/src/views/market/market-sentiment/components/style-risk-appetite-card.tsx` | 风格风险偏好子卡 |
| `frontend/src/views/market/market-sentiment/components/skeletons.tsx` | 加载骨架屏 |
| `frontend/src/lib/api.ts` | 所有 fetcher 函数 + TypeScript 类型定义 |
