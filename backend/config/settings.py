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

# 每日盘后定时跑"近 30 天应用分析快照"的时间窗口（北京时间）。
#: 默认在 A 股收盘 15:30 后开始跑，盘后 30 分钟内触发。
APPLICATION_ANALYSIS_DAILY_DEFAULT_HOUR = 15
APPLICATION_ANALYSIS_DAILY_DEFAULT_MINUTE = 30
#: 北京时间相对 UTC 的偏移小时数。
APPLICATION_ANALYSIS_DAILY_TIMEZONE_OFFSET_HOURS = 8

# ---- 换手率单独持久化目录（不再写进 K 线主文件） ----
STOCK_TURNOVER_DIR = REFERENCE_FOLDER / 'stock' / 'turnover'

# ---- scheduler 维护目录（F:\dev-repo\mp4-to-word-new\scheduler） ----
SCHEDULER_DIR = BASE_DIR / 'scheduler'
SCHEDULER_JOBS_FILE = SCHEDULER_DIR / 'jobs.json'
SCHEDULER_TURNOVER_JOB_FILE = SCHEDULER_DIR / 'turnover_job.json'
SCHEDULER_AUCTION_ANALYSIS_JOB_FILE = SCHEDULER_DIR / 'auction_analysis_job.json'
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
    (STOCK_REFERENCE_CACHE_FOLDER / 'auction').mkdir(parents=True, exist_ok=True)
    (STOCK_REFERENCE_CACHE_FOLDER / 'indicators').mkdir(parents=True, exist_ok=True)
    STOCK_TURNOVER_DIR.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_HISTORY_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER.mkdir(parents=True, exist_ok=True)
    APPLICATION_ANALYSIS_AUCTION_FOLDER.mkdir(parents=True, exist_ok=True)
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)
