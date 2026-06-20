from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]
REFERENCE_FOLDER = BASE_DIR / 'reference'
REFERENCE_INDEX_FILE = REFERENCE_FOLDER / 'index.json'

MP4_REFERENCE_FOLDER = REFERENCE_FOLDER / 'parse'
MP4_REFERENCE_DATA_FOLDER = MP4_REFERENCE_FOLDER / 'data'
MP4_REFERENCE_INDEX_FOLDER = MP4_REFERENCE_FOLDER / 'index'
MP4_REFERENCE_TYPE_INDEX = MP4_REFERENCE_INDEX_FOLDER / 'index.json'

STOCK_REFERENCE_FOLDER = REFERENCE_FOLDER / 'stock'
STOCK_REFERENCE_INDEX_FOLDER = STOCK_REFERENCE_FOLDER / 'index'
STOCK_REFERENCE_DATA_FOLDER = STOCK_REFERENCE_FOLDER / 'data'
STOCK_REFERENCE_CACHE_FOLDER = STOCK_REFERENCE_FOLDER / 'cache'
STOCK_REFERENCE_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'index.json'
STOCK_REFERENCE_ANNOTATION_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'annotations.json'
STOCK_REFERENCE_WORKSPACE_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'workspaces.json'
STOCK_CHART_CONFIG_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'stock_chart_config.json'

APPLICATION_ANALYSIS_FOLDER = REFERENCE_FOLDER / 'application-analysis'
APPLICATION_ANALYSIS_TARGETS_FILE = APPLICATION_ANALYSIS_FOLDER / 'targets.json'
APPLICATION_ANALYSIS_RESULTS_FOLDER = APPLICATION_ANALYSIS_FOLDER / 'results'
APPLICATION_ANALYSIS_HISTORY_FOLDER = APPLICATION_ANALYSIS_FOLDER / 'history'
APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER = APPLICATION_ANALYSIS_FOLDER / 'snapshots'
APPLICATION_ANALYSIS_SCHEDULER_FILE = APPLICATION_ANALYSIS_FOLDER / 'scheduler.json'

# ---- 行业 / 概念 应用面分析 (独立于 application-analysis，单独持久化) ----
INDUSTRY_APPLICATION_FOLDER = REFERENCE_FOLDER / 'industry-application'
INDUSTRY_APPLICATION_TARGETS_FILE = INDUSTRY_APPLICATION_FOLDER / 'targets.json'
INDUSTRY_APPLICATION_RESULTS_FOLDER = INDUSTRY_APPLICATION_FOLDER / 'results'
INDUSTRY_APPLICATION_HISTORY_FOLDER = INDUSTRY_APPLICATION_FOLDER / 'history'
INDUSTRY_APPLICATION_SCHEDULER_FILE = INDUSTRY_APPLICATION_FOLDER / 'scheduler.json'

# ---- 自选股（self-selected）持久化 ----
SELF_SELECTED_FOLDER = REFERENCE_FOLDER / 'self-selected'
SELF_SELECTED_GROUPS_FILE = SELF_SELECTED_FOLDER / 'groups.json'
SELF_SELECTED_ITEMS_FILE = SELF_SELECTED_FOLDER / 'items.json'

# 每日盘后定时跑"近 30 天应用分析快照"的时间窗口（北京时间）。
#: 默认在 A 股收盘 15:30 后开始跑，盘后 30 分钟内触发。
APPLICATION_ANALYSIS_DAILY_DEFAULT_HOUR = 15
APPLICATION_ANALYSIS_DAILY_DEFAULT_MINUTE = 30
#: 北京时间相对 UTC 的偏移小时数。
APPLICATION_ANALYSIS_DAILY_TIMEZONE_OFFSET_HOURS = 8

# ---- 换手率单独持久化目录（不再写进 K 线主文件） ----
STOCK_TURNOVER_DIR = REFERENCE_FOLDER / 'stock' / 'turnover'

# ---- A 股"全市场"日持久化（用于同花顺式热力图） ----
# 每日 17:00（盘后）由 backend/scripts/refresh_stock_universe.py 拉取:
#   1. 全 A 股 code
#   2. 每只股的实时快照
#   3. 每只股的题材 (helpers.stock_topics) + reason 行业归一
# 运行时 (sector-heatmap) 读最新一份 JSON, 不再调 eltdx.
STOCK_UNIVERSE_DIR = REFERENCE_FOLDER / 'stock-universe'
STOCK_UNIVERSE_INDEX_FILE = STOCK_UNIVERSE_DIR / 'index.json'

# ---- 涨跌停情绪 (limitEmotion) 持久化 ----
# 不进数据库, 统一走本地 JSON. 目录布局:
#   reference/market-pulse/latest.json
#   reference/market-pulse/snapshots/<trade_date>/<HHMMSS>.json
#   reference/market-limit/daily/<trade_date>.json
#   reference/market-limit/config.json
MARKET_PULSE_LIMIT_FOLDER = REFERENCE_FOLDER / 'market-pulse'
MARKET_PULSE_LIMIT_LATEST_FILE = MARKET_PULSE_LIMIT_FOLDER / 'latest.json'
MARKET_PULSE_LIMIT_SNAPSHOTS_DIR = MARKET_PULSE_LIMIT_FOLDER / 'snapshots'
MARKET_LIMIT_FOLDER = REFERENCE_FOLDER / 'market-limit'
MARKET_LIMIT_DAILY_DIR = MARKET_LIMIT_FOLDER / 'daily'
MARKET_LIMIT_CONFIG_FILE = MARKET_LIMIT_FOLDER / 'config.json'

# ---- 同花顺全行业主力资金（hexin-v 破解）落盘目录 ----
# 由 backend/services/stock/f10/ths_fund_flow_service.py 维护, 含:
#   1) latest.json         : 全量最新一份, 给前端直接读
#   2) history/yyyy-mm-dd.json : 每日 15:30 盘后归档
THS_FUND_FLOW_DIR = REFERENCE_FOLDER / 'ths-fund-flow'

# ---- 同花顺 90 行业 / 成分股（hexin-v 破解）落盘目录 ----
# 由 backend/services/stock/f10/ths_industry_service.py (列表/info/K线) +
# backend/services/stock/f10/ths_industry_constituents_service.py (成分股) 共同维护.
# 每周六 18:00 由 backend/services/scheduler/ths_industry_constituents_scheduler.py
# 全量重爬 90 行业成分股, 落盘 constituents/{code}.json
# 包含:
#   1) industry_list.json          90 行业 {code: name} + nameToCode
#   2) industry_info.json          每行业 9 项指数数据 (akshare)
#   3) kline/                      每行业 975 根 K 线 (akshare)
#   4) constituents/{code}.json    每行业全量成分股 (hexin-v 破解)
THS_INDUSTRY_DIR = REFERENCE_FOLDER / 'ths-industry'
THS_INDUSTRY_LIST_FILE = THS_INDUSTRY_DIR / 'industry_list.json'
THS_INDUSTRY_INFO_FILE = THS_INDUSTRY_DIR / 'industry_info.json'
THS_INDUSTRY_KLINE_DIR = THS_INDUSTRY_DIR / 'kline'
THS_INDUSTRY_CONSTITUENTS_DIR = THS_INDUSTRY_DIR / 'constituents'
# 行业成分股索引 (由 scheduler 维护, 一次性聚合 90 行业)
THS_INDUSTRY_CONSTITUENTS_INDEX_FILE = THS_INDUSTRY_DIR / 'constituents_index.json'

# ---- scheduler 维护目录（F:\dev-repo\mp4-to-word-new\scheduler） ----
SCHEDULER_DIR = BASE_DIR / 'scheduler'
# 注: 各 job 的 config 现在存 Postgres app.scheduler_jobs.extra，
#     不再用 *job.json 文件。SCHEDULER_DIR 仅留用于 mkdir 兼容。
# 但 scheduler 模块仍引用这些常量 (legacy JSON read/write), 保留定义。
SCHEDULER_JOBS_FILE = SCHEDULER_DIR / 'jobs.json'
SCHEDULER_MA_COUNT_JOB_FILE = SCHEDULER_DIR / 'ma_count_job.json'
SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE = SCHEDULER_DIR / 'market_overview_daily_job.json'
SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE = SCHEDULER_DIR / 'market_sentiment_index_job.json'
SCHEDULER_PROFIT_EFFECT_JOB_FILE = SCHEDULER_DIR / 'profit_effect_job.json'
SCHEDULER_RISK_APPETITE_JOB_FILE = SCHEDULER_DIR / 'risk_appetite_job.json'
SCHEDULER_STYLE_RISK_APPETITE_JOB_FILE = SCHEDULER_DIR / 'style_risk_appetite_job.json'
SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE = SCHEDULER_DIR / 'volatility_sentiment_job.json'

# ---- 大盘资金 / 成交额 落地 (按天归档) ----
MARKET_OVERVIEW_FOLDER = REFERENCE_FOLDER / 'market-overview'
MARKET_OVERVIEW_LATEST_FILE = MARKET_OVERVIEW_FOLDER / 'latest.json'
#: 历史归档, 按 trading_date 命名, e.g. 2026-06-12.json
MARKET_OVERVIEW_ARCHIVE_DIR = MARKET_OVERVIEW_FOLDER / 'archive'
APPLICATION_ANALYSIS_AUCTION_FOLDER = APPLICATION_ANALYSIS_FOLDER / 'auction'

UPLOAD_FOLDER = BASE_DIR / 'uploads'
OUTPUT_FOLDER = BASE_DIR / 'outputs'

DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Referer': 'https://www.douyin.com/',
}

STOCK_EASTMONEY_HEADERS = {
    'User-Agent': DOWNLOAD_HEADERS['User-Agent'],
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': DOWNLOAD_HEADERS['Accept-Language'],
    'Referer': 'https://quote.eastmoney.com/',
    'Origin': 'https://quote.eastmoney.com',
}

STOCK_EASTMONEY_KLINE_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
STOCK_EASTMONEY_SEARCH_URL = 'https://searchapi.eastmoney.com/api/suggest/get'
STOCK_TENCENT_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
STOCK_SINA_MINUTE_KLINE_URL = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'

API_KEY = os.getenv('MINIMAX_API_KEY')
GROUP_ID = os.getenv('MINIMAX_GROUP_ID')




def ensure_app_directories() -> None:
    REFERENCE_FOLDER.mkdir(exist_ok=True)
    MP4_REFERENCE_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    MP4_REFERENCE_INDEX_FOLDER.mkdir(parents=True, exist_ok=True)
    STOCK_REFERENCE_INDEX_FOLDER.mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_DATA_FOLDER / 'annotations').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_DATA_FOLDER / 'snapshots').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_CACHE_FOLDER / 'klines').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_CACHE_FOLDER / 'intraday').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_CACHE_FOLDER / 'auction').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_CACHE_FOLDER / 'indicators').mkdir(parents=True, exist_ok=True)
    STOCK_TURNOVER_DIR.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_HISTORY_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_AUCTION_FOLDER.mkdir(parents=True, exist_ok=True)
    INDUSTRY_APPLICATION_FOLDER.mkdir(parents=True, exist_ok=True)
    INDUSTRY_APPLICATION_RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)
    INDUSTRY_APPLICATION_HISTORY_FOLDER.mkdir(parents=True, exist_ok=True)
    THS_FUND_FLOW_DIR.mkdir(parents=True, exist_ok=True)
    THS_INDUSTRY_DIR.mkdir(parents=True, exist_ok=True)
    THS_INDUSTRY_KLINE_DIR.mkdir(parents=True, exist_ok=True)
    THS_INDUSTRY_CONSTITUENTS_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    SELF_SELECTED_FOLDER.mkdir(parents=True, exist_ok=True)
    MARKET_PULSE_LIMIT_FOLDER.mkdir(parents=True, exist_ok=True)
    MARKET_PULSE_LIMIT_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    MARKET_LIMIT_FOLDER.mkdir(parents=True, exist_ok=True)
    MARKET_LIMIT_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)
