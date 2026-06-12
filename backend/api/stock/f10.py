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


@f10_bp.route('/api/stock-chart/f10/stock-sectors')
def f10_stock_sectors():
    """个股所属行业 + 概念板块 (合并 sectors 落盘快照 + live eltdx helpers.stock_topics).

    数据源 2 路合并, 去重:
    1. **sectors 快照** (scheduler 从 eltdx 同步, 落盘到 reference/stock-universe/sectors.json)
       - industry = category_raw=0
       - concept  = category_raw=2
    2. **live eltdx** ``client.helpers.stock_topics(code)``
       - topic_id 以 "X" 开头 (申万细分)         -> industry
       - topic_id 不以 "X" 开头但 relation_level 为空 (普通行业 topic) -> industry
       - relation_level 1~4 (概念 / 题材)         -> concept
       - relation_level 5 (昨日涨停 / 近N日连板 这种状态标签) -> 丢弃

    返回::
        {
          "code": "000048",
          "industries": [{name, topic_id, source}],
          "concepts":   [{name, topic_id, source}],
          "source": "sectors+eltdx_helpers",
        }
    """
    from backend.services.stock.stock_universe_service import list_sectors_by_category

    symbol = _symbol_arg()
    code = symbol.strip()

    # 1) sectors 快照: 归一化 code -> {sh,sz,bj}{6位}
    candidates: set[str] = {code}
    if code.isdigit() and len(code) == 6:
        candidates.add(f"sh{code}")
        candidates.add(f"sz{code}")
        candidates.add(f"bj{code}")
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix) and len(code) == 8:
            candidates.add(code[2:])
    candidates.discard("")

    industries: list[dict[str, Any]] = []
    concepts: list[dict[str, Any]] = []
    seen_ind: set[str] = set()   # 去重 key: name
    seen_con: set[str] = set()

    for category_raw, bucket, seen in (
        (0, industries, seen_ind),
        (2, concepts, seen_con),
    ):
        for sec in list_sectors_by_category(category_raw):
            stock_codes = set(sec.get("stock_codes") or [])
            if not stock_codes & candidates:
                continue
            name = (sec.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            bucket.append({
                "name": name,
                "topic_id": sec.get("topic_id"),
                "category_raw": category_raw,
                "source": "sectors",
            })

    # 2) live eltdx helpers.stock_topics: 失败就跳过, 不影响 sectors 快照
    try:
        live_topics = get_fundamentals_service().get_stock_topics(code).get("topics") or []
    except Exception:
        live_topics = []

    for t in live_topics:
        name = (t.get("topic_name") or "").strip()
        if not name:
            continue
        relation = t.get("relation_level")
        topic_id = t.get("topic_id") or ""
        topic_id_str = str(topic_id)
        # 行业判定: X 前缀 (申万细分) 或 relation 为空
        is_industry = topic_id_str.startswith("X") or relation in (None, "")
        # 概念判定: relation 在 1~4
        is_concept = isinstance(relation, int) and 1 <= relation <= 4
        # 状态标签 (昨日涨停/连板) relation=5 -> 丢弃
        if is_industry:
            if name in seen_ind:
                continue
            seen_ind.add(name)
            industries.append({
                "name": name,
                "topic_id": topic_id_str,
                "category_raw": 0,
                "source": "eltdx",
            })
        elif is_concept:
            if name in seen_con:
                continue
            seen_con.add(name)
            concepts.append({
                "name": name,
                "topic_id": topic_id_str,
                "category_raw": 2,
                "source": "eltdx",
            })
        # else: relation=5 状态标签, 跳过

    # 3) 注入当日涨跌幅: 从 heatmap 快照按 name 查 (磁盘读, 快, 不打 eltdx)
    #    同名 sector 在不同分类系统里可能不完全一致 (申万细分 vs 同花顺 90 行业);
    #    匹配不上时 changePercent 留空, 前端 fallback 显示 "—".
    try:
        from backend.services.stock.market_heatmap_service import build_market_heatmap
        heatmap_ind = build_market_heatmap(kind="industries", top_n=200).get("items") or []
        heatmap_con = build_market_heatmap(kind="concepts", top_n=300).get("items") or []
    except Exception:
        heatmap_ind, heatmap_con = [], []

    # 用 name 做 lookup key (去除空白 + 去除 "概念" 后缀)
    def _norm(s: str) -> str:
        return (s or "").replace(" ", "").replace("概念", "").strip()

    # 同花顺 90 行业 / 申万 32 行业 跟我们 sectors 快照里的"申万细分"**名字不一样**:
    # sectors 快照里是申万细分 (X530101001 住宅开发 / X200501001 畜禽饲料),
    # heatmap 里是申万一级 (房地产 / 食品饮料 / 钢铁). 这里**直接映射到 heatmap 名字** (单步),
    # lookup 时再链式解析 (畜禽饲料 → 饲料 → 农产品加工).
    INDUSTRY_ALIAS: dict[str, str] = {
        # 申万细分 / 申万一级 / 同花顺 三套名互转, value 必须是 heatmap 行业 name
        "住宅开发": "房地产",
        "房地产开发": "房地产",
        "畜禽饲料": "农产品加工",
        "水产饲料": "农产品加工",
        "饲料": "农产品加工",
        "其他金属": "小金属",
        "黄金": "贵金属",
        "股份制银行": "银行",
        "国有大型银行": "银行",
        "汽车整车": "乘用车",
        # 申万细分 -> 申万一级 兜底
        "其他电子": "元件",
        "其他电源设备": "电池",
        "其他社会服务": "社会服务",
        "公路铁路运输": "物流",
        "公交": "物流",
        "航空运输": "物流",
        "机场": "物流",
        "一般零售": "零售",
        "专业零售": "零售",
        "贸易": "贸易",
        "炼化及贸易": "炼化及贸易",
        "化学纤维": "化学纤维",
        "化学制品": "化学制品",
        "农化制品": "农化制品",
        "互联网电商": "互联网电商",
        "通信设备": "通信设备",
        "半导体": "半导体",
        "光学光电子": "光学光电子",
    }

    name_to_pct_ind: dict[str, float | None] = {
        _norm(it.get("name")): it.get("changePercent")
        for it in heatmap_ind
        if it.get("name")
    }
    name_to_pct_con: dict[str, float | None] = {
        _norm(it.get("name")): it.get("changePercent")
        for it in heatmap_con
        if it.get("name")
    }

    def _lookup_industry(name: str) -> float | None:
        if not name:
            return None
        key = _norm(name)
        # 1) 直接命中
        if key in name_to_pct_ind:
            return name_to_pct_ind[key]
        # 2) 别名链式解析 (畜禽饲料 → 饲料 → 农产品加工, 最多 3 跳防环)
        cur = name
        for _ in range(3):
            aliased = INDUSTRY_ALIAS.get(cur) or INDUSTRY_ALIAS.get(_norm(cur))
            if not aliased or aliased == cur:
                break
            ak = _norm(aliased)
            if ak in name_to_pct_ind:
                return name_to_pct_ind[ak]
            cur = aliased
        # 3) 模糊: 名称互为子串
        for hname, pct in name_to_pct_ind.items():
            if not hname:
                continue
            if key in hname or hname in key:
                return pct
        return None

    def _lookup_concept(name: str) -> float | None:
        if not name:
            return None
        key = _norm(name)
        if key in name_to_pct_con:
            return name_to_pct_con[key]
        for hname, pct in name_to_pct_con.items():
            if not hname:
                continue
            if key in hname or hname in key:
                return pct
        return None

    for ind in industries:
        if ind.get("changePercent") is None:
            ind["changePercent"] = _lookup_industry(ind.get("name") or "")
    for con in concepts:
        if con.get("changePercent") is None:
            con["changePercent"] = _lookup_concept(con.get("name") or "")

    return jsonify({
        "code": code,
        "industries": industries,
        "concepts": concepts,
        "count": len(industries) + len(concepts),
        "source": "sectors+eltdx_helpers+heatmap_zdf",
    })


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
# 公告 / 新闻 / 路演 / 研报 (eltdx 1.0+)
# ---------------------------------------------------------------------------


@f10_bp.route('/api/stock-chart/f10/announcements')
def f10_announcements():
    """个股公告列表 (eltdx CWSearch.tzx_rcache announcements)。"""
    return _safe_call(lambda: get_fundamentals_service().get_announcements(_symbol_arg()))


@f10_bp.route('/api/stock-chart/f10/news')
def f10_news():
    """个股新闻列表 (eltdx CWSearch.tzx_rcache news)。"""
    return _safe_call(lambda: get_fundamentals_service().get_news(_symbol_arg()))


@f10_bp.route('/api/stock-chart/f10/roadshows')
def f10_roadshows():
    """路演 / 业绩说明会列表 (eltdx CWSearch.tzx_rcache roadshows)。"""
    return _safe_call(lambda: get_fundamentals_service().get_roadshows(_symbol_arg()))


@f10_bp.route('/api/stock-chart/f10/company-news')
def f10_company_news():
    """公司研报 / 监管措施 (eltdx CWServ.tdxf10_gg_gszx)。

    ``section`` 默认 ``gsyj`` (公司研究), 其它常用值: ``zqyj`` (证券研究) /
    ``jgcs`` (监管措施) 等。
    """
    section = str(request.args.get('section', 'gsyj')).strip() or 'gsyj'
    return _safe_call(
        lambda: get_fundamentals_service().get_company_news(_symbol_arg(), section=section)
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
