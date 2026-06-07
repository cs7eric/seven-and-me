"""F10 / 题材 / 涨停跌停 / 换手率 路由层。

所有路由都委托给 :mod:`backend.services.stock.f10` 单例；只要在 service 层切换
adapter，整套路由即可对应到不同数据源。
"""
from __future__ import annotations

from typing import Any, Callable

from flask import Blueprint, jsonify, request

from backend.services.stock.f10 import all_index_codes, get_fundamentals_service
from backend.services.stock.f10.helpers import (
    all_concept_index_codes,
    all_industry_index_codes,
    concept_index_kline,
    industry_index_kline,
    index_kline,
    stock_topics,
    topic_stocks,
)
from backend.services.stock.f10.limit_count import (
    merge_into_breadth,
    read_limit_up_down_cache,
    refresh_limit_up_down,
)
from backend.services.stock.f10.turnover import refresh_all_targets_turnover, refresh_turnover_rate


f10_bp = Blueprint('stock_f10', __name__)


# ---------------------------------------------------------------------------
# 工具方法
# ---------------------------------------------------------------------------


def _symbol_arg(default: str = '000001') -> str:
    return str(request.args.get('symbol', default)).strip() or default


def _safe_call(producer: Callable[[], dict[str, Any]]):
    try:
        return jsonify(producer())
    except ValueError as exc:
        # 业务参数错误（如 category 乱码）
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400
    except RuntimeError as exc:
        return jsonify({'error': str(exc), 'error_type': 'upstream_failure'}), 502
    except Exception as exc:  # pragma: no cover - 兜底
        return jsonify({'error': f'f10 接口失败: {exc}'}), 500


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/ping')
def f10_ping():
    return _safe_call(lambda: get_fundamentals_service().ping())


# ---------------------------------------------------------------------------
# 概念 / 题材
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/topics')
def f10_topics():
    symbol = _symbol_arg()
    return _safe_call(lambda: get_fundamentals_service().get_stock_topics(symbol))


@f10_bp.route('/api/stock-chart/f10/topic-compare')
def f10_topic_compare():
    symbol = _symbol_arg()
    topic_id = str(request.args.get('topic_id', '')).strip()
    section = str(request.args.get('section', 'gndbzfsj')).strip() or 'gndbzfsj'
    sort_by = str(request.args.get('sort_by', 'zdf')).strip() or 'zdf'
    if not topic_id:
        return jsonify({'error': 'topic_id 不能为空'}), 400
    return _safe_call(
        lambda: get_fundamentals_service().get_topic_compare(
            symbol, topic_id, section=section, sort_by=sort_by
        )
    )


# ---------------------------------------------------------------------------
# eltdx 风格 Helpers（高级封装）
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/topic-stocks')
def f10_topic_stocks():
    """题材内成分股表（按服务端排名字段整理成表）。

    对应 eltdx ``client.helpers.topic_stocks(...)``。
    支持 ``topic_id`` 或 ``topic_name`` 两种入参；不传 topic_id 时会在
    ``seed_code`` 关联的题材里按名称模糊匹配。
    """
    seed_code = str(request.args.get('seed_code', '')).strip() or '000001'
    topic_id = str(request.args.get('topic_id', '')).strip() or None
    topic_name = str(request.args.get('topic_name', '')).strip() or None
    sort_by = str(request.args.get('sort_by', 'zdf')).strip() or 'zdf'
    section = str(request.args.get('section', 'gndbzfsj')).strip() or 'gndbzfsj'
    try:
        return jsonify(topic_stocks(
            seed_code,
            topic_id=topic_id,
            topic_name=topic_name,
            sort_by=sort_by,
            section=section,
        ).to_dict())
    except LookupError as exc:
        return jsonify({'error': str(exc), 'error_type': 'not_found'}), 404
    except ValueError as exc:
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400


@f10_bp.route('/api/stock-chart/f10/stock-topics')
def f10_stock_topics():
    """个股关联题材集合（合并 topic_ids + hot_topics）。

    对应 eltdx ``client.helpers.stock_topics(...)``。
    """
    symbol = _symbol_arg()
    return jsonify(stock_topics(symbol).to_dict())


@f10_bp.route('/api/stock-chart/f10/theme-market')
def f10_theme_market():
    symbol = _symbol_arg()
    req_id = str(request.args.get('req_id', '200743')).strip() or '200743'
    return _safe_call(
        lambda: get_fundamentals_service().get_theme_market(symbol, req_id=req_id)
    )


@f10_bp.route('/api/stock-chart/sectors-market')
def f10_sectors_market():
    """按分类拉板块 / 个股行情（统一分发器）。

    ``category`` 支持：
      - 数字 ID（默认 6 = 沪深A股）
      - 别名：`沪深A股` / `A股` / `沪A` / `深A` / `all` / `全部`（走 list_by_category）
      - 行业指数：`行业指数` / `行业` / `industry` / `申万行业`（走 32 个申万行业指数 K 线）
      - 概念指数：`概念指数` / `概念` / `concept` / `通达信概念`（走 50 个概念指数 K 线）
    """
    category = str(request.args.get('category', '6')).strip() or '6'
    sort_by = str(request.args.get('sort_by', '涨幅')).strip() or '涨幅'
    try:
        count = int(request.args.get('count', 100))
    except (TypeError, ValueError):
        count = 100
    try:
        start = int(request.args.get('start', 0))
    except (TypeError, ValueError):
        start = 0
    ascending = str(request.args.get('ascending', 'false')).strip().lower() in {'1', 'true', 'yes'}
    return _safe_call(
        lambda: get_fundamentals_service().list_sectors_market(
            category, sort_by=sort_by, count=count, ascending=ascending, start=start
        )
    )


@f10_bp.route('/api/stock-chart/sectors-market/industry')
def f10_sectors_market_industry():
    """直接走 32 个申万行业指数 K 线。"""
    sort_by = str(request.args.get('sort_by', '涨幅')).strip() or '涨幅'
    try:
        count = int(request.args.get('count', 100))
    except (TypeError, ValueError):
        count = 100
    try:
        start = int(request.args.get('start', 0))
    except (TypeError, ValueError):
        start = 0
    ascending = str(request.args.get('ascending', 'false')).strip().lower() in {'1', 'true', 'yes'}
    return _safe_call(
        lambda: get_fundamentals_service().list_industry_sectors_market(
            sort_by=sort_by, count=count, ascending=ascending, start=start
        )
    )


@f10_bp.route('/api/stock-chart/sectors-market/concept')
def f10_sectors_market_concept():
    """直接走 50 个概念主题指数 K 线。"""
    sort_by = str(request.args.get('sort_by', '涨幅')).strip() or '涨幅'
    try:
        count = int(request.args.get('count', 100))
    except (TypeError, ValueError):
        count = 100
    try:
        start = int(request.args.get('start', 0))
    except (TypeError, ValueError):
        start = 0
    ascending = str(request.args.get('ascending', 'false')).strip().lower() in {'1', 'true', 'yes'}
    return _safe_call(
        lambda: get_fundamentals_service().list_concept_sectors_market(
            sort_by=sort_by, count=count, ascending=ascending, start=start
        )
    )


# ---------------------------------------------------------------------------
# 行业 / 概念 指数 K 线（完整历史）— 全程走 eltdx bars.get(kind="index")
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/eltdx/industry-index-kline')
def f10_eltdx_industry_index_kline():
    """申万行业指数完整 K 线（``sh8803XX``，来自 :data:`INDUSTRY_INDEX_CODES`）。"""
    code = str(request.args.get('code', '')).strip() or 'sh880301'
    period = str(request.args.get('period', 'day')).strip() or 'day'
    try:
        count = int(request.args.get('count', 120))
    except (TypeError, ValueError):
        count = 120
    try:
        return jsonify(industry_index_kline(code, period=period, count=count))
    except ValueError as exc:
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400


@f10_bp.route('/api/stock-chart/eltdx/concept-index-kline')
def f10_eltdx_concept_index_kline():
    """概念主题指数完整 K 线（``sh8804XX``，来自 :data:`CONCEPT_INDEX_CODES`）。"""
    code = str(request.args.get('code', '')).strip() or 'sh880401'
    period = str(request.args.get('period', 'day')).strip() or 'day'
    try:
        count = int(request.args.get('count', 120))
    except (TypeError, ValueError):
        count = 120
    try:
        return jsonify(concept_index_kline(code, period=period, count=count))
    except ValueError as exc:
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400


@f10_bp.route('/api/stock-chart/eltdx/index-kline')
def f10_eltdx_index_kline():
    """通用板块 / 指数 K 线（支持 ``880xxx`` / ``881xxx`` / ``sh88xxxx``）。"""
    code = str(request.args.get('code', '')).strip() or '881111'
    period = str(request.args.get('period', 'day')).strip() or 'day'
    try:
        count = int(request.args.get('count', 120))
    except (TypeError, ValueError):
        count = 120
    try:
        return jsonify(index_kline(code, period=period, count=count))
    except ValueError as exc:
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400


@f10_bp.route('/api/stock-chart/eltdx/index-codes')
def f10_eltdx_index_codes():
    """返回所有行业 / 概念 / 板块 指数代码（用于前端下拉选）。

    ``kind``: ``industry`` / ``concept`` / ``sector`` / 留空返回全部。
    """
    kind = str(request.args.get('kind', '')).strip().lower()
    if kind in {'', 'all', 'both'}:
        items = [
            {'code': code, 'name': name, 'kind': item_kind}
            for code, name, item_kind in all_index_codes()
        ]
    elif kind == 'industry':
        items = all_industry_index_codes()
    elif kind == 'concept':
        items = all_concept_index_codes()
    elif kind == 'sector':
        items = [
            {'code': code, 'name': name, 'kind': item_kind}
            for code, name, item_kind in all_index_codes()
            if item_kind == 'sector'
        ]
    else:
        return jsonify({'error': f"kind 仅支持 industry/concept/sector/空, 收到 {kind!r}"}), 400
    return jsonify({'items': items, 'count': len(items), 'source': 'index_codes.py'})


# ---------------------------------------------------------------------------
# 涨停跌停数量
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/limit-count', methods=['GET'])
def f10_limit_count_get():
    """读取最近一次缓存的涨停跌停统计。"""
    payload = read_limit_up_down_cache()
    if not payload:
        return jsonify({'items': [], 'has_cache': False})
    return jsonify({'items': [payload], 'has_cache': True, 'source': payload.get('source')})


@f10_bp.route('/api/stock-chart/limit-count/refresh', methods=['POST'])
def f10_limit_count_refresh():
    """强制从数据源拉一次并写盘。"""
    payload = request.get_json(silent=True) or {}
    category = str(payload.get('category', '沪深A股')).strip() or '沪深A股'
    try:
        max_pages = int(payload.get('max_pages') or 80)
    except (TypeError, ValueError):
        max_pages = 80
    return _safe_call(
        lambda: {
            'item': refresh_limit_up_down(category=category, max_pages=max_pages),
            'has_cache': True,
        }
    )


def _optional_breadth_payload() -> dict[str, Any] | None:
    """供外部在 market-breadth 路由中嵌入的 hook。"""
    cached = read_limit_up_down_cache()
    return cached


# ---------------------------------------------------------------------------
# 换手率
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/turnover', methods=['GET'])
def f10_turnover_get():
    """从 ``reference/stock/turnover/{target_type}-{symbol}.json`` 读取换手率快照。

    不触发计算。
    """
    symbol = _symbol_arg()
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    from backend.services.stock.turnover_repo import load_turnover
    payload = load_turnover(target_type, symbol)
    if not payload:
        return jsonify({'has_cache': False, 'symbol': symbol, 'target_type': target_type})
    return jsonify({'has_cache': True, 'symbol': symbol, 'target_type': target_type, 'turnover': payload})


@f10_bp.route('/api/stock-chart/turnover/refresh', methods=['POST'])
def f10_turnover_refresh():
    """计算并写回 reference/stock/turnover/ 单独文件（不再写 K 线主文件）。"""
    payload = request.get_json(silent=True) or request.args.to_dict()
    symbol = str(payload.get('symbol', '000001')).strip() or '000001'
    target_type = str(payload.get('target_type', 'stock')).strip() or 'stock'
    period = str(payload.get('period', '1d')).strip() or '1d'
    adjust = str(payload.get('adjust', 'qfq')).strip() or 'qfq'
    return _safe_call(
        lambda: refresh_turnover_rate(symbol, target_type, period=period, adjust=adjust)
    )


@f10_bp.route('/api/stock-chart/turnover/refresh-all', methods=['POST'])
def f10_turnover_refresh_all():
    """批量刷新 target.json 中所有 enabled 标的的换手率。

    主要给"调度器手动 trigger"和"测试"用。
    """
    from backend.services.stock.application_analysis_store import load_targets
    targets = load_targets().get('items', [])
    return _safe_call(lambda: refresh_all_targets_turnover(targets))


@f10_bp.route('/api/stock-chart/turnover/scheduler/status')
def f10_turnover_scheduler_status():
    """查询 turnover 刷新调度器状态（最近一次运行 / 累计 / 是否在跑）。"""
    from backend.services.scheduler.turnover_scheduler import get_turnover_scheduler_status
    return _safe_call(get_turnover_scheduler_status)


@f10_bp.route('/api/stock-chart/turnover/scheduler/trigger', methods=['POST'])
def f10_turnover_scheduler_trigger():
    """手动触发一次 turnover 刷新（绕开时间窗）。"""
    from backend.services.scheduler.turnover_scheduler import get_turnover_scheduler
    return _safe_call(get_turnover_scheduler().trigger_now)


# ---------------------------------------------------------------------------
# F10 基础 / 公司
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/stock-info')
def f10_stock_info():
    return _safe_call(lambda: get_fundamentals_service().get_stock_info(_symbol_arg()))


@f10_bp.route('/api/stock-chart/f10/company-profile')
def f10_company_profile():
    section = str(request.args.get('section', '8')).strip() or '8'
    return _safe_call(
        lambda: get_fundamentals_service().get_company_profile(_symbol_arg(), section=section)
    )


@f10_bp.route('/api/stock-chart/f10/business-composition')
def f10_business_composition():
    report_date = request.args.get('report_date') or None
    return _safe_call(
        lambda: get_fundamentals_service().get_business_composition(_symbol_arg(), report_date=report_date)
    )


# ---------------------------------------------------------------------------
# F10 估值 / 财务
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/valuation')
def f10_valuation():
    req_id = str(request.args.get('req_id', '200191')).strip() or '200191'
    return _safe_call(
        lambda: get_fundamentals_service().get_valuation(_symbol_arg(), req_id=req_id)
    )


@f10_bp.route('/api/stock-chart/f10/finance-report')
def f10_finance_report():
    report_type = str(request.args.get('report_type', 'zcfzb')).strip() or 'zcfzb'
    return _safe_call(
        lambda: get_fundamentals_service().get_finance_report(_symbol_arg(), report_type=report_type)
    )


@f10_bp.route('/api/stock-chart/f10/finance-diagnosis')
def f10_finance_diagnosis():
    section = str(request.args.get('section', 'yynl')).strip() or 'yynl'
    return _safe_call(
        lambda: get_fundamentals_service().get_finance_diagnosis(_symbol_arg(), section=section)
    )


@f10_bp.route('/api/stock-chart/f10/stock-score')
def f10_stock_score():
    section = str(request.args.get('section', 'pf')).strip() or 'pf'
    return _safe_call(
        lambda: get_fundamentals_service().get_stock_score(_symbol_arg(), section=section)
    )


@f10_bp.route('/api/stock-chart/f10/profit-forecast')
def f10_profit_forecast():
    return _safe_call(lambda: get_fundamentals_service().get_profit_forecast(_symbol_arg()))


# ---------------------------------------------------------------------------
# F10 排名 / 治理
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/ranking-detail')
def f10_ranking_detail():
    section = str(request.args.get('section', 'scpmdela')).strip() or 'scpmdela'
    return _safe_call(
        lambda: get_fundamentals_service().get_ranking_detail(_symbol_arg(), section=section)
    )


@f10_bp.route('/api/stock-chart/f10/governance')
def f10_governance():
    section = str(request.args.get('section', 'wgcl')).strip() or 'wgcl'
    return _safe_call(
        lambda: get_fundamentals_service().get_governance(_symbol_arg(), section=section)
    )


# ---------------------------------------------------------------------------
# 内部 hook：供 market-breadth 路由 merge 数据
# ---------------------------------------------------------------------------


__all__ = [
    'f10_bp',
    'merge_into_breadth',
    'read_limit_up_down_cache',
    'refresh_limit_up_down',
    'refresh_turnover_rate',
    '_optional_breadth_payload',
]
