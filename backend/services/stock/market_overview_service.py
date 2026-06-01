from __future__ import annotations

from backend.services.stock.market_overview.windows import (
    WINDOWS,
    build_summary,
    latest_window_metrics,
    market_state_label,
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


def _bounded(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _pick_window(window_metrics: list[dict], window: int) -> dict | None:
    return next((item for item in window_metrics if item['window'] == window), None)


def _zone_label(zone_low: float, zone_high: float, sources: list[str]) -> str:
    if abs(zone_high - zone_low) < 0.5:
        price_part = f'{zone_low:.0f}'
    else:
        price_part = f'{zone_low:.0f}-{zone_high:.0f}'
    source_part = ' / '.join(sources[:3]) if sources else '关键价位'
    return f'{price_part}：{source_part}'


def _build_price_zones(levels: list[dict], latest_close: float, zone_type: str) -> list[dict]:
    if not levels:
        return []
    ordered = sorted([item for item in levels if item.get('price')], key=lambda x: float(x['price']))
    tolerance = max(latest_close * 0.008, 2)
    clusters: list[list[dict]] = []
    for level in ordered:
        price = float(level['price'])
        if not clusters:
            clusters.append([level])
            continue
        previous_prices = [float(item['price']) for item in clusters[-1]]
        center = sum(previous_prices) / len(previous_prices)
        if abs(price - center) <= tolerance:
            clusters[-1].append(level)
        else:
            clusters.append([level])

    zones = []
    for cluster in clusters:
        prices = [float(item['price']) for item in cluster]
        strengths = [int(item.get('strength') or 0) for item in cluster]
        raw_sources = [str(item.get('label') or item.get('source') or '') for item in cluster]
        sources = []
        for source in raw_sources:
            if source and source not in sources:
                sources.append(source)
        low = min(prices)
        high = max(prices)
        weighted_price = sum(price * max(strength, 1) for price, strength in zip(prices, strengths)) / sum(max(strength, 1) for strength in strengths)
        distance_pct = weighted_price / latest_close - 1
        zones.append({
            'zoneLow': round(low, 2),
            'zoneHigh': round(high, 2),
            'type': zone_type,
            'strength': min(100, sum(strengths)),
            'sources': sources,
            'distancePct': round(distance_pct, 4),
            'label': _zone_label(low, high, sources),
        })

    if zone_type == 'support':
        zones = [item for item in zones if item['zoneHigh'] <= latest_close]
    else:
        zones = [item for item in zones if item['zoneLow'] >= latest_close]
    zones.sort(key=lambda item: abs(item['distancePct']))
    return zones[:6]


def _risk_state(sentiment: dict) -> str:
    risk_score = sentiment['riskDiffusionScore']
    if risk_score >= 60:
        return '中等偏高'
    if risk_score >= 45:
        return '中等'
    return '偏低'


def _attack_level(overall_score: int, risk_state: str, range_type: str) -> int:
    level = 1
    if overall_score >= 45:
        level = 2
    if overall_score >= 56:
        level = 3
    if overall_score >= 68:
        level = 4
    if overall_score >= 78:
        level = 5
    if '上沿' in range_type or '冲高' in range_type or '突破失败' in range_type:
        level -= 1
    if risk_state == '中等偏高':
        level -= 1
    return max(1, min(5, level))


def _stance(overall_score: int, attack_level: int, risk_state: str) -> str:
    if risk_state == '中等偏高' and attack_level <= 2:
        return '防守'
    if overall_score >= 68 and attack_level >= 4:
        return '进攻'
    if overall_score >= 50 and attack_level >= 3:
        return '结构性参与'
    return '观察'


def _industry_overview(industries: list[dict]) -> dict:
    if not industries:
        return {
            'available': False,
            'leadings': [],
            'laggings': [],
            'strongCount': 0,
            'weakCount': 0,
            'conclusion': '行业数据暂未接入，当前不使用风格数据冒充行业强弱。',
        }
    strong = [item for item in industries if item.get('state') in {'占优', '偏强'}]
    weak = [item for item in industries if item.get('state') == '转弱']
    top_names = ' / '.join(item['name'] for item in industries[:3])
    conclusion = f'行业主线集中在 {top_names}，强势行业 {len(strong)} 个，弱势行业 {len(weak)} 个。'
    return {
        'available': True,
        'leadings': industries[:5],
        'laggings': list(reversed(industries[-5:])),
        'strongCount': len(strong),
        'weakCount': len(weak),
        'conclusion': conclusion,
    }


def _style_overview(styles: list[dict], dominant_style: str) -> dict:
    dominant = next((item for item in styles if item['style'] == dominant_style), styles[0] if styles else None)
    spread = 0
    values = [item.get('relativeReturn20') for item in styles if item.get('relativeReturn20') is not None]
    if values:
        spread = round(max(values) - min(values), 4)
    conclusion = f'{dominant_style}风格占优' if dominant_style != '均衡' else '风格暂时均衡'
    if dominant and dominant.get('relativeReturn20') is not None:
        conclusion = f'{dominant_style}20日相对上证 {dominant["relativeReturn20"] * 100:.1f}%'
    return {
        'dominantStyle': dominant_style,
        'dominant': dominant,
        'spread20': spread,
        'rows': styles,
        'conclusion': conclusion,
    }


def _build_hero(range_type: str, summary: dict, sentiment: dict, dominant_style: str, risk_state: str, support_zones: list[dict], resistance_zones: list[dict]) -> dict:
    score = int(summary['overallScore'])
    attack_level = _attack_level(score, risk_state, range_type)
    nearest_resistance = resistance_zones[0]['label'] if resistance_zones else '暂无明确压力区'
    nearest_support = support_zones[0]['label'] if support_zones else '暂无明确支撑区'
    risk_level = risk_state
    headline_parts = [range_type]
    if dominant_style and dominant_style != '均衡':
        headline_parts.append(f'{dominant_style}占优')
    if sentiment.get('trend') == '改善':
        headline_parts.append('情绪修复')
    elif sentiment.get('trend') == '走弱':
        headline_parts.append('情绪走弱')
    headline = ' · '.join(headline_parts)
    one_sentence = f'当前市场为{headline}，上方关注{nearest_resistance}，下方关注{nearest_support}，风险等级{risk_level}。'
    return {
        'regime': range_type,
        'headline': headline,
        'overallScore': score,
        'attackLevel': attack_level,
        'riskLevel': risk_level,
        'oneSentence': one_sentence,
    }


def _build_action_plan(hero: dict, sentiment: dict, dominant_style: str, support_zones: list[dict], resistance_zones: list[dict]) -> dict:
    score = int(hero['overallScore'])
    attack_level = int(hero['attackLevel'])
    risk_state = str(hero['riskLevel'])
    stance = _stance(score, attack_level, risk_state)
    nearest_resistance = resistance_zones[0]['label'] if resistance_zones else '上方关键压力区'
    nearest_support = support_zones[0]['label'] if support_zones else '下方关键支撑区'
    suitable = [
        f'{dominant_style}风格内趋势保持、回踩不破的标的' if dominant_style != '均衡' else '趋势保持且未明显过热的标的',
        '强势行业内缩量回踩确认的方向',
        '量能温和放大、风险扩散没有同步上升的结构性机会',
    ]
    avoid = [
        f'指数靠近{nearest_resistance}时追高',
        '高位放量滞涨和冲高回落方向',
        '情绪走弱或炸板率偏高时追连板',
        '弱势行业里的单日反弹股',
    ]
    confirmation = [
        f'上证放量站上{nearest_resistance}',
        '上涨家数占比连续改善',
        '风险扩散分回落，情绪趋势维持改善',
        f'回踩{nearest_support}不破并重新放量',
    ]
    invalidation = [
        f'跌破{nearest_support}',
        '情绪趋势转弱且风险扩散分上行',
        f'{dominant_style}风格相对收益转弱' if dominant_style != '均衡' else '主导风格持续缺失',
    ]
    if sentiment.get('trend') == '走弱':
        suitable = ['降低仓位，等待情绪重新修复', '只保留强趋势且回撤可控的方向', '优先观察支撑区承接力度']
    return {
        'stance': stance,
        'suitable': suitable,
        'avoid': avoid,
        'confirmationSignals': confirmation,
        'invalidationSignals': invalidation,
    }


def _cycle_conclusion(window_metrics: list[dict]) -> str:
    wm20 = _pick_window(window_metrics, 20)
    wm60 = _pick_window(window_metrics, 60)
    wm250 = _pick_window(window_metrics, 250)
    short_state = market_state_label(wm20) if wm20 else '未知'
    mid_state = market_state_label(wm60) if wm60 else '未知'
    long_state = market_state_label(wm250) if wm250 else '未知'
    return f'短周期{short_state}，中周期{mid_state}，长周期{long_state}。'


def _build_internal_structure(sentiment: dict, styles: list[dict], industries: list[dict], dominant_style: str) -> dict:
    style = _style_overview(styles, dominant_style)
    industry = _industry_overview(industries)
    if industry['available']:
        combined = f'市场内部结构：情绪{sentiment["trend"]}，{style["conclusion"]}，{industry["conclusion"]}'
    else:
        combined = f'市场内部结构：情绪{sentiment["trend"]}，{style["conclusion"]}，行业数据暂未接入。'
    return {
        'sentiment': sentiment,
        'style': style,
        'industry': industry,
        'combinedConclusion': combined,
    }


def _build_shanghai_chart_bars(sh_bars: list[dict], sentiment: dict) -> list[dict]:
    sample = sh_bars[-120:]
    if not sample:
        return []
    volumes = [float(item.get('volume') or 0) for item in sample]
    amounts = [float(item.get('turnover') or 0) for item in sample]
    max_volume = max(volumes) if volumes else 0
    max_amount = max(amounts) if amounts else 0
    latest_limit_up = int(sentiment.get('limitUpCount') or 0)
    latest_break_rate = float(sentiment.get('breakRate') or 0)
    result = []
    for idx, item in enumerate(sample):
        volume = float(item.get('volume') or 0)
        amount = float(item.get('turnover') or 0)
        result.append({
            'timestamp': int(float(item.get('timestamp') or 0)),
            'open': round(float(item.get('open') or 0), 2),
            'high': round(float(item.get('high') or 0), 2),
            'low': round(float(item.get('low') or 0), 2),
            'close': round(float(item.get('close') or 0), 2),
            'volume': round(volume, 2),
            'amount': round(amount, 2),
            'volumeRatio': round(volume / max_volume, 4) if max_volume else 0,
            'turnoverProxy': round(amount / max_amount, 4) if max_amount else 0,
            'limitUpCount': latest_limit_up if idx == len(sample) - 1 else None,
            'breakRate': latest_break_rate if idx == len(sample) - 1 else None,
        })
    return result


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
    dominant_style = dominant_style_from_rows(styles)

    range_type = classify_range_type(window_metrics, latest_close, sentiment, dominant_style)
    support_levels, resistance_levels = build_support_resistance(sh_bars, window_metrics, latest_close, ma20, ma60, ma120, ma250)
    support_zones = _build_price_zones(support_levels, latest_close, 'support')
    resistance_zones = _build_price_zones(resistance_levels, latest_close, 'resistance')
    nearest_support = support_levels[0] if support_levels else None
    nearest_resistance = resistance_levels[0] if resistance_levels else None
    nearest_support_zone = support_zones[0] if support_zones else None
    nearest_resistance_zone = resistance_zones[0] if resistance_zones else None

    risk_state = _risk_state(sentiment)
    summary = build_summary(range_type, window_metrics, sentiment['todayScore'], dominant_style, risk_state, support_levels, resistance_levels)
    hero = _build_hero(range_type, summary, sentiment, dominant_style, risk_state, support_zones, resistance_zones)
    action_plan = _build_action_plan(hero, sentiment, dominant_style, support_zones, resistance_zones)

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
    internal_structure = _build_internal_structure(sentiment, styles, industries, dominant_style)
    similar_scenario_backtest = build_similar_scenario_backtest(
        sh_bars, range_type, window_metrics, sentiment, dominant_style, index_bars_map
    )

    shanghai = {
        'close': round(latest_close, 2),
        'rangeType': range_type,
        'currentZone': range_type,
        'windowMetrics': window_metrics,
        'supportLevels': support_levels,
        'resistanceLevels': resistance_levels,
        'supportZones': support_zones,
        'resistanceZones': resistance_zones,
        'nearestSupport': nearest_support,
        'nearestResistance': nearest_resistance,
        'nearestSupportZone': nearest_support_zone,
        'nearestResistanceZone': nearest_resistance_zone,
        'ma20': round(ma20, 2) if ma20 else None,
        'ma60': round(ma60, 2) if ma60 else None,
        'ma120': round(ma120, 2) if ma120 else None,
        'ma250': round(ma250, 2) if ma250 else None,
        'cycleConclusion': _cycle_conclusion(window_metrics),
    }

    return {
        'tradeDate': str(sh_bars[-1].get('timestamp')),
        'hero': hero,
        'actionPlan': action_plan,
        'shanghaiMap': {
            'close': round(latest_close, 2),
            'rangeType': range_type,
            'currentZone': range_type,
            'supportZones': support_zones,
            'resistanceZones': resistance_zones,
            'nearestSupport': nearest_support_zone,
            'nearestResistance': nearest_resistance_zone,
            'chartBars': _build_shanghai_chart_bars(sh_bars, sentiment),
        },
        'cycleMatrix': window_metrics,
        'internalStructure': internal_structure,
        'similarScenarios': similar_scenario_backtest,
        'raw': {
            'indices': indices,
            'breadth': sentiment,
            'industries': industries,
        },
        'summary': summary,
        'shanghai': shanghai,
        'indices': indices,
        'sentiment': sentiment,
        'styles': styles,
        'industries': industries,
        'similarScenarioBacktest': similar_scenario_backtest,
    }
