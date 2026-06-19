# MSI 9 Factor 技术设计文档 (TAD)

> 维护人: cs7eric
> 更新: 2026-06-19
> 用途: 描述市场情绪指数 (MSI) 9 个子因子的实现逻辑、公式、数据源、取值方式

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

## 4. 数据流与 cache-aside 模式

```
每日 17:00 scheduler 触发各子卡 save
    │
    ├─ volatility_sentiment_scheduler   → save_volatility_sentiment()
    ├─ turnover_activity_scheduler     → save_turnover_activity()
    ├─ risk_appetite_scheduler         → save_risk_appetite()
    ├─ ma_count_scheduler               → save_ma_count()
    ├─ limit_emotion_scheduler          → save_limit_emotion_summary()
    ├─ profit_effect_scheduler         → save_profit_effect()
    ├─ sector_breadth_scheduler         → upsert_sector_breadth()
    └─ style_risk_scheduler             → save_style_risk_appetite()

用户请求 MSI
    │
    └─ calc_market_sentiment_index_cached(td)
           │
           ├─ get_market_sentiment_index(td)  ← cache-aside 优先查表
           │   (命中则直接返回，无则往下)
           │
           └─ calc_market_sentiment_index(td)  ← 各因子调 percentile_score 实时算
                   │
                   └─ save_market_sentiment_index()  ← 算完写入 cache
```

**cache-aside 保证**: 任何读过的日期都会进表，下次命中 O(<10ms)

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
| `backend/services/stock/trading_calendar.py` | `is_trading_day`，`WORKDAYS_OVERTIME` 清空 |
| `scripts/backfill_turnover_from_index.py` | TDX sh+sz amount 回填 turnover_activity |
| `scripts/backfill_limit_emotion_summary_batch.py` | expanding-window 重算 limit_emotion 4 个 score 列 |
