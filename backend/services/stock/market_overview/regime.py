from __future__ import annotations


def classify_range_type(
    window_metrics: list[dict],
    latest_close: float,
    sentiment: dict | None = None,
    dominant_style: str | None = None,
) -> str:
    wm20 = next((item for item in window_metrics if item['window'] == 20), None)
    wm60 = next((item for item in window_metrics if item['window'] == 60), None)
    wm120 = next((item for item in window_metrics if item['window'] == 120), None)
    wm250 = next((item for item in window_metrics if item['window'] == 250), None)
    if not wm20 or not wm60:
        return '箱体震荡'

    above20 = wm20.get('closeAboveMa20')
    above60 = wm20.get('closeAboveMa60')
    slope20 = wm20.get('ma20Slope') or 0
    slope60 = wm20.get('ma60Slope') or 0
    pos20 = wm20.get('rangePosition')
    pos60 = wm60.get('rangePosition') or 0.5
    ret5 = wm20.get('returnN') or 0
    ret20 = next((item.get('returnN') or 0 for item in window_metrics if item['window'] == 20), 0)
    ret60 = wm60.get('returnN') or 0
    ret120 = wm120.get('returnN') if wm120 else 0
    ret250 = wm250.get('returnN') if wm250 else 0
    pos120 = wm120.get('rangePosition') if wm120 else 0.5
    pos250 = wm250.get('rangePosition') if wm250 else 0.5

    vol_ratio = wm20.get('volumeRatio') or 1.0
    high_vol = vol_ratio > 1.3

    sentiment_score = sentiment.get('todayScore') if sentiment else 50
    sentiment_trend = sentiment.get('trend') if sentiment else '震荡'
    risk_score = sentiment.get('riskDiffusionScore') if sentiment else 50
    high_risk = risk_score > 60

    volume_on_break = bool(high_vol and pos60 > 0.75)

    if above20 and above60 and slope20 > 0.002 and slope60 > 0.001 and pos60 > 0.68 and ret60 > 0.04:
        if high_vol and ret20 > 0.04:
            return '主升趋势'
        return '主升趋势'

    if above60 and slope60 > 0 and pos60 >= 0.45 and pos60 <= 0.75 and ret5 < 0.03:
        return '上升趋势回踩'

    if pos60 > 0.82:
        if slope20 < -0.002 and ret5 < -0.01:
            return '突破失败'
        if volume_on_break:
            return '突破确认'
        if ret5 > 0:
            return '箱体上沿试探'

    if pos20 is not None and pos20 > 0.9 and slope20 > 0.003 and high_vol:
        wm15 = next((item for item in window_metrics if item['window'] == 15), None)
        short_ret = wm15.get('returnN') if wm15 else ret5
        if short_ret > 0.04:
            return '放量冲高'

    if pos20 is not None and pos20 > 0.85 and slope20 < -0.001:
        return '冲高回落'

    if pos60 < 0.2 and ret5 < 0 and slope20 <= 0:
        return '箱体下沿防守'

    if above20 and not above60 and slope60 < 0 and ret5 > 0:
        return '破位修复'

    if not above20 and not above60 and slope20 < 0 and slope60 < 0:
        if pos60 < 0.35:
            if high_risk:
                return '下跌趋势 + 风险扩散'
            return '下跌趋势'
        return '下跌趋势'

    if pos60 < 0.35 and abs(ret5) < 0.03 and abs(slope20) < 0.01:
        if ret5 > 0 and ret5 < 0.02 and vol_ratio < 0.8:
            return '缩量反弹'
        return '低位筑底'

    if pos60 > 0.85 and pos120 is not None and pos120 > 0.7 and ret20 > 0.04:
        return '高位钝化'

    weight_label = ''
    if high_vol and ret5 > 0 and slope20 > 0:
        weight_label = '+ 放量上行'
    elif high_risk:
        weight_label = '+ 风险升高'
    elif sentiment_trend == '改善' and above20:
        weight_label = '+ 情绪修复'
    elif sentiment_trend == '走弱' and (not above20 or slope20 < 0):
        weight_label = '+ 情绪走弱'
    elif dominant_style == '大盘' or dominant_style == '上证50':
        weight_label = '+ 权重托底'

    if weight_label:
        return f'箱体震荡{weight_label}'
    return '箱体震荡'
