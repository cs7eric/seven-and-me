"""eltdx 适配器实现。

完整对照 eltdx 1.0.2 的 f10 客户端和 quotes 客户端方法，把所有 F10 / 题材 /
涨停跌停 / 换手率相关方法翻译成 :class:`FundamentalsAdapter` 抽象接口的返回
形态。底层字段通过 :func:`_f10_to_dict` 统一处理，外部不直接接触 F10ResultSet。
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone, datetime
from typing import Any, Iterable

from eltdx import TdxClient

from backend.adapters.market.eltdx_adapter import (
    _build_client,
    _safe_trade_date,
    _sanitize_jsonable,
    stock_symbol_to_eltdx_code,
)
from backend.services.stock.config_service import get_stock_chart_config

from .base import FundamentalsAdapter
from .index_codes import CONCEPT_INDEX_CODES, INDUSTRY_INDEX_CODES
from .schemas import (
    AnnouncementItem,
    Announcements,
    BusinessComposition,
    CompanyNews,
    CompanyNewsItem,
    CompanyProfile,
    FinanceDiagnosis,
    FinanceReport,
    Governance,
    LimitUpDownCount,
    NewsItem,
    NewsList,
    ProfitForecast,
    RankingDetail,
    RoadshowItem,
    Roadshows,
    SectorMarket,
    StockInfo,
    StockScore,
    StockTopicsCombined,
    ThemeMarket,
    TopicDetail,
    TopicInfo,
    TopicStock,
    TurnoverRateEntry,
    TurnoverRateSeries,
    Valuation,
)


# ---------------------------------------------------------------------------
# 工具方法
# ---------------------------------------------------------------------------


def _f10_to_dict(response: Any) -> dict[str, Any]:
    """把 F10Response 序列化成可 jsonify 的 dict。"""
    if response is None:
        return {}
    if hasattr(response, "raw") and isinstance(response.raw, dict):
        return _sanitize_jsonable(response.raw)
    if isinstance(response, dict):
        return _sanitize_jsonable(response)
    return _sanitize_jsonable(asdict(response)) if hasattr(response, "__dataclass_fields__") else {}


def _f10_rows(response: Any) -> list[dict[str, Any]]:
    if response is None:
        return []
    rows = getattr(response, "rows", None)
    if callable(rows):
        rows = rows()
    if rows:
        return [_sanitize_jsonable(row) for row in rows]
    return []


def _s(row: dict[str, Any], key: str) -> str | None:
    """安全地把 row[key] 转 str / None (eltdx 表行解析 helper)。"""
    if not isinstance(row, dict):
        return None
    value = row.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _threshold_for_code(full_code: str, last_price: float | None, pre_close_price: float | None) -> float:
    """根据代码判定涨跌停阈值（百分比）。"""
    if not full_code:
        return 9.95
    code = full_code.lower()
    # 北交所：8/9/92 开头
    if code.startswith(("bj8", "bj9", "bj92")):
        return 29.95
    # 创业板 / 科创板：sz30 / sz301 / sh688 / sh689
    if code.startswith(("sz30", "sz301", "sh688", "sh689")):
        return 19.95
    # 主板 / 中小板
    return 9.95


def _is_st(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in name


def _classify_record(record: Any, threshold_overrides: dict[str, float] | None = None) -> tuple[str, float]:
    """根据 change_pct 与阈值判定分类。

    返回 ``(bucket, threshold)``，bucket ∈ {limit_up, up, flat, down, limit_down}。
    """
    pct = getattr(record, "change_pct", None)
    if pct is None and hasattr(record, "last_price") and hasattr(record, "pre_close_price"):
        last = getattr(record, "last_price", None)
        prev = getattr(record, "pre_close_price", None)
        if isinstance(last, (int, float)) and isinstance(prev, (int, float)) and prev:
            pct = round((last - prev) / prev * 100, 4)
    if pct is None:
        return ("flat", 9.95)
    full_code = getattr(record, "full_code", "") or ""
    name = getattr(record, "name", None)
    threshold = _threshold_for_code(full_code, getattr(record, "last_price", None), getattr(record, "pre_close_price", None))
    if threshold_overrides and _is_st(name):
        st_threshold = threshold_overrides.get("st", 4.95)
        if pct >= st_threshold:
            return ("limit_up", threshold)
        if pct <= -st_threshold:
            return ("limit_down", threshold)
    if pct >= threshold:
        return ("limit_up", threshold)
    if pct <= -threshold:
        return ("limit_down", threshold)
    if pct > 0:
        return ("up", threshold)
    if pct < 0:
        return ("down", threshold)
    return ("flat", threshold)


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


# ---------------------------------------------------------------------------
# 板块 / 分类 编号映射（保护 normalize_category 的 alias 兜底问题）
# ---------------------------------------------------------------------------


#: 别名 → 通达信分类数字 ID。
#:
#: ⚠️ eltdx 库 ``CATEGORY_ALIASES`` 只内置 3 个 alias（``沪深a股 / a股 / A股 / 沪深A股``），
#: 全部映射到 category ID ``6``（沪深 A 股）。库**没有**暴露"列出所有行业板块 /
#: 概念板块 / 地域板块"的接口 —— 我们也**没有**。
#:
#: 业务侧能正确工作的 alias 只覆盖沪深 A 股；其余"行业 / 概念"等都是**未知**的，
#: 调用会到 eltdx 兜底走 ``int(text, 0)`` 然后失败。
#:
#: 要拿"行业 / 概念板块行情"，参考 :class:`EltdxFundamentalsAdapter.list_sectors_market`
#: 的 docstring，绕路走 :func:`helpers.stock_topics` + 通达信 block 文件 / 东财 / akshare。
CATEGORY_ALIASES: dict[str, int] = {
    # ---- eltdx 库内置 / 安全 ----
    "沪深a股": 6,
    "a股": 6,
    "A股": 6,
    "沪深A股": 6,
    "沪a股": 6,
    "深a股": 6,
    # ---- 业务侧补充的友好写法（同样映射到 6） ----
    "沪A": 6, "沪a": 6,
    "深A": 6, "深a": 6,
    "all": 6, "ALL": 6,
    "All": 6,
    "全部": 6,
    "全部A": 6,
    "全部A股": 6,
    "沪深a股(涨停敢死队)": 6,
    "沪深板块": 6,
}


#: 业务侧已知的"未实现 / 不支持"分类。
#: 访问这些 alias 会显式抛错，避免用户误以为系统支持。
UNSUPPORTED_CATEGORY_ALIASES: dict[str, str] = {
    "行业板块":     "eltdx 库没有暴露'列出所有行业板块'的分类接口。",
    "概念板块":     "eltdx 库没有暴露'列出所有概念板块'的分类接口；"
                   "个股关联题材请改用 /api/stock-chart/f10/topics（基于 helpers.stock_topics）。",
    "地域板块":     "eltdx 库没有暴露'列出所有地域板块'的分类接口。",
    "指数板块":     "eltdx 库没有暴露'列出所有指数板块'的分类接口。",
    "行业指数":     "行业指数代码（如 sh880301）需要走 K 线接口 client.bars.get(code, kind='index'）。",
    "概念指数":     "概念指数代码需要走 K 线接口 client.bars.get(code, kind='sector')。",
}


def _normalize_category_id(category: Any) -> int:
    """把用户传进来的 category 强制规范成 eltdx 协议层使用的数字 ID。

    - 已知 alias → 返回数字 ID
    - 已知"不支持"alias → 抛业务异常（带原因）
    - 纯数字 / 十六进制字符串 → ``int(text, 0)``
    - 其它乱码字符串 → 抛业务异常，不要让 eltdx 内部 ``int(text, 0)`` 兜底
    """
    if isinstance(category, int):
        return category
    text = str(category or "").strip()
    if not text:
        return 6  # 默认 沪深A股
    if text in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[text]
    if text in UNSUPPORTED_CATEGORY_ALIASES:
        raise ValueError(
            f"category={text!r} 当前数据源不支持：{UNSUPPORTED_CATEGORY_ALIASES[text]}"
        )
    # 尝试纯数字 / 十六进制字符串
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        raise ValueError(
            f"无法识别的 category: {text!r}。"
            f"可传数字 ID（如 6）或 alias：{sorted(CATEGORY_ALIASES.keys())}"
        ) from None


# ---------------------------------------------------------------------------
# 行业 / 概念 指数 K-line → 行情 dict
# ---------------------------------------------------------------------------


def _bar_value(bar: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in bar and bar[key] is not None:
            try:
                return float(bar[key])
            except (TypeError, ValueError):
                continue
    return None


def _bars_to_index_market(full_code: str, name: str, kind: str, bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """从最近 2 根日 K 派生指数行情。"""
    if len(bars) < 2:
        return None
    today, prev = bars[-1], bars[-2]
    last = _bar_value(today, "close", "last_price", "close_price", "last")
    prev_close = _bar_value(prev, "close", "last_price", "close_price", "last")
    if last is None or prev_close is None or prev_close == 0:
        return None

    open_p = _bar_value(today, "open", "open_price")
    high_p = _bar_value(today, "high", "high_price")
    low_p = _bar_value(today, "low", "low_price")
    amount = _bar_value(today, "amount") or 0.0
    volume = _bar_value(today, "volume", "vol", "total_hand") or 0.0

    change = last - prev_close
    change_pct = change / prev_close * 100
    open_pct = ((open_p - prev_close) / prev_close * 100) if open_p else 0.0
    high_pct = ((high_p - prev_close) / prev_close * 100) if high_p else 0.0
    low_pct = ((low_p - prev_close) / prev_close * 100) if low_p else 0.0
    amplitude_pct = ((high_p - low_p) / prev_close * 100) if (high_p and low_p) else 0.0

    return {
        "full_code": full_code,
        "name": name,
        "kind": kind,
        "last_price": last,
        "pre_close_price": prev_close,
        "change": change,
        "change_pct": round(change_pct, 4),
        "open_price": open_p,
        "open_pct": round(open_pct, 4),
        "high_price": high_p,
        "high_pct": round(high_pct, 4),
        "low_price": low_p,
        "low_pct": round(low_pct, 4),
        "amplitude_pct": round(amplitude_pct, 4),
        "amount": amount,
        "volume": volume,
        "trading_date": today.get("date") or today.get("timestamp"),
    }


def _sort_market_items(items: list[dict[str, Any]], sort_by: str = "涨幅", ascending: bool = False) -> list[dict[str, Any]]:
    field_map = {
        "代码": "full_code",
        "现价": "last_price",
        "涨幅": "change_pct",
        "open_pct": "open_pct",
        "振幅": "amplitude_pct",
        "成交额": "amount",
        "成交量": "volume",
    }
    field = field_map.get(sort_by, "change_pct")

    def _key(item: dict[str, Any]):
        value = item.get(field)
        if value is None:
            return (1, 0)  # 缺失值排最后
        return (0, value)

    return sorted(items, key=_key, reverse=not ascending)


# ---------------------------------------------------------------------------
# CategoryQuoteRecord → 字典
# ---------------------------------------------------------------------------


def _record_to_dict(record: Any) -> dict[str, Any]:
    """把 CategoryQuoteRecord（或任意 dataclass-like 对象）转成 dict。

    优先用对象自己的 ``__dataclass_fields__``（若有）；否则走 ``vars``。
    """
    if record is None:
        return {}
    if isinstance(record, dict):
        return dict(record)
    if hasattr(record, "__dataclass_fields__"):
        return _sanitize_jsonable(asdict(record))
    return _sanitize_jsonable(vars(record))


# ---------------------------------------------------------------------------
# theme_market N00X 字段翻译
# ---------------------------------------------------------------------------


NXX_FIELD_MAP: dict[str, str] = {
    "N001": "market",
    "N002": "sector_code",
    "N003": "sector_name",
    "N004": "change_pct",
    "N005": "limit_up_count",
    "N006": "limit_down_count",
    "N007": "leading_stock",
    "N008": "leading_change_pct",
    "N009": "open_change_pct",
    "N010": "max_change_pct",
    "N011": "amount",
    "N012": "total_hand",
    "N013": "turnover_rate",
    "N014": "amplitude_pct",
    "N015": "net_inflow",
    "N016": "main_inflow",
    "N017": "ranking",
    "N018": "trading_date",
}


def _translate_nxx_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[NXX_FIELD_MAP.get(str(key), str(key))] = value
    return out


# ---------------------------------------------------------------------------
# 适配器主体
# ---------------------------------------------------------------------------


class EltdxFundamentalsAdapter(FundamentalsAdapter):
    """F10 / 题材 / 行情数据源 - eltdx 实现。"""

    name = "eltdx"

    def __init__(self, client: TdxClient | None = None) -> None:
        self._client = client

    # -------- 生命周期 --------

    def _open_client(self) -> TdxClient:
        if self._client is not None:
            return self._client
        return _build_client()

    @staticmethod
    def _use_external_client() -> bool:
        config = get_stock_chart_config().get('f10', {})
        return bool(config.get('use_external_client'))

    def _resolve_f10(self, client: TdxClient):
        return client.f10

    # -------- 题材 / 概念 --------

    def get_topic_ids(self, symbol: str) -> list[str]:
        with self._open_client() as client:
            response = self._resolve_f10(client).topic_ids(symbol)
        ids: list[str] = []
        for row in _f10_rows(response):
            val = row.get("t001") or row.get("topic_id") or row.get("id")
            if val is None:
                continue
            ids.append(str(val))
        return ids

    def get_hot_topics(self, symbol: str, section: str = "zttzbkz") -> list[TopicInfo]:
        """热点题材（按 ``F10-热点题材.md`` 字段映射：id/ztmc/gld/rxsj/ztrq/ztnr/arec）。"""
        with self._open_client() as client:
            response = self._resolve_f10(client).hot_topics(symbol, section=section)
        topics: list[TopicInfo] = []
        for row in _f10_rows(response):
            topics.append(
                TopicInfo(
                    topic_id=str(row.get("id") or row.get("topic_id") or ""),
                    topic_name=str(row.get("ztmc") or row.get("topic_name") or ""),
                    relation_level=_coerce_int(row.get("gld") or row.get("relation_level")) or None,
                    selected_date=str(row.get("rxsj") or row.get("selected_date") or "") or None,
                    topic_date=str(row.get("ztrq") or row.get("topic_date") or "") or None,
                    reason=str(row.get("ztnr") or row.get("reason") or "") or None,
                    detail_id=str(row.get("arec") or row.get("detail_id") or "") or None,
                    source=str(row.get("source") or "CWServ.tdxf10_gg_rdtc") or None,
                )
            )
        return topics

    def get_topic_compare(
        self, symbol: str, topic_id: str, section: str = "gndbzfsj", sort_by: str = "zdf"
    ) -> TopicDetail:
        """题材内个股对比（按 ``F10-题材内对比.md`` 字段映射：pm/zqdm/zqjc/zdf/...）。"""
        with self._open_client() as client:
            response = self._resolve_f10(client).topic_compare(
                symbol, topic_id, section=section, sort_by=sort_by
            )
        rows = _f10_rows(response)
        stocks: list[TopicStock] = []
        topic_name = ""
        for row in rows:
            if not topic_name:
                # 题材名通常出现在 t002（hot_topics 同源） 或 topic_name 字段
                topic_name = str(row.get("topic_name") or row.get("t002") or "")
            stocks.append(
                TopicStock(
                    full_code=str(row.get("zqdm") or row.get("full_code") or ""),
                    name=str(row.get("zqjc") or row.get("name") or ""),
                    rank=_coerce_int(row.get("pm") or row.get("rank")) or None,
                    change_pct=_to_float(row.get("zdf") or row.get("change_pct")),
                    change_pct_3d=_to_float(row.get("zdf_3d") or row.get("change_pct_3d")),
                    change_pct_5d=_to_float(row.get("zdf_5d") or row.get("change_pct_5d")),
                    change_pct_20d=_to_float(row.get("zdf_20d") or row.get("change_pct_20d")),
                    change_pct_60d=_to_float(row.get("zdf_60d") or row.get("change_pct_60d")),
                    change_pct_ytd=_to_float(row.get("zdf_ys") or row.get("change_pct_ytd")),
                    trading_date=str(row.get("tjdate") or row.get("trading_date") or "") or None,
                )
            )
        return TopicDetail(
            topic_id=str(topic_id),
            topic_name=topic_name,
            seed_code=str(symbol),
            stocks=stocks,
            raw=_f10_to_dict(response),
        )

    def get_stock_topics_combined(self, symbol: str) -> StockTopicsCombined:
        """合并 topic_ids + hot_topics（通过 ``helpers.stock_topics``）。

        eltdx 的 helpers 内部已经做了：
        - 调用 ``topic_ids`` 拿到全量题材 ID；
        - 调用 ``hot_topics`` 拿到带可读名的题材条目；
        - 把 topic_name 合并进 topic_ids 输出。
        """
        with self._open_client() as client:
            result = client.helpers.stock_topics(stock_symbol_to_eltdx_code(symbol))
        topics: list[TopicInfo] = []
        for t in getattr(result, "topics", []) or []:
            topics.append(
                TopicInfo(
                    topic_id=str(getattr(t, "topic_id", "") or ""),
                    topic_name=str(getattr(t, "topic_name", "") or ""),
                    relation_level=_coerce_int(getattr(t, "relation_level", None)) or None,
                    selected_date=str(getattr(t, "selected_date", "") or "") or None,
                    topic_date=str(getattr(t, "topic_date", "") or "") or None,
                    reason=str(getattr(t, "reason", "") or "") or None,
                    detail_id=str(getattr(t, "detail_id", "") or "") or None,
                    source=str(getattr(t, "source", "") or "helpers.stock_topics") or None,
                )
            )
        return StockTopicsCombined(
            symbol=str(symbol),
            topics=topics,
            count=int(getattr(result, "count", 0) or len(topics)),
        )

    def list_sectors_market(
        self,
        category: str,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        """按分类拉板块 / 个股行情。``category`` 可以是 ``"沪深A股"`` /
        行业 / 概念板块分类名或数字分类编号。"""
        category_id = _normalize_category_id(category)
        with self._open_client() as client:
            page = client.quotes.list_by_category(
                category_id,
                sort_by=sort_by,
                start=start,
                count=count,
                ascending=ascending,
            )
        items = [_sanitize_jsonable(_record_to_dict(rec)) for rec in (getattr(page, "records", None) or [])]
        return SectorMarket(
            category=str(category_id),
            sort_by=str(sort_by),
            ascending=bool(ascending),
            total=int(getattr(page, "count", 0) or len(items)),
            items=items,
        )

    def get_theme_market(self, symbol: str, req_id: str = "200743") -> ThemeMarket:
        """题材概念行情（HQServ.hq_nlp_tcihq 复合响应）。

        F10-题材概念行情.md 中 table0 是回显，table1 是相关板块列表，
        table2 / 后续是成分股等。``tables[1].rows`` 行内字段为 ``N001..N00X``。
        这里把 ``tables`` 整体暴露给上层（``sections``），并把 ``N00X`` 翻译成可读名。
        """
        with self._open_client() as client:
            response = self._resolve_f10(client).theme_market(symbol, req_id=req_id)
        raw = _f10_to_dict(response)
        tables = raw.get("tables") or raw.get("ResultSets") or []
        sections: dict[str, list[dict[str, Any]]] = {}
        for idx, table in enumerate(tables):
            key = str(table.get("Key") or table.get("key") or f"table{idx}")
            rows_raw = table.get("Data") or table.get("rows") or []
            rows = _sanitize_jsonable(rows_raw)
            # 若行是 N00X 命名空间，翻译成可读名
            if rows and any(isinstance(r, dict) and any(str(k).startswith("N00") for k in r.keys()) for r in rows):
                rows = [_translate_nxx_row(r) for r in rows]
            sections[key] = rows
        return ThemeMarket(
            symbol=str(symbol),
            req_id=str(req_id),
            sections=sections,
            raw=raw,
        )

    # -------- 行业 / 概念 指数 K-line 行情 --------

    def get_industry_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        """拉取所有行业指数的当日行情（申万 32 个行业）。"""
        return self._get_index_codes_market(
            INDUSTRY_INDEX_CODES, kind="industry",
            sort_by=sort_by, count=count, ascending=ascending, start=start,
        )

    def get_concept_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        """拉取所有概念主题指数的当日行情。"""
        return self._get_index_codes_market(
            CONCEPT_INDEX_CODES, kind="concept",
            sort_by=sort_by, count=count, ascending=ascending, start=start,
        )

    def _get_index_codes_market(
        self,
        codes: list[tuple[str, str]],
        kind: str,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        items: list[dict[str, Any]] = []
        with self._open_client() as client:
            for full_code, name in codes:
                try:
                    bars = self._fetch_index_bars(client, full_code)
                except Exception:
                    continue
                if not bars:
                    continue
                market = _bars_to_index_market(full_code, name, kind, bars)
                if market is not None:
                    items.append(market)

        items = _sort_market_items(items, sort_by=sort_by, ascending=ascending)
        total = len(items)
        page = items[start:start + count]
        return SectorMarket(
            category=kind,
            sort_by=str(sort_by),
            ascending=bool(ascending),
            total=total,
            items=page,
        )

    @staticmethod
    def _fetch_index_bars(client: Any, full_code: str) -> list[dict[str, Any]]:
        """拉指数 K 线（多种 kind 兜底）。"""
        last_exc: Exception | None = None
        # 优先 kind=None（最稳），再 index，再 sector
        for kind in (None, "index", "sector"):
            try:
                kwargs: dict[str, Any] = {"period": "1d", "count": 2}
                if kind is not None:
                    kwargs["kind"] = kind
                result = client.bars.get(full_code, **kwargs)
                items = (
                    getattr(result, "items", None)
                    or getattr(result, "bars", None)
                    or list(result or [])
                )
                out: list[dict[str, Any]] = []
                for bar in items:
                    out.append(_record_to_dict(bar))
                if out:
                    return out
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return []

    # -------- 涨停跌停 / 换手率 --------

    def count_limit_up_down(
        self,
        *,
        category: str = "沪深A股",
        max_pages: int = 80,
        threshold_overrides: dict[str, float] | None = None,
        trade_date: str | None = None,
    ) -> LimitUpDownCount:
        """分页拉 ``list_by_category`` 涨跌幅榜，直到涨幅不再 ≥ 阈值。"""
        up = down = flat = limit_up = limit_down = total = 0
        page_size = 80
        stop_up = stop_down = False

        with self._open_client() as client:
            # 上涨榜：按涨幅降序拉到 < 阈值为止
            start = 0
            while start // page_size < max_pages and not stop_up:
                page = client.quotes.list_by_category(category, sort_by="涨幅", start=start, count=page_size, ascending=False)
                records = list(getattr(page, "records", []) or [])
                if not records:
                    break
                for record in records:
                    bucket, _ = _classify_record(record, threshold_overrides)
                    if bucket == "limit_up":
                        limit_up += 1
                    elif bucket == "up":
                        stop_up = True  # 涨跌幅已跌破涨停阈值，本页之后全是 up
                        break
                    else:
                        stop_up = True
                        break
                if len(records) < page_size:
                    break
                start += page_size

            # 下跌榜：按跌幅升序
            start = 0
            while start // page_size < max_pages and not stop_down:
                page = client.quotes.list_by_category(category, sort_by="涨幅", start=start, count=page_size, ascending=True)
                records = list(getattr(page, "records", []) or [])
                if not records:
                    break
                for record in records:
                    bucket, _ = _classify_record(record, threshold_overrides)
                    if bucket == "limit_down":
                        limit_down += 1
                    elif bucket == "down":
                        stop_down = True
                        break
                    else:
                        stop_down = True
                        break
                if len(records) < page_size:
                    break
                start += page_size

            # 全量总家数：只取首页 size 推断或通过 codes.count 拿
            try:
                sz_count = client.codes.count("sz") or 0
                sh_count = client.codes.count("sh") or 0
                bj_count = client.codes.count("bj") or 0
                total = (sz_count or 0) + (sh_count or 0) + (bj_count or 0)
            except Exception:
                total = 0

        up += limit_up
        down += limit_down

        return LimitUpDownCount(
            trade_date=trade_date or _safe_trade_date(None).isoformat(),
            up_count=up,
            down_count=down,
            flat_count=flat,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            total_count=total,
            source=self.name,
        )

    def compute_turnover_rate_series(
        self,
        symbol: str,
        target_type: str,
        period: str = "1d",
        adjust: str = "qfq",
    ) -> TurnoverRateSeries:
        from backend.services.stock.kline_service import resolve_stock_klines
        from backend.services.stock.sample_data_service import sample_stock_klines

        items, _ = resolve_stock_klines(target_type, symbol, period, adjust, sample_stock_klines)
        circulating_shares, total_shares = self._lookup_shares(symbol)

        entries: list[TurnoverRateEntry] = []
        for bar in items:
            volume = float(bar.get("volume") or 0)
            amount = float(bar.get("amount") or bar.get("turnover") or 0)
            timestamp = int(bar.get("timestamp") or 0)
            trade_date = str(bar.get("trade_date") or bar.get("date") or "").strip() or None
            if not trade_date and timestamp > 0:
                trade_date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
            turnover_rate = self._estimate_turnover_rate(volume, amount, circulating_shares)
            entries.append(
                TurnoverRateEntry(
                    trade_date=trade_date,
                    timestamp=timestamp,
                    turnover_rate=turnover_rate,
                    volume=volume,
                    amount=amount,
                    circulating_shares=circulating_shares,
                )
            )

        return TurnoverRateSeries(
            symbol=symbol,
            target_type=target_type,
            period=period,
            adjust=adjust,
            circulating_shares=circulating_shares,
            total_shares=total_shares,
            source=self.name,
            entries=entries,
        )

    def _lookup_shares(self, symbol: str) -> tuple[float | None, float | None]:
        """取流通股本 + 总股本（单位：股）。

        走 ``client.helpers.stock_profile_table(full_code)``，从 ``rows[0]`` 里拿
        ``circulating_shares / total_shares``（单位：股）。

        ⚠️ ``client.f10.stock_info()`` 的真实字段只有 ``T002 / T003 / sc``，**没有**股本字段。
        """
        try:
            full_code = stock_symbol_to_eltdx_code(symbol)
            with self._open_client() as client:
                table = client.helpers.stock_profile_table(full_code)
            rows = getattr(table, "rows", None) or ()
            profile = rows[0] if rows else None
            circulating = getattr(profile, "circulating_shares", None)
            total = getattr(profile, "total_shares", None)
            return circulating, total
        except Exception:
            return None, None

    @staticmethod
    def _estimate_turnover_rate(volume: float, amount: float, circulating_shares: float | None) -> float:
        """换手率 = volume(手) × 100 / circulating_shares(股) × 100%

        与 eltdx helpers._turnover_rate 同口径：
            volume_hand * 100.0 / circulating_shares * 100.0
        """
        if not volume or not circulating_shares:
            return 0.0
        return round(volume * 10000.0 / circulating_shares, 4)

    # -------- F10 基础 --------

    def get_stock_info(self, symbol: str) -> StockInfo:
        with self._open_client() as client:
            response = self._resolve_f10(client).stock_info(symbol)
        return StockInfo(symbol=str(symbol), raw=_f10_to_dict(response))

    def get_company_profile(self, symbol: str, section: str = "8") -> CompanyProfile:
        with self._open_client() as client:
            response = self._resolve_f10(client).company_profile(symbol, section=section)
        return CompanyProfile(
            symbol=str(symbol),
            section=str(section),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_business_composition(
        self, symbol: str, report_date: str | None = None
    ) -> BusinessComposition:
        with self._open_client() as client:
            response = self._resolve_f10(client).business_composition(symbol, report_date=report_date)
        rows = _f10_rows(response)
        selected_date = report_date
        for row in rows:
            if selected_date is None:
                selected_date = str(row.get("t002") or row.get("report_date") or "") or None
            else:
                break
        return BusinessComposition(
            symbol=str(symbol),
            report_date=selected_date,
            rows=rows,
            raw=_f10_to_dict(response),
        )

    # -------- F10 财务 / 估值 --------

    def get_valuation(self, symbol: str, req_id: str = "200191") -> Valuation:
        with self._open_client() as client:
            response = self._resolve_f10(client).valuation(symbol, req_id=req_id)
        return Valuation(
            symbol=str(symbol),
            req_id=str(req_id),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_finance_report(self, symbol: str, report_type: str = "zcfzb") -> FinanceReport:
        with self._open_client() as client:
            response = self._resolve_f10(client).finance_report(symbol, report_type=report_type)
        return FinanceReport(
            symbol=str(symbol),
            report_type=str(report_type),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_finance_diagnosis(self, symbol: str, section: str = "yynl") -> FinanceDiagnosis:
        with self._open_client() as client:
            response = self._resolve_f10(client).finance_diagnosis(symbol, section=section)
        return FinanceDiagnosis(
            symbol=str(symbol),
            section=str(section),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_stock_score(self, symbol: str, section: str = "pf") -> StockScore:
        with self._open_client() as client:
            response = self._resolve_f10(client).stock_score(symbol, section=section)
        return StockScore(
            symbol=str(symbol),
            section=str(section),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_profit_forecast(self, symbol: str) -> ProfitForecast:
        with self._open_client() as client:
            response = self._resolve_f10(client).profit_forecast(symbol)
        return ProfitForecast(
            symbol=str(symbol),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    # -------- F10 排名 / 治理 --------

    def get_ranking_detail(self, symbol: str, section: str = "scpmdela") -> RankingDetail:
        with self._open_client() as client:
            response = self._resolve_f10(client).ranking_detail(symbol, section=section)
        return RankingDetail(
            symbol=str(symbol),
            section=str(section),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    def get_governance(self, symbol: str, section: str = "wgcl") -> Governance:
        with self._open_client() as client:
            response = self._resolve_f10(client).governance(symbol, section=section)
        return Governance(
            symbol=str(symbol),
            section=str(section),
            rows=_f10_rows(response),
            raw=_f10_to_dict(response),
        )

    # -------- 公告 / 新闻 / 路演 / 研报 (eltdx 1.0+) --------

    def get_announcements(self, symbol: str) -> Announcements:
        """个股公告列表 (CWSearch.tzx_rcache announcements)。

        eltdx 返回的 tables[0] 是已结构化的 dict 行 (列名见 schemas.AnnouncementItem)。
        """
        with self._open_client() as client:
            response = self._resolve_f10(client).announcements(symbol)
        items = self._parse_table_rows(
            response,
            lambda row: AnnouncementItem(
                issue_date=_s(row, "issue_date"),
                title=_s(row, "title"),
                typecode=_s(row, "typecode"),
                typename=_s(row, "typename"),
                rec_id=_s(row, "rec_id"),
                tableid=_s(row, "tableid"),
                url=_s(row, "url"),
                redistime=_s(row, "redistime"),
                source=_s(row, "source"),
            ),
        )
        return Announcements(
            symbol=str(symbol),
            items=items,
            raw=_f10_to_dict(response),
        )

    def get_news(self, symbol: str) -> NewsList:
        """个股新闻列表 (CWSearch.tzx_rcache news)。"""
        with self._open_client() as client:
            response = self._resolve_f10(client).news(symbol)
        items = self._parse_table_rows(
            response,
            lambda row: NewsItem(
                issue_date=_s(row, "issue_date"),
                title=_s(row, "title"),
                rec_id=_s(row, "rec_id"),
                tableid=_s(row, "tableid"),
                redistime=_s(row, "redistime"),
                source=_s(row, "source"),
                relatecolumn=_s(row, "relatecolumn"),
            ),
        )
        return NewsList(
            symbol=str(symbol),
            items=items,
            raw=_f10_to_dict(response),
        )

    def get_roadshows(self, symbol: str) -> Roadshows:
        """路演 / 业绩说明会列表 (CWSearch.tzx_rcache roadshows)。"""
        with self._open_client() as client:
            response = self._resolve_f10(client).roadshows(symbol)
        items = self._parse_table_rows(
            response,
            lambda row: RoadshowItem(
                title=_s(row, "title"),
                roadshow_type=_s(row, "roadshow_type"),
                start_date=_s(row, "start_date"),
                start_time=_s(row, "start_time"),
                end_time=_s(row, "end_time"),
                summary=_s(row, "summary"),
                url=_s(row, "url"),
            ),
        )
        return Roadshows(
            symbol=str(symbol),
            items=items,
            raw=_f10_to_dict(response),
        )

    def get_company_news(self, symbol: str, section: str = "gsyj") -> CompanyNews:
        """公司研报 / 监管措施 (CWServ.tdxf10_gg_gszx, 默认 section='gsyj')。

        eltdx 返回的是 raw T0xx 列, 用 T004 (评级) / T009 (分析师) /
        T011 (rec_id) / T012 (日期) / T039 (标题) / nflag / ybdz 提取。
        """
        with self._open_client() as client:
            response = self._resolve_f10(client).company_news(symbol, section=section)

        def _map(row: dict[str, Any]) -> CompanyNewsItem:
            return CompanyNewsItem(
                rating=_s(row, "T004"),
                analysts=_s(row, "T009"),
                rec_id=_s(row, "T011"),
                issue_date=_s(row, "T012"),
                title=_s(row, "T039"),
                nflag=_s(row, "nflag"),
                doc_hash=_s(row, "ybdz"),
            )

        items = self._parse_table_rows(response, _map)
        return CompanyNews(
            symbol=str(symbol),
            section=str(section),
            items=items,
            raw=_f10_to_dict(response),
        )

    def _parse_table_rows(self, response: Any, mapper: Any) -> list[Any]:
        """把 F10Response.tables[*].rows 解析为 dataclass item 列表。

        跳过空 title (避免公告/新闻接口偶尔返回的占位空行)。
        """
        out: list[Any] = []
        if response is None:
            return out
        tables = getattr(response, "tables", None) or []
        for tbl in tables:
            rows = getattr(tbl, "rows", None) or []
            for row in rows:
                item = mapper(row)
                # 通用兜底: title 字段为空就跳过
                title = getattr(item, "title", None)
                if not title:
                    continue
                out.append(item)
        return out

    # -------- 健康检查 --------

    def ping(self) -> dict[str, Any]:
        try:
            with self._open_client() as client:
                quotes = client.quotes.list_by_category("沪深A股", sort_by="涨幅", start=0, count=1)
            return {"source": self.name, "ok": True, "records": len(getattr(quotes, "records", []) or [])}
        except Exception as exc:  # pragma: no cover - 健康检查兜底
            return {"source": self.name, "ok": False, "error": str(exc)}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
