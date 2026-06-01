from __future__ import annotations

from backend.services.stock.market_overview.windows import calc_return


INDEX_SYMBOLS = {
    '上证指数': '000001',
    '深证成指': '399001',
    '沪深300': '000300',
    '上证50': '000016',
    '中证500': '000905',
    '中证1000': '000852',
    '中证2000': '932000',
    '创业板指': '399006',
    '科创50': '000688',
}

STYLE_MAPPING = [
    {'style': '大盘', 'sources': ['上证50', '沪深300']},
    {'style': '中盘', 'sources': ['中证500']},
    {'style': '小盘', 'sources': ['中证1000']},
    {'style': '微盘', 'sources': ['中证2000']},
    {'style': '成长', 'sources': ['创业板指', '科创50']},
]


def _style_relative_return(index_bars_map: dict[str, list[dict]], source_names: list[str], sh_bars: list[dict], window: int) -> float | None:
    valid_returns = []
    for name in source_names:
        bars = index_bars_map.get(name)
        if not bars or len(bars) <= window or len(sh_bars) <= window:
            continue
        idx_ret = calc_return(bars, window)
        sh_ret = calc_return(sh_bars, window)
        if idx_ret is not None and sh_ret is not None:
            valid_returns.append(idx_ret - sh_ret)
    if not valid_returns:
        return None
    return round(sum(valid_returns) / len(valid_returns), 4)


def build_style_overview(index_bars_map: dict[str, list[dict]], sh_bars: list[dict]) -> list[dict]:
    result = []
    for row in STYLE_MAPPING:
        rel5 = _style_relative_return(index_bars_map, row['sources'], sh_bars, 5)
        rel20 = _style_relative_return(index_bars_map, row['sources'], sh_bars, 20)
        rel60 = _style_relative_return(index_bars_map, row['sources'], sh_bars, 60)
        values = [v for v in [rel5, rel20, rel60] if v is not None]
        avg_score = sum(values) / len(values) if values else 0
        state = '占优' if avg_score > 0.03 else '偏强' if avg_score > 0.01 else '转弱' if avg_score < -0.01 else '均衡'
        result.append({
            'style': row['style'],
            'source': row['sources'][0],
            'relativeReturn5': rel5,
            'relativeReturn20': rel20,
            'relativeReturn60': rel60,
            'state': state,
        })
    return result


def dominant_style_from_rows(rows: list[dict]) -> str:
    ranked = []
    for item in rows:
        values = [value for value in [item.get('relativeReturn5'), item.get('relativeReturn20'), item.get('relativeReturn60')] if value is not None]
        if not values:
            continue
        ranked.append((sum(values) / len(values), item['style']))
    if not ranked:
        return '均衡'
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def style_similarity(candidate_style: str, current_style: str) -> float:
    if candidate_style == current_style:
        return 0.0
    if candidate_style == '均衡' or current_style == '均衡':
        return 4.0
    return 8.0
