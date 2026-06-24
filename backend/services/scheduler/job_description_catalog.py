"""Scheduler job description catalog.

集中维护 scheduler job 的业务说明 / 计算逻辑说明:
  1. 各 scheduler 在 ``register_job(...)`` 时统一取这里的描述
  2. 需要把旧 Postgres 行同步成新版 description 时, 也走这里
"""
from __future__ import annotations

from typing import Iterable


JOB_DESCRIPTION_CATALOG: dict[str, str] = {
    "turnover_refresh": """
盘内换手率刷新。

执行逻辑：
1. 工作日盘中按固定频率轮询 target.json 中启用的标的，收盘后再补跑一次。
2. 为每个标的拉取最新换手率等盘口指标，更新本地目标池展示数据。
3. 主要用于自选/分析页面的实时展示，不参与 MSI 9 因子计算。
""".strip(),
    "market_pulse_inside": """
盘中市场脉冲快照。

执行逻辑：
1. 盘中定时抓取全市场涨跌家数、成交额、热点板块和榜单摘要。
2. 生成一份面向前端的盘中 snapshot，供工作台和市场概览类页面直接消费。
3. 这是实时快照类 job，不做 MSI 因子回填。
""".strip(),
    "market_pulse_close": """
收盘市场脉冲快照。

执行逻辑：
1. 收盘后抓取一次全市场最终快照，固化当日收盘口径。
2. 输出涨跌分布、热点板块、榜单 TopN 等概览数据。
3. 用于页面展示和运维核对，不直接参与 MSI 因子计算。
""".strip(),
    "market_pulse_constituents": """
市场脉冲行业成分更新。

执行逻辑：
1. 定时刷新市场脉冲依赖的行业/主题成分集合。
2. 为盘中热点板块、行业榜单和成分股透视提供底层映射关系。
3. 属于实时展示链路的上游，不直接参与 MSI 因子回填。
""".strip(),
    "market_overview_inside": """
盘中大盘概览快照。

执行逻辑：
1. 盘中抓取指数、涨跌家数、成交额等大盘摘要指标。
2. 输出用于页面展示的实时概览对象。
3. 属于盘中快照链路，不是 MSI EOD 回填 job。
""".strip(),
    "market_overview_close": """
收盘大盘概览快照。

执行逻辑：
1. 收盘后抓取指数、成交额、涨跌家数等最终口径。
2. 生成当日收盘概览数据，供页面和后续运维核对使用。
3. 与 market_overview_daily 的 DuckDB 回填不同，这里更偏展示态 snapshot。
""".strip(),
    "market_overview_warmup": """
开盘前/启动时大盘概览预热。

执行逻辑：
1. 在正式盘中轮询前预热一份 overview snapshot。
2. 减少页面初次进入时的空白态和冷启动延迟。
3. 不负责 EOD 历史落盘。
""".strip(),
    "application_analysis": """
应用级标的分析调度。

执行逻辑：
1. 按配置对目标标的逐个执行应用分析任务。
2. 每个 target 会记录独立的 inflight / last_run 状态，支持逐标的追踪。
3. 主要服务 AI/策略分析场景，不参与 MSI 9 因子。
""".strip(),
    "auction_ai_analysis": """
集合竞价 AI 分析。

执行逻辑：
1. 在集合竞价时段读取目标池和竞价数据。
2. 调用分析链路生成竞价解读、异动原因和关注提示。
3. 结果用于盘前决策支持，不参与 MSI 9 因子计算。
""".strip(),
    "stock_universe_refresh": """
股票池基础数据刷新。

执行逻辑：
1. 更新股票、行业、题材等基础 universe 集合。
2. 为后续筛选、分析、页面下拉和成分映射提供底层静态数据。
3. 属于数据准备 job，不直接产出 MSI 因子。
""".strip(),
    "ths_industry_constituents_weekly": """
同花顺 90 行业成分股周度全量重爬。

执行逻辑：
1. 每周末全量抓取 90 个 THS 行业的最新成分股。
2. 落盘到 reference/ths-industry/constituents/*.json，供 API 和行业分析复用。
3. 作为行业映射底表，为行业宽度、热点分析等功能提供上游数据。
""".strip(),
    "ths_industry_constituents_daily": """
同花顺 90 行业成分股日度快照。

执行逻辑：
1. 每个交易日收盘后抓取 90 个 THS 行业成分快照。
2. 用于补齐日内到日终之间可能发生的行业成分变化。
3. 数据落盘后供行业相关页面和分析链路直接读取。
""".strip(),
    "tdx_hsjday_download": """
MSI 上游原始数据下载。

执行逻辑：
1. 工作日 16:30 下载通达信 hsjday 历史日线压缩包。
2. 产物是后续 initial_backfill 的输入源，尚未入 DuckDB。
3. 这是 MSI 全链路最上游的数据准备步骤。
""".strip(),
    "daily_eod_incremental": """
已废弃的 EOD 汇总 job。

执行逻辑：
1. 历史上负责把 daily_raw、limit_emotion、market_overview 等多个步骤串在一起执行。
2. 现在已拆分为 initial_backfill、qfq_reconciliation、limit_emotion、market_overview_daily、turnover_activity 等独立 job。
3. 保留此项主要为了兼容旧配置和兜底触发，不建议作为主链路使用。
""".strip(),
    "market_overview_daily": """
MSI Factor 2 的上游数据回填。

执行逻辑：
1. 工作日 18:45 回填当日市场总成交额、资金流和大盘概览等汇总指标。
2. 其中 total_amount 会被 turnover_activity 用作“当日全市场成交额”输入。
3. 结果落到 duckdb.market_overview_daily，属于 MSI 成交活跃度的直接上游。
""".strip(),
    "ths_industry_fund_flow_daily": """
同花顺 90 行业资金流日度抓取。

执行逻辑：
1. 工作日 17:15 直接抓取同花顺行业资金流页面。
2. 抓取后按交易日写入 Postgres `app.sector_fund_flow_capture_batches` 与 `app.sector_fund_flow_daily_snapshots`。
3. 相关历史接口、Industry / Concept Application 资金流页与 sector_breadth 聚合都复用这套交易日快照。
""".strip(),
    "style_risk_appetite_refresh": """
MSI Factor 9: 风格风险偏好，权重 5%。

计算逻辑：
1. spread = 中证1000 近 5 个交易日累计收益率 - 沪深300 近 5 个交易日累计收益率。
2. spread > 0 表示小盘跑赢大盘，市场风格更偏风险；spread < 0 表示更偏避险。
3. score = percentile_score('style_risk_appetite_daily', 'spread', td, spread)，即在过去约 3 年滚动窗口中的历史分位。
4. 结果落盘到 duckdb.style_risk_appetite_daily。
""".strip(),
    "profit_effect_refresh": """
MSI Factor 7: 赚钱效应，权重 10%。

计算逻辑：
1. raw_score = 0.60 × up_5d_pct + 0.40 × (100 - new_low_60d_pct)。
2. up_5d_pct 表示近 5 日上涨股票占比；new_low_60d_pct 表示创 60 日新低股票占比。
3. raw_score 越高，说明上涨面更宽且创新低更少，赚钱效应更好。
4. 最终通过过去约 3 年滚动窗口分位映射为 0-100，落盘 duckdb.profit_effect_daily。
""".strip(),
    "market_sentiment_chain_refresh": """
MSI 串行总链路调度。

执行逻辑：
1. 工作日按固定 cron 串行执行 MSI 上游、因子与 composite job。
2. 顺序执行，前一步完成并写库后才进入下一步，避免 DuckDB / 文件锁重叠。
3. 失败时在首个失败步骤处停止，保留步骤级状态供调度页排查。
""".strip(),
    "market_sentiment_index_refresh": """
MSI Composite 合成指数，9 因子加权汇总。

计算逻辑：
1. 前置检查 9 张因子子表在目标交易日全部就绪，不全则 skip。
2. composite_score = Σ weight_i × factor_i。
3. 权重依次为：vol 15%、turnover 15%、price_strength 10%、risk_appetite 10%、breadth 15%、limit_emotion 15%、profit_effect 10%、sector_breadth 5%、style_risk 5%。
4. 任一因子缺失时默认按 50（中性）处理，不让单因子缺失阻断历史回放。
5. 结果落盘到 duckdb.market_sentiment_index_daily。
""".strip(),
    "volatility_sentiment_refresh": """
MSI Factor 1: 波动率情绪，权重 15%。

计算逻辑：
1. 标的是沪深300，先计算近 20 日收益序列的年化 realized volatility。
2. 再拿过去 252 日的历史波动率样本做滚动分位。
3. 情绪分采用反向映射：sentiment_score = (1 - percentile_1y) × 100。
4. 波动率越低，情绪分越高；波动率越高，情绪分越低。
5. 结果落盘到 duckdb.volatility_sentiment_daily。
""".strip(),
    "ma_count_refresh": """
MSI Factor 3 + Factor 5 联合上游。

计算逻辑：
1. 价格强度（Factor 3）读取 ma_count_daily.new_high_252d_pct：
   创 252 日新高股票数 / 全部合格股票数，再映射到过去约 3 年历史分位。
2. 市场广度（Factor 5）读取 ma_count_daily.breadth_raw：
   breadth_raw = 0.40 × pctAdvancing + 0.35 × pctAboveMa20 + 0.25 × pctAboveMa60，
   再映射到过去约 3 年历史分位。
3. 该 job 同时回填 ma_count_daily 与 index_returns_daily，属于 MSI 价格强度和广度因子的共同上游。
""".strip(),
    "risk_appetite_refresh": """
MSI Factor 4: 风险偏好，权重 10%。

计算逻辑：
1. spread = 沪深300近 20 日累计收益率 - 国债 ETF 组合近 20 日累计收益率。
2. 国债 ETF 组合使用 511010 与 511090 各 50% 加权。
3. spread > 0 表示股票跑赢债券，风险偏好更强；spread < 0 表示更偏避险。
4. 最终对 spread 做过去约 3 年滚动历史分位，落盘 duckdb.risk_appetite_daily。
""".strip(),
    "limit_emotion_refresh": """
MSI Factor 6: 涨跌停情绪，权重 15%。

计算逻辑：
1. up_down_score = 50 + 25 × log2(涨停数 / 跌停数)。
2. break_board_score = 100 - 100 × 炸板率，炸板率越高得分越低。
3. yesterday_return_score = 50 + 10 × 昨日涨停股今日平均涨跌幅。
4. composite_raw = 0.4 × up_down_score + 0.3 × break_board_score + 0.3 × yesterday_return_score。
5. 再把 composite_raw 映射到过去约 3 年滚动历史分位，落盘 duckdb.limit_emotion_summary_daily。
""".strip(),
    "sector_breadth_refresh": """
MSI Factor 8: 板块扩散，权重 5%。

计算逻辑：
1. 统计当日上涨行业数 / 全部行业数，得到 advance_pct。
2. score = advance_pct × 100，直接映射到 0-100，不再做历史分位。
3. 这里使用的是同花顺行业资金流口径下的行业涨跌表现。
4. 结果落盘到 duckdb.market_pulse_sector_breadth_daily。
""".strip(),
    "initial_backfill_refresh": """
MSI 上游：TDX 日线解析入库。

执行逻辑：
1. 工作日 17:10 解析通达信 .day 二进制文件。
2. 把全 A 日线原始行情写入 duckdb.daily_raw，采用 INSERT OR IGNORE / 幂等回填。
3. 这是 qfq_reconciliation、ma_count、limit_emotion、profit_effect 等多个因子的共同上游。
""".strip(),
    "qfq_reconciliation_refresh": """
MSI 上游：前复权/后复权对账补齐。

执行逻辑：
1. 工作日 17:30 对目标交易日进行 qfq/hfq 对账检查。
2. 若发现 daily_qfq / daily_hfq 缺失或异常，则补拉当日复权行情。
3. 保障后续依赖复权价格的指标计算口径稳定一致。
""".strip(),
    "turnover_activity_refresh": """
MSI Factor 2: 成交活跃度，权重 15%。

计算逻辑：
1. total_amount = 当日全市场成交额，来自 duckdb.daily_raw 中 999999 与 399001 的成交额求和（元转亿元）。
2. avg_20d_amount = 当日之前 20 个交易日成交额均值，不包含当天。
3. ratio = total_amount / avg_20d_amount。
4. score = percentile_score('turnover_activity_daily', 'ratio', td, ratio)，即 ratio 在过去约 3 年滚动窗口中的历史分位。
5. 结果落盘到 duckdb.turnover_activity_daily，供 MSI composite 直接读取。
""".strip(),
    "test_scheduler_demo": """
测试用 scheduler 条目。

执行逻辑：
1. 主要用于演示注册表 CRUD、分类和前端卡片渲染。
2. 不对应真实业务调度器，也不执行实际数据回填。
""".strip(),
}


def get_job_description(code: str, fallback: str = "") -> str:
    return JOB_DESCRIPTION_CATALOG.get(code, fallback)


def iter_job_descriptions() -> Iterable[tuple[str, str]]:
    return JOB_DESCRIPTION_CATALOG.items()
