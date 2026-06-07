"""通达信 56 个行业指数 (8803XX 系列) 行情服务.

设计目标:
- 8803XX → ``sh/sz/bj`` 前缀不能写死, 先反查.
- 提供单点 / 批量实时快照 + K 线能力.
- 跟 heatmap / 行业页共用, 不引入 pandas / openpyxl 等重依赖.

eltdx v1.0.2 实测:
- ``client.get_index_codes_all()`` 返回 ``[sh881478, ...]`` 1678 项, 56 个行业
  指数全部命中, 前缀都是 ``sh``.
- ``client.get_quote([codes])`` 返回 ``QuoteSnapshot`` 列表, 字段:
  ``full_code / code / exchange / last_price / pre_close_price / open_price /
  high_price / low_price / change / change_pct / amount / total_hand /
  current_hand``.
- ``client.bars.get(code, period="day", count=N)`` 返回 K 线; v1.0.2 对指数
  日 K 偶发协议错 (invalid kline date), 走 try/except 兜底, 失败返回空 bars.

模块入口:
- :func:`resolve_full_codes`        : 8803XX → sh/sz/bj + name 映射
- :func:`fetch_industry_snapshots`  : 56 个行业实时快照
- :func:`fetch_industry_snapshot`   : 单个行业实时快照
- :func:`fetch_industry_kline`      : 单个行业 K 线
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Final

from .tdx_industry_codes import (
    LABEL,
    KIND,
    TDX_INDUSTRY_56,
    get_tdx_industry_56,
    get_tdx_industry_name,
)

logger = logging.getLogger(__name__)

# 优先级: sh > sz > bj (88 系列几乎都在 sh, 兼容防御)
_FULL_CODE_PROBE_MARKETS: Final[list[str]] = ["sh", "sz", "bj"]
_QUOTE_BATCH: Final[int] = 20  # eltdx get_quote 一次性 20 个稳


# ---------------------------------------------------------------------------
# client 复用 (与 f10 体系一致, 单 client + pool_size 多路复用)
# ---------------------------------------------------------------------------
_client_lock = threading.Lock()
_client = None


def _get_client():
    """复用单 client, 跨进程安全."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from backend.adapters.market.eltdx_adapter import _build_client  # noqa: WPS433
            _client = _build_client()
            _client.connect()
    return _client


def reset_client() -> None:
    """测试用, 强制重新 connect."""
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = None


# ---------------------------------------------------------------------------
# full_code 反查
# ---------------------------------------------------------------------------
_index_cache_lock = threading.Lock()
_index_cache: dict[str, str] | None = None  # code6 -> full_code


def _index_full_codes() -> dict[str, str]:
    """拉取 eltdx 全量指数代码表, 解析成 ``{880471: sh880471}``.

    缓存到进程内, 与 ``_client`` 同生命周期.
    """
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    with _index_cache_lock:
        if _index_cache is not None:
            return _index_cache
        client = _get_client()
        out: dict[str, str] = {}
        for full in client.get_index_codes_all() or []:
            raw = str(full or "").strip().lower()
            if not raw:
                continue
            for prefix in _FULL_CODE_PROBE_MARKETS:
                if raw.startswith(prefix):
                    code6 = raw[len(prefix):]
                    if code6 and code6 not in out:  # 同名 code6 第一次命中为准
                        out[code6] = raw
                    break
        _index_cache = out
        logger.info("tdx_industry index cache: %d full_codes", len(out))
        return _index_cache


def reset_index_cache() -> None:
    global _index_cache
    with _index_cache_lock:
        _index_cache = None


def resolve_full_codes(
    mapping: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """从 TDX 指数代码表里反查 ``880xxx`` 的 full_code.

    Args:
        mapping: ``{880471: 银行, ...}``, 默认用 :data:`TDX_INDUSTRY_56`.

    Returns:
        ``{880471: {name, full_code, exchange, tdx_name}, ...}``
    """
    mapping = mapping or TDX_INDUSTRY_56
    code_to_full = _index_full_codes()
    out: dict[str, dict[str, Any]] = {}
    for code6, name in mapping.items():
        full = code_to_full.get(str(code6))
        if not full:
            continue
        out[str(code6)] = {
            "name": str(name),
            "full_code": full,
            "exchange": full[:2] if len(full) >= 2 else "",
        }
    return out


# ---------------------------------------------------------------------------
# 行情 → dict
# ---------------------------------------------------------------------------
def _quote_to_row(q: Any) -> dict[str, Any]:
    """eltdx QuoteSnapshot → JSON-friendly dict. 缺字段为 None."""
    if q is None:
        return {}
    return {
        "full_code": getattr(q, "full_code", None),
        "code": getattr(q, "code", None),
        "exchange": getattr(q, "exchange", None),
        "last_price": getattr(q, "last_price", None),
        "pre_close_price": getattr(q, "pre_close_price", None),
        "open_price": getattr(q, "open_price", None),
        "high_price": getattr(q, "high_price", None),
        "low_price": getattr(q, "low_price", None),
        "change": getattr(q, "change", None),
        "change_pct": getattr(q, "change_pct", None),
        "amount": getattr(q, "amount", None),
        "total_hand": getattr(q, "total_hand", None),
        "current_hand": getattr(q, "current_hand", None),
        "open_amount_yuan": getattr(q, "open_amount_yuan", None),
    }


def _batched(xs: list, size: int) -> list[list]:
    return [xs[i:i + size] for i in range(0, len(xs), size)]


def fetch_industry_snapshots(
    mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """批量拉全量行业指数的实时快照.

    Returns:
        list of dict, 每项含 ``code6 / name / full_code / last_price /
        pre_close_price / open_price / high_price / low_price / change /
        change_pct / amount / total_hand``.

        按 ``change_pct`` 降序, 缺值排最后.
    """
    resolved = resolve_full_codes(mapping)
    if not resolved:
        raise RuntimeError(
            "没有在 eltdx 全量指数代码表里找到 8803XX 行业指数, "
            "可能当前主站不返回板块指数, 或 client 离线"
        )
    full_codes = [v["full_code"] for v in resolved.values()]
    client = _get_client()

    quotes_by_full: dict[str, Any] = {}
    for chunk in _batched(full_codes, _QUOTE_BATCH):
        try:
            qs = client.get_quote(chunk) or []
        except Exception as exc:
            logger.warning("get_quote failed for %s: %s", chunk, exc)
            continue
        for q in qs:
            quotes_by_full[getattr(q, "full_code", "")] = q

    rows: list[dict[str, Any]] = []
    for code6, info in resolved.items():
        q = quotes_by_full.get(info["full_code"])
        if not q:
            continue
        row = _quote_to_row(q)
        row["code6"] = code6
        row["name"] = info["name"]
        rows.append(row)

    rows.sort(key=lambda r: (r.get("change_pct") is None, -(r.get("change_pct") or 0.0)))
    return rows


def fetch_industry_snapshot(code6: str) -> dict[str, Any] | None:
    """单行业快照, ``code6`` 支持 ``880471`` / ``sh880471`` 两种."""
    if not code6:
        return None
    raw = str(code6).strip().lower()
    if not raw:
        return None
    if not raw[:2] in _FULL_CODE_PROBE_MARKETS:
        code6_key = raw
        full = _index_full_codes().get(code6_key)
        if not full:
            return None
    else:
        full = raw
        code6_key = raw[2:]

    client = _get_client()
    try:
        qs = client.get_quote([full]) or []
    except Exception as exc:
        logger.warning("get_quote failed for %s: %s", full, exc)
        return None
    if not qs:
        return None
    row = _quote_to_row(qs[0])
    row["code6"] = code6_key
    row["name"] = get_tdx_industry_name(code6_key) or code6_key
    return row


def fetch_industry_kline(
    code6: str,
    *,
    period: str = "day",
    count: int = 120,
) -> list[dict[str, Any]]:
    """单行业 K 线. v1.0.2 对指数日 K 偶发协议错, 走 try/except 兜底.

    Returns:
        list of ``{time, open, high, low, close, volume_lots, amount}``.
        拉取失败时返回空列表, 调用方自行降级.
    """
    if not code6:
        return []
    raw = str(code6).strip().lower()
    if not raw:
        return []
    if raw[:2] not in _FULL_CODE_PROBE_MARKETS:
        full = _index_full_codes().get(raw)
        if not full:
            return []
    else:
        full = raw

    client = _get_client()
    try:
        series = client.bars.get(full, period=period, count=count)
    except Exception as exc:
        logger.warning("bars.get failed for %s period=%s: %s", full, period, exc)
        return []

    out: list[dict[str, Any]] = []
    for b in (getattr(series, "bars", None) or []):
        out.append({
            "time": getattr(b, "time", None),
            "open": getattr(b, "open", None),
            "high": getattr(b, "high", None),
            "low": getattr(b, "low", None),
            "close": getattr(b, "close", None),
            "volume_lots": getattr(b, "volume_lots", None),
            "amount": getattr(b, "amount", None),
            "up_count": getattr(b, "up_count", None),
            "down_count": getattr(b, "down_count", None),
        })
    return out


# ---------------------------------------------------------------------------
# 顶层便捷: 一次拿齐所有行业 (dict 形式, 方便 heatmap 直接消费)
# ---------------------------------------------------------------------------
def build_industry_market_payload() -> dict[str, Any]:
    """返回 ``{kind, label, fetchedAt, items: [...]}``, 与 heatmap 板块结构兼容.

    每项 fields:
      ``code6 / name / full_code / last_price / pre_close_price / change /
      change_pct / amount / total_hand / volume / open_price / high_price /
      low_price / kind='industries' / sectorCode='TDX_INDUSTRY_56'``.
    """
    from datetime import datetime
    rows = fetch_industry_snapshots()
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append({
            "code6": r.get("code6"),
            "name": r.get("name"),
            "fullCode": r.get("full_code"),
            "latestPrice": r.get("last_price"),
            "preClosePrice": r.get("pre_close_price"),
            "openPrice": r.get("open_price"),
            "highPrice": r.get("high_price"),
            "lowPrice": r.get("low_price"),
            "change": r.get("change"),
            "changePercent": r.get("change_pct"),
            "amount": r.get("amount"),
            "volume": r.get("total_hand"),
            "turnoverRate": None,
            "kind": KIND,
            "sectorCode": r.get("full_code"),
            "sectorName": r.get("name"),
        })
    return {
        "kind": KIND,
        "label": LABEL,
        "count": len(items),
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "source": "eltdx.get_index_codes_all + get_quote",
    }
