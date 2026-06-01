from __future__ import annotations

from backend.services.stock.kline_service import resolve_stock_klines
from backend.services.stock.search_service import resolve_industry_index
from backend.services.stock.market_overview.windows import calc_return


OVERVIEW_INDUSTRIES = [
    '银行',
    '证券',
    '保险',
    '白酒',
    '食品饮料',
    '家用电器',
    '煤炭',
    '有色金属',
    '化工',
    '医药',
    '医疗器械',
    '半导体',
    '电子',
    '通信',
    '人工智能',
    '软件',
    '新能源',
    '光伏',
    '储能',
    '风电',
    '新能源汽车',
    '汽车零部件',
    '军工',
    '机械设备',
    '环保',
    '传媒',
    '旅游',
    '房地产',
]


def _sample_loader(symbol: str, period: str) -> list[dict]:
    from backend.services.stock.sample_data_service import sample_stock_klines
    return sample_stock_klines(symbol, period)


def _fetch_index_bars(name: str, symbol: str) -> list[dict]:
    items, _ = resolve_stock_klines('index', symbol, '1d', 'qfq', _sample_loader)
    return items


def build_real_industry_overview(sh_bars: list[dict], index_bars_map: dict[str, list[dict]]) -> list[dict]:
    result = []
    seen_symbols: set[str] = set()

    for industry_name in OVERVIEW_INDUSTRIES:
        try:
            resolved = resolve_industry_index(industry_name)
        except Exception:
            continue
        if not resolved:
            continue

        symbol = str(resolved.get('sectorIndexSymbol') or '').strip()
        index_name = str(resolved.get('sectorIndexName') or symbol).strip() or symbol
        industry_query = str(resolved.get('industryQuery') or industry_name).strip() or industry_name
        if not symbol or symbol in seen_symbols:
            continue

        bars = index_bars_map.get(index_name)
        if bars is None:
            try:
                bars, _ = resolve_stock_klines('index', symbol, '1d', 'qfq', _sample_loader)
            except Exception:
                continue

        if not bars or len(bars) < 61 or len(sh_bars) < 61:
            continue

        rel5 = calc_return(bars, 5)
        rel20 = calc_return(bars, 20)
        rel60 = calc_return(bars, 60)
        sh5 = calc_return(sh_bars, 5)
        sh20 = calc_return(sh_bars, 20)
        sh60 = calc_return(sh_bars, 60)
        if rel5 is None or rel20 is None or rel60 is None or sh5 is None or sh20 is None or sh60 is None:
            continue

        rr5 = round(rel5 - sh5, 4)
        rr20 = round(rel20 - sh20, 4)
        rr60 = round(rel60 - sh60, 4)
        avg_score = (rr5 + rr20 + rr60) / 3
        state = '占优' if avg_score > 0.03 else '偏强' if avg_score > 0.01 else '转弱' if avg_score < -0.01 else '均衡'
        score = rr5 * 60 + rr20 * 100 + rr60 * 80

        result.append({
            'name': industry_name,
            'indexName': index_name,
            'symbol': symbol,
            'industryQuery': industry_query,
            'relativeReturn5': rr5,
            'relativeReturn20': rr20,
            'relativeReturn60': rr60,
            'state': state,
            'score': round(score, 2),
        })
        seen_symbols.add(symbol)

    result.sort(key=lambda x: x['score'], reverse=True)
    return result
