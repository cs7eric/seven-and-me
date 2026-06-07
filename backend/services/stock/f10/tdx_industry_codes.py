"""通达信 56 个行业指数 (8803XX 系列) 的只读封装.

数据源持久化在 ``reference/stock-universe/tdx_industry_56.json``,
这里只暴露只读 API, 不写盘. 写盘用
:func:`refresh_tdx_industry_56_from_constants` 或直接改 JSON.

约定:
- JSON 的 ``items`` 字段是 ``{code6: name}`` 映射, code 形如 ``880301``.
- 内部使用全名 (``sh880301``) 作为 key, 方便和 eltdx bars / quote 接口直接对接.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Final

from backend.config.settings import STOCK_UNIVERSE_DIR

logger = logging.getLogger(__name__)

TDX_INDUSTRY_56_FILE: Final[Path] = STOCK_UNIVERSE_DIR / "tdx_industry_56.json"
TDX_INDUSTRY_56_PREFIX: Final[str] = "sh"

# 与 index.json / sectors 体系保持一致, 默认 "industries" 走的就是这 56 个行业
KIND: Final[str] = "industries"
LABEL: Final[str] = "行业"


# 进程级缓存 (JSON 不大, 一次加载常驻内存即可)
_lock = threading.Lock()
_loaded: dict[str, str] | None = None
_meta: dict[str, Any] | None = None


def _load_locked() -> tuple[dict[str, str], dict[str, Any]]:
    global _loaded, _meta
    if _loaded is not None and _meta is not None:
        return _loaded, _meta
    if not TDX_INDUSTRY_56_FILE.exists():
        logger.warning("tdx_industry_56.json not found at %s", TDX_INDUSTRY_56_FILE)
        _loaded, _meta = {}, {"source": "missing", "version": 0, "updatedAt": None}
        return _loaded, _meta
    try:
        blob = json.loads(TDX_INDUSTRY_56_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("tdx_industry_56.json read failed: %s", exc)
        _loaded, _meta = {}, {"source": "broken", "version": 0, "updatedAt": None}
        return _loaded, _meta

    items = blob.get("items") or {}
    if not isinstance(items, dict):
        items = {}

    prefix = str(blob.get("prefix") or TDX_INDUSTRY_56_PREFIX).lower()
    out: dict[str, str] = {}
    for code6, name in items.items():
        code6 = str(code6 or "").strip()
        name = str(name or "").strip()
        if not code6 or not name:
            continue
        out[f"{prefix}{code6}"] = name
    _loaded = out
    _meta = {
        "source": blob.get("source"),
        "version": blob.get("version"),
        "updatedAt": blob.get("updatedAt"),
        "count": len(out),
        "file": str(TDX_INDUSTRY_56_FILE),
    }
    return _loaded, _meta


def reset_cache() -> None:
    """测试 / 写盘后清空内存缓存, 强制重新读 JSON."""
    global _loaded, _meta
    with _lock:
        _loaded = None
        _meta = None


# ---------------------------------------------------------------------------
# 只读 API
# ---------------------------------------------------------------------------
def get_tdx_industry_56() -> dict[str, str]:
    """返回 ``{sh880301: 煤炭, sh880305: 电力, ...}`` 全量映射."""
    with _lock:
        loaded, _ = _load_locked()
        return dict(loaded)


def get_tdx_industry_56_meta() -> dict[str, Any]:
    """返回元信息 (source / version / updatedAt / count / file)."""
    with _lock:
        _, meta = _load_locked()
        return dict(meta)


def get_tdx_industry_56_pairs() -> list[tuple[str, str]]:
    """返回 ``[(sh880301, 煤炭), ...]`` 列表, 顺序与 JSON 一致."""
    with _lock:
        loaded, _ = _load_locked()
        return list(loaded.items())


def get_tdx_industry_56_names() -> list[str]:
    """仅返回名称列表."""
    with _lock:
        loaded, _ = _load_locked()
        return list(loaded.values())


def get_tdx_industry_name(code6_or_full: str) -> str | None:
    """按 ``880301`` / ``sh880301`` 查行业名. 找不到返回 None."""
    if not code6_or_full:
        return None
    raw = str(code6_or_full).strip().lower()
    if not raw:
        return None
    full = raw if raw.startswith(TDX_INDUSTRY_56_PREFIX) else f"{TDX_INDUSTRY_56_PREFIX}{raw}"
    with _lock:
        loaded, _ = _load_locked()
        return loaded.get(full)


# ---------------------------------------------------------------------------
# 写盘 API (供运维 / 脚本同步 in-code 字典到 JSON)
# ---------------------------------------------------------------------------
TDX_INDUSTRY_56: Final[dict[str, str]] = {
    "880301": "煤炭",
    "880305": "电力",
    "880310": "石油",
    "880318": "钢铁",
    "880324": "有色",
    "880330": "化纤",
    "880335": "化工",
    "880344": "建材",
    "880350": "造纸",
    "880351": "矿物制品",
    "880355": "日用化工",
    "880360": "农林牧渔",
    "880367": "纺织服饰",
    "880372": "食品饮料",
    "880380": "酿酒",
    "880387": "家用电器",
    "880390": "汽车类",
    "880398": "医疗保健",
    "880399": "家居用品",
    "880400": "医药",
    "880406": "商业连锁",
    "880414": "商贸代理",
    "880418": "传媒娱乐",
    "880421": "广告包装",
    "880422": "文教休闲",
    "880423": "酒店餐饮",
    "880424": "旅游",
    "880430": "航空",
    "880431": "船舶",
    "880432": "运输设备",
    "880437": "通用机械",
    "880440": "工业机械",
    "880446": "电气设备",
    "880447": "工程机械",
    "880448": "电器仪表",
    "880452": "电信运营",
    "880453": "公共交通",
    "880454": "水务",
    "880455": "供气供热",
    "880456": "环境保护",
    "880459": "运输服务",
    "880464": "仓储物流",
    "880465": "交通设施",
    "880471": "银行",
    "880472": "证券",
    "880473": "保险",
    "880474": "多元金融",
    "880476": "建筑",
    "880482": "房地产",
    "880489": "IT设备",
    "880490": "通信设备",
    "880491": "半导体",
    "880492": "元器件",
    "880493": "软件服务",
    "880494": "互联网",
    "880497": "综合类",
}


def refresh_tdx_industry_56_from_constants(
    *,
    source: str = "TDX 行业指数 56 分类 (8803XX 系列)",
    version: int = 1,
) -> dict[str, Any]:
    """把上面 :data:`TDX_INDUSTRY_56` 字典写回 JSON. 仅在 JSON 缺失或需要批量更新时调用.

    返回写入的元信息.
    """
    TDX_INDUSTRY_56_FILE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    blob = {
        "source": source,
        "version": version,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "prefix": TDX_INDUSTRY_56_PREFIX,
        "items": dict(TDX_INDUSTRY_56),
    }
    tmp = TDX_INDUSTRY_56_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=2)
    tmp.replace(TDX_INDUSTRY_56_FILE)
    reset_cache()
    return {"file": str(TDX_INDUSTRY_56_FILE), "count": len(TDX_INDUSTRY_56), **blob}
