"""
A 股"股票 ↔ 行业板块 / 概念板块"映射服务.

每日 17:00 (盘后) 拉一次, 落盘两类数据:
  1. ``reference/stock-universe/YYYY-MM-DD.json`` —— 当日全量快照
     { "stocks":[{code, name, industry, topics[]}], "trading_day":..., "version": 2 }
  2. ``reference/stock-universe/sectors/`` —— 按 category_raw 拆分的板块字典
     - sectors/index.json    : 所有 category 概况
     - sectors_industries_0.json : 行业板块 (cat=0)
     - sectors_concepts_2.json   : 概念板块 (cat=2)
     - sectors_styles_4.json     : 风格板块 (cat=4)
     - 未来 eltdx 加新 cat (1/3/5/6...) 自动识别, 写 sectors_cat_<n>.json

数据流:
  refresh()
    -> 拉 5530 + 题材, 写 per-day JSON
    -> 调 save_sectors_index() 动态按 category_raw 拆成多个文件

Hotpath API:
  list_categories() / list_sectors_by_category(raw) / get_sector_stocks(raw, name=, topic_id=)
  find_sectors_for(code, category_raw=None) / find_industries_for(code) / find_concepts_for(code)
  load_sectors_index() / load_category(raw)

CLI: ``python -m backend.scripts.refresh_stock_universe``
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from backend.config.settings import STOCK_UNIVERSE_DIR, STOCK_UNIVERSE_INDEX_FILE

logger = logging.getLogger(__name__)

# 拉取并发: 写死 64 worker 激进并发, 走多轮重试拿全数据.
# TQLEX 网关经常 502 限流吞请求, 多轮重试补齐失败 code.
# 关键: 每轮 round 用不同 host + 短超时, 防止 IP 限流累积.
DEFAULT_WORKERS = 64
DEFAULT_POOL_SIZE = 8
MAX_RETRY_ROUNDS = 8  # 最多重试 8 轮 (1 轮原始 + 7 轮重试)
RETRY_BACKOFF_S = 5   # 每轮重试前 sleep 5s (短, 限流自然就恢复了)

# 已知 7709 主站列表 (从 pytdx 文档 + 各路博客整理).
# 每轮 round 从中 random.choice 一台, 避免被同一 IP 累计限流.
# 关键: eltdx 1.0.2 client 启动后只锁一个 host, 不会自动 failover,
# 所以换 host 必须开新 client —— 跟每轮 round 重开 client 逻辑正好对上.
HOSTS = [
    "116.205.183.150:7709",   # 阿里云
    "124.71.187.122:7709",    # 阿里云
    "122.192.35.4:7709",      # 华泰
    "119.147.212.81:7709",    # 招商
    "60.191.117.167:7709",    # 浙商
    "115.236.62.66:7709",     # 西南
    "123.125.108.90:7709",    # 联通
    "218.108.50.108:7709",    # 移动
    "114.80.63.12:7709",      # 上海
    "180.153.18.170:7709",    # 上海
    "123.125.108.14:7709",    # 联通
    "60.12.136.250:7709",     # 浙商
    "218.6.170.54:7709",      # 国元
    "123.103.93.79:7709",     # 银河
]

# 分片多轮策略: 每 shard_round 把 pending 拆成若干个 <= SHARD_SIZE 的子组
# round 0: 5530 拆 6 x ~1000 (host 0-5)
# round 1: 剩 ~1500 拆 3 x ~500 (host 6-8)
# round 2: 剩 ~500 拆 3 x ~200 (host 9-11)
# round 3+: 1 x 全量 (host 12+)
SHARD_SIZES = [1000, 500, 200, 100, 50, 50]

# per-day snapshot schema version
DAILY_VERSION = 2

# ---------- reason 字段提取行业 ----------
# 样本:
#   "公司属于白酒（通达信研究行业）"                  -> 白酒
#   "公司主营业务属于光纤通信行业, 以网络总线..."        -> 光纤通信
#   "公司业务属于半导体设备制造领域"                   -> 半导体设备制造
#   "公司业务为废旧动力电池回收及梯次利用"               -> 废旧动力电池回收及梯次利用 (太长了, 截短)
#   "公司主营电力、热力生产和供应业"                    -> 电力、热力生产和供应业
_INDUSTRY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"公司属于([\u4e00-\u9fa5]+)（通达信研究行业）"),
    re.compile(r"公司主营业务属于([\u4e00-\u9fa5]+)"),
    re.compile(r"公司主营([\u4e00-\u9fa5]{2,16}?)业?[，,。；;是为]"),
    re.compile(r"公司业务属于([\u4e00-\u9fa5]+)"),
    re.compile(r"公司业务为([\u4e00-\u9fa5]{2,16})"),
    re.compile(r"公司业务是([\u4e00-\u9fa5]{2,16}?)的"),
    re.compile(r"公司聚焦于([\u4e00-\u9fa5]+)"),
    re.compile(r"公司主营([\u4e00-\u9fa5]+)"),
)

# 不应作为行业名的停用关键词 (业务描述被误抓时的兜底过滤)
_INDUSTRY_BLACKLIST: frozenset[str] = frozenset({
    "研发", "生产", "销售", "服务", "管理", "咨询",
    "的", "了", "是", "在", "和", "与", "及", "或", "等",
})


def extract_industry_from_reason(reason: str) -> str | None:
    if not reason:
        return None
    for pat in _INDUSTRY_PATTERNS:
        m = pat.search(reason)
        if not m:
            continue
        name = m.group(1).strip()
        if not name or name in _INDUSTRY_BLACKLIST:
            continue
        if len(name) > 16:
            # 太长通常是 reason 整段被吃进来, 截到 8 字
            name = name[:8]
        return name
    return None


# ---------- 题材拉取 ----------
import random as _random


def _connect(host: str | None = None, pool_size: int = 1, timeout: float = 8.0):
    """新建 eltdx TdxClient. host 不传则走 eltdx 默认 (单 host).

    关键: 传 host 则锁那一台, 不传则 eltdx 内部用 14 个主站.
    """
    import eltdx
    if host:
        return eltdx.TdxClient(host=host, pool_size=pool_size, timeout=timeout)
    return eltdx.TdxClient(pool_size=pool_size, timeout=timeout)


def _pick_host(round_idx: int) -> str:
    """每轮 round 用不同 host, 防止同一 IP 累计限流."""
    return HOSTS[round_idx % len(HOSTS)]


def _fetch_topics(c, code: str) -> list[dict[str, Any]]:
    try:
        st = c.helpers.stock_topics(code)
    except Exception as exc:
        logger.debug("stock_topics %s failed: %s", code, exc)
        return []
    out: list[dict[str, Any]] = []
    for t in st.topics or []:
        out.append({
            "topic_id": t.topic_id,
            "topic_name": t.topic_name,
            "reason": t.reason,
            "relation_level": float(t.relation_level or 0),
            "category_raw": int(t.category_raw or 0),
        })
    return out


# ---------- 持久化 ----------
def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# sectors.json 拆为多个分类文件: 每个 category_raw 一个 JSON
# 例: sectors_cat_0.json (行业板块 1829 topics) / sectors_cat_2.json (概念 270) / sectors_cat_4.json (风格 146)
# 未来 eltdx 加新 category_raw 不用改代码, 自动发现.

CATEGORIES_DIR = STOCK_UNIVERSE_DIR / "sectors"
CATEGORIES_INDEX_FILE = CATEGORIES_DIR / "index.json"

# 已知 category_raw -> 友好命名 (仅作参考, 不强制; 未知 cat 也照样写)
CATEGORY_NAMES: dict[int, str] = {
    0: "industries",     # 行业板块 (申万/中证/通达信)
    2: "concepts",       # 概念板块 (热点题材)
    4: "styles",         # 风格板块 (大盘/小盘/高股息)
}


def _category_file(category_raw: int) -> Path:
    name = CATEGORY_NAMES.get(category_raw)
    if name:
        return CATEGORIES_DIR / f"sectors_{name}_{category_raw}.json"
    return CATEGORIES_DIR / f"sectors_cat_{category_raw}.json"


def _category_label(category_raw: int) -> str:
    return CATEGORY_NAMES.get(category_raw, f"unknown_{category_raw}")


# ---------------------------------------------------------------------------
# 板块字典聚合 + 持久化
# ---------------------------------------------------------------------------


@dataclass
class SectorBucket:
    """通用 sector bucket, 同时适用于 industry(name) 和 topic(topic_id+name)."""
    key: str                      # industry name 或 topic_id
    name: str                     # 显示名
    extra: dict[str, Any]         # topic_id 等额外字段
    stock_codes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stock_count": len(self.stock_codes),
            "stock_codes": self.stock_codes,
            **self.extra,
        }


def aggregate_sectors(stocks: list[dict[str, Any]]) -> dict[int, list[SectorBucket]]:
    """动态检测 category_raw, 每个分类聚一个 bucket list.

    返回 {category_raw: [SectorBucket, ...]}.
    未来 eltdx 加新 category_raw (如 1/3/5/6...), 自动归到对应分类.
    """
    # category_raw -> key_field -> bucket
    # key_field: 'industry' 用 name, 'topic' 用 topic_id
    grouped: dict[int, dict[str, SectorBucket]] = {}

    for s in stocks:
        code = s.get("code")
        if not code:
            continue
        ind = s.get("industry") or ""
        if ind:
            # industry 算 cat=0 行业板块 (跟 eltdx category_raw=0 一致)
            inner = grouped.setdefault(0, {})
            if ind not in inner:
                inner[ind] = SectorBucket(key=ind, name=ind, extra={}, stock_codes=[])
            if code not in inner[ind].stock_codes:
                inner[ind].stock_codes.append(code)

        for t in s.get("topics") or []:
            cr = int(t.get("category_raw") or 0)
            tid = str(t.get("topic_id") or "")
            tname = t.get("topic_name") or ""
            if not tid or not tname:
                continue
            inner = grouped.setdefault(cr, {})
            if tid not in inner:
                inner[tid] = SectorBucket(
                    key=tid,
                    name=tname,
                    extra={"topic_id": tid},
                    stock_codes=[],
                )
            if code not in inner[tid].stock_codes:
                inner[tid].stock_codes.append(code)

    # 排序 + 转 list
    out: dict[int, list[SectorBucket]] = {}
    for cr, inner in grouped.items():
        buckets = list(inner.values())
        buckets.sort(key=lambda b: (-len(b.stock_codes), b.name))
        out[cr] = buckets
    return out


def save_sectors_index(
    stocks: list[dict[str, Any]],
    *,
    progress: bool = True,
) -> dict[str, Any]:
    """动态聚合 + 写多个 sectors_cat_<n>.json.

    返回 {category_raw: {"count": int, "file": Path, "label": str}}
    """
    t0 = time.time()
    CATEGORIES_DIR.mkdir(parents=True, exist_ok=True)
    grouped = aggregate_sectors(stocks)
    summary: dict[str, Any] = {
        "version": 2,
        "fetched_at": datetime.now().isoformat(),
        "source": "eltdx.helpers.stock_topics (reverse aggregated, dynamic category)",
        "category_count": len(grouped),
        "categories": {},
    }
    for cr in sorted(grouped.keys()):
        buckets = grouped[cr]
        label = _category_label(cr)
        out_file = _category_file(cr)
        payload = {
            "version": 2,
            "category_raw": cr,
            "category_label": label,
            "fetched_at": datetime.now().isoformat(),
            "source": "eltdx.helpers.stock_topics (reverse aggregated)",
            "sector_count": len(buckets),
            "sectors": [b.as_dict() for b in buckets],
        }
        _atomic_write(out_file, payload)
        summary["categories"][str(cr)] = {
            "category_raw": cr,
            "category_label": label,
            "sector_count": len(buckets),
            "file": out_file.name,
        }
        if progress:
            print(f"  -> 写 {out_file.name} (cat={cr} {label}, {len(buckets)} sectors)")

    # 写 index.json (顶层索引, 列出所有 cat 文件)
    _atomic_write(CATEGORIES_INDEX_FILE, summary)
    if progress:
        print(f"  -> 写 {CATEGORIES_INDEX_FILE.name} (共 {len(grouped)} 个 category)")
        print(f"  -> total {time.time()-t0:.1f}s")
    return summary


# ---------------------------------------------------------------------------
# 每日拉取
# ---------------------------------------------------------------------------


@dataclass
class RefreshResult:
    trading_day: str
    file_path: Path
    stock_count: int
    category_count: int
    categories: dict[str, int]  # {category_label: sector_count}
    elapsed_s: float
    categories_index: Path


def refresh(
    progress: bool = True,
    workers: int = DEFAULT_WORKERS,
    pool_size: int = DEFAULT_POOL_SIZE,
) -> RefreshResult:
    """拉全 A 股 + 每只股的题材, 写当日 JSON + sectors.json.

    走"多轮重试"策略, 即使 TQLEX 网关 502 限流, 也能拿全:
      round 0: 拉全 5530
      round 1..N: 重试空 topics 的 code
      直到全拿或达到 MAX_RETRY_ROUNDS
    """
    t0 = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    target_file = STOCK_UNIVERSE_DIR / f"{today}.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)

    if progress:
        print(f"[1/3] 拉全 A 股 code (eltdx.get_a_share_codes_all)")
    with _connect() as c:
        codes = c.get_a_share_codes_all()
    if progress:
        print(f"  -> {len(codes)} 只 code")

    if progress:
        print(
            f"[2/3] 分组分轮 (workers={workers}, pool_size={pool_size}, "
            f"max_rounds={MAX_RETRY_ROUNDS}, hosts={len(HOSTS)} 选一)"
        )

    # 分片多轮策略: 每 shard_round 用更小的 shard_size 拆组, 每组一个 host
    # round 0: 5530 拆 6 x 1000 (6 host 串行)
    # round 1: 剩 ~1500 拆 3 x 500 (3 host)
    # round 2: 剩 ~500 拆 3 x 200
    # round 3+: 拆 1 x 50
    # 累计限流不集中, 6-7 个 host 轮换拿到全

    results: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
    pending: list[str] = list(codes)
    host_cycle = 0
    shard_round = 0
    total_groups = 0

    while pending and shard_round < len(SHARD_SIZES) * 2:
        shard_size = SHARD_SIZES[min(shard_round, len(SHARD_SIZES) - 1)]
        shards = [pending[i:i+shard_size] for i in range(0, len(pending), shard_size)]

        if progress:
            print(
                f"  -- shard_round {shard_round}, {len(pending)} 只 拆 {len(shards)} 组 (size={shard_size}) --"
            )

        for gi, shard in enumerate(shards):
            if not shard:
                continue
            host = _pick_host(host_cycle)
            host_cycle += 1
            total_groups += 1
            t0 = time.time()
            client = _connect(host=host, pool_size=pool_size, timeout=6.0)
            try:
                client.connect()
            except Exception as exc:
                if progress:
                    print(f"  ! host={host} connect 失败: {exc}")
                continue
            try:
                with ThreadPoolExecutor(max_workers=min(workers, len(shard)), thread_name_prefix="topics") as executor:
                    futures = {executor.submit(_fetch_topics, client, code): code for code in shard}
                    for future in as_completed(futures):
                        code = futures[future]
                        try:
                            topics = future.result() or []
                        except Exception as exc:
                            topics = []
                        results[code] = topics
            finally:
                client.close()

            got = sum(1 for c in shard if results.get(c))
            speed = got / max(time.time() - t0, 0.1)
            if progress:
                print(
                    f"     [group {gi+1}/{len(shards)}] host={host} "
                    f"{len(shard)} 只 -> {got} 拿到, {speed:.0f}/s, "
                    f"{time.time()-t0:.1f}s"
                )

        pending = [c for c in codes if not results.get(c)]
        if progress:
            print(f"  shard_round {shard_round} done: 剩 {len(pending)} 只空")
        if not pending:
            break
        shard_round += 1
        if progress:
            print(f"  -- sleep {RETRY_BACKOFF_S}s 让网关限流恢复 --")
        time.sleep(RETRY_BACKOFF_S)

    if pending and progress:
        print(
            f"  WARN: {len(pending)} 只最终仍为空, "
            f"将以空 topics 入库"
        )

    if progress:
        print(f"[3/3] 聚合 + 写盘")
    stocks: list[dict[str, Any]] = []
    for code in codes:
        topics = results.get(code, [])
        industry: str | None = None
        for t in topics:
            reason = t.get("reason") or ""
            if industry is None:
                industry = extract_industry_from_reason(reason)
        stocks.append({
            "code": code,
            "name": "",
            "industry": industry or "",
            "topics": topics,
        })

    payload = {
        "version": DAILY_VERSION,
        "trading_day": today,
        "fetched_at": datetime.now().isoformat(),
        "source": f"eltdx.helpers.stock_topics (pool_size={pool_size}, workers={workers}, groups={total_groups})",
        "stock_count": len(stocks),
        "empty_count": len([s for s in stocks if not s["topics"]]),
        "stocks": stocks,
    }
    _atomic_write(target_file, payload)
    _update_index(today, target_file, payload)

    # 写 sectors 字典 (动态分 category_raw 多个文件)
    sectors_summary = save_sectors_index(stocks, progress=progress)

    elapsed = time.time() - t0
    cat_summary = ", ".join(
        "{}:{}".format(c["category_label"], c["sector_count"])
        for c in sectors_summary["categories"].values()
    )
    if progress:
        print(
            f"done. {elapsed:.0f}s, {len(stocks)} stocks, "
            f"{sectors_summary['category_count']} categories ({cat_summary}) "
            f"({len(stocks)/elapsed:.0f} 股/s, {total_groups} groups)"
        )

    return RefreshResult(
        trading_day=today,
        file_path=target_file,
        stock_count=len(stocks),
        category_count=sectors_summary["category_count"],
        categories={
            c["category_label"]: c["sector_count"]
            for c in sectors_summary["categories"].values()
        },
        elapsed_s=elapsed,
        categories_index=CATEGORIES_INDEX_FILE,
    )


def _update_index(trading_day: str, file_path: Path, payload: dict[str, Any]) -> None:
    STOCK_UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    if STOCK_UNIVERSE_INDEX_FILE.exists():
        try:
            index = json.loads(STOCK_UNIVERSE_INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            index = {"versions": []}
    else:
        index = {"versions": []}
    history = [v for v in index.get("versions", []) if v.get("trading_day") != trading_day]
    history.insert(0, {
        "trading_day": trading_day,
        "file": str(file_path.relative_to(STOCK_UNIVERSE_DIR)),
        "stock_count": payload["stock_count"],
        "fetched_at": payload["fetched_at"],
    })
    index["versions"] = history[:30]
    index["latest"] = history[0]
    _atomic_write(STOCK_UNIVERSE_INDEX_FILE, index)


# ---------------------------------------------------------------------------
# 加载 hotpath
# ---------------------------------------------------------------------------


def _read_json(path: Path, default=None) -> dict[str, Any] | None:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("read %s failed: %s", path, exc)
        return default


def load_latest() -> dict[str, Any] | None:
    """加载最近的每日快照. 用于行情/实时快照查询."""
    if not STOCK_UNIVERSE_INDEX_FILE.exists():
        return None
    try:
        index = json.loads(STOCK_UNIVERSE_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    latest = index.get("latest")
    if not latest:
        return None
    fp = STOCK_UNIVERSE_DIR / latest["file"]
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def load_sectors_index() -> dict[str, Any] | None:
    """加载 sectors/index.json. 列出所有 category 概况."""
    return _read_json(CATEGORIES_INDEX_FILE)


def load_category(category_raw: int) -> dict[str, Any] | None:
    """加载单个 category 文件 sectors_xxx_<n>.json.

    未来加新 category_raw 直接传新数字即可, 不用改代码.
    """
    return _read_json(_category_file(category_raw), None)


# ---------------------------------------------------------------------------
# 行业 / 概念板块 公开 API (hotpath 友好)
# ---------------------------------------------------------------------------


def list_categories() -> list[dict[str, Any]]:
    """列出所有 category (从 sectors/index.json). [{category_raw, category_label, sector_count, file}]."""
    idx = load_sectors_index()
    if not idx:
        return []
    return list(idx.get("categories", {}).values())


def list_sectors_by_category(category_raw: int) -> list[dict[str, Any]]:
    """列出某 category 下的所有 sector. [{name, topic_id, stock_count, stock_codes}, ...]."""
    data = load_category(category_raw)
    if not data:
        return []
    return data.get("sectors", [])


# 兼容旧 API: list_industries = list_sectors_by_category(0)
def list_industries() -> list[dict[str, Any]]:
    return list_sectors_by_category(0)


# 兼容旧 API: list_topics = list_sectors_by_category(2)
def list_topics() -> list[dict[str, Any]]:
    return list_sectors_by_category(2)


def get_sector_stocks(category_raw: int, *, name: str | None = None, topic_id: str | None = None) -> list[str]:
    """根据 category_raw + name/topic_id 拿成分股 codes."""
    if not name and not topic_id:
        return []
    sectors = list_sectors_by_category(category_raw)
    for s in sectors:
        if topic_id and str(s.get("topic_id")) == str(topic_id):
            return s.get("stock_codes", [])
        if name and s.get("name") == name:
            return s.get("stock_codes", [])
    return []


# 兼容旧 API: get_industry_stocks(name) = get_sector_stocks(0, name=name)
def get_industry_stocks(name: str) -> list[str]:
    return get_sector_stocks(0, name=name)


# 兼容旧 API: get_concept_stocks(topic_id, topic_name) = get_sector_stocks(2, ...)
def get_concept_stocks(topic_id: str | None = None, topic_name: str | None = None) -> list[str]:
    return get_sector_stocks(2, topic_id=topic_id, name=topic_name)


def find_sectors_for(code: str, category_raw: int | None = None) -> list[dict[str, Any]]:
    """某 code 所属某 category 的所有 sector.

    category_raw=None 时, 遍历所有 category 找.
    返回 [{category_raw, category_label, name, topic_id}]
    """
    if category_raw is not None:
        cats = [category_raw]
    else:
        idx = load_sectors_index()
        cats = [int(c) for c in (idx or {}).get("categories", {}).keys()]
    out: list[dict[str, Any]] = []
    for cr in cats:
        for s in list_sectors_by_category(cr):
            if code in s.get("stock_codes", []):
                out.append({
                    "category_raw": cr,
                    "category_label": _category_label(cr),
                    "name": s.get("name"),
                    "topic_id": s.get("topic_id"),
                })
    return out


# 兼容旧 API
def find_industries_for(code: str) -> list[str]:
    """某 code 所属所有行业 (cat=0). 返回 name 列表."""
    return [s["name"] for s in find_sectors_for(code, category_raw=0)]


def find_concepts_for(code: str) -> list[dict[str, Any]]:
    """某 code 所属所有概念 (cat=2)."""
    return [
        {"topic_id": s.get("topic_id"), "topic_name": s.get("name")}
        for s in find_sectors_for(code, category_raw=2)
    ]


def find_industry_for(code: str) -> str | None:
    inds = find_industries_for(code)
    return inds[0] if inds else None


def find_topics_for(code: str) -> list[dict[str, Any]]:
    return find_concepts_for(code)


# ---------------------------------------------------------------------------
# 仅从最新每日快照查的便捷方法 (单股快照, 不进 sectors 字典)
# ---------------------------------------------------------------------------


def find_stock_meta(code: str) -> dict[str, Any] | None:
    """某 code 在每日快照里的元数据 (含完整 topics). 不走 sectors.json."""
    latest = load_latest()
    if not latest:
        return None
    for s in latest.get("stocks", []):
        if s.get("code") == code:
            return s
    return None
