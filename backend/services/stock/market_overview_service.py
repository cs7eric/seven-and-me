from __future__ import annotations

from backend.services.stock.market_overview.windows import (
    WINDOWS,
    build_summary,
    latest_window_metrics,
    moving_average,
)
from backend.services.stock.market_overview.support_resistance import (
    build_support_resistance,
)
from backend.services.stock.market_overview.regime import (
    classify_range_type,
)
from backend.services.stock.market_overview.sentiment import (
    build_sentiment_overview,
)
from backend.services.stock.market_overview.style_rotation import (
    INDEX_SYMBOLS,
    build_style_overview,
    dominant_style_from_rows,
)
from backend.services.stock.market_overview.industry_strength import (
    build_real_industry_overview,
)
from backend.services.stock.market_overview.similar_scenarios import (
    build_similar_scenario_backtest,
)


def _fetch_index_bars(name: str, symbol: str) -> list[dict]:
    from backend.services.stock.kline_service import resolve_stock_klines
    from backend.services.stock.sample_data_service import sample_stock_klines as _sample_loader
    items, _ = resolve_stock_klines('index', symbol, '1d', 'qfq', lambda s, p: _sample_loader(s, p))
    return items


def build_market_overview() -> dict:
    index_bars_map = {name: _fetch_index_bars(name, symbol) for name, symbol in INDEX_SYMBOLS.items()}
    sh_bars = index_bars_map['上证指数']
    closes = [float(x['close']) for x in sh_bars]
    latest_close = closes[-1]
    ma20 = moving_average(closes, 20)[-1]
    ma60 = moving_average(closes, 60)[-1]
    ma120 = moving_average(closes, 120)[-1]
    ma250 = moving_average(closes, 250)[-1]

    window_metrics = latest_window_metrics(sh_bars)
    sentiment = build_sentiment_overview()
    styles = build_style_overview(index_bars_map, sh_bars)
    dominant_style = next((item['style'] for item in styles if item['state'] in {'占优', '偏强'}), '均衡')

    range_type = classify_range_type(window_metrics, latest_close, sentiment, dominant_style)
    support_levels, resistance_levels = build_support_resistance(sh_bars, window_metrics, latest_close, ma20, ma60, ma120, ma250)
    nearest_support = support_levels[0] if support_levels else None
    nearest_resistance = resistance_levels[0] if resistance_levels else None

    risk_state = '中等偏高' if sentiment['riskDiffusionScore'] >= 60 else '中等' if sentiment['riskDiffusionScore'] >= 45 else '偏低'
    summary = build_summary(range_type, window_metrics, sentiment['todayScore'], dominant_style, risk_state, support_levels, resistance_levels)

    indices = []
    for name, bars in index_bars_map.items():
        metrics = latest_window_metrics(bars)
        idx_close = float(bars[-1]['close'])
        idx_range_type = classify_range_type(metrics, idx_close)
        indices.append({
            'name': name,
            'symbol': INDEX_SYMBOLS[name],
            'close': round(idx_close, 2),
            'rangeType': idx_range_type,
            'windowMetrics': metrics,
        })

    industries = build_real_industry_overview(sh_bars, index_bars_map)
    similar_scenario_backtest = build_similar_scenario_backtest(
        sh_bars, range_type, window_metrics, sentiment, dominant_style, index_bars_map
    )

    return {
        'tradeDate': str(sh_bars[-1].get('timestamp')),
        'summary': summary,
        'shanghai': {
            'close': round(latest_close, 2),
            'rangeType': range_type,
            'windowMetrics': window_metrics,
            'supportLevels': support_levels,
            'resistanceLevels': resistance_levels,
            'nearestSupport': nearest_support,
            'nearestResistance': nearest_resistance,
            'ma20': round(ma20, 2) if ma20 else None,
            'ma60': round(ma60, 2) if ma60 else None,
            'ma120': round(ma120, 2) if ma120 else None,
            'ma250': round(ma250, 2) if ma250 else None,
        },
        'indices': indices,
        'sentiment': sentiment,
        'styles': styles,
        'industries': industries,
        'similarScenarioBacktest': similar_scenario_backtest,
    }
