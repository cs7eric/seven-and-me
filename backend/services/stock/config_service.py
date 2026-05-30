from backend.config.settings import STOCK_CHART_CONFIG_FILE
from backend.utils.json_io import read_json_file, write_json_file


def get_stock_chart_config() -> dict:
    default = {
        'version': 1,
        'kline': {
            'minute_provider': 'mootdx',
            'daily_provider': 'tencent',
            'weekly_provider': 'tencent',
            'fallbacks': {
                'minute': ['mootdx', 'sina', 'eastmoney'],
                'daily': ['tencent', 'eastmoney'],
                'weekly': ['tencent', 'eastmoney'],
            },
            'mootdx': {
                'servers': [
                    ['110.41.147.114', 7709],
                    ['8.129.13.54', 7709],
                    ['124.70.176.52', 7709],
                ],
                'timeout': 10,
                'minute_adjust_mode': 'none_only',
            },
        },
    }
    config_data = read_json_file(STOCK_CHART_CONFIG_FILE, default)
    if not STOCK_CHART_CONFIG_FILE.exists():
        write_json_file(STOCK_CHART_CONFIG_FILE, config_data)
    return config_data
