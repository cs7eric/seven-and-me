"""
A 股"股票 ↔ 板块/行业"映射服务 (纯映射, 不存行情).

每日 17:00 (盘后) 拉一次:
  1. eltdx ``client.get_a_share_codes_all()`` 拿全 5530+ 只 A 股 code
  2. eltdx ``client.helpers.stock_topics(code)`` 拿每只股的题材清单,
     从 ``reason`` 字段正则提取 "公司属于XXX（通达信研究行业）" 作为行业归一

**不存行情 / 涨幅 / 成交额** —— 这些数据由 hotpath 实时调下游 API.

持久化到 ``STOCK_UNIVERSE_DIR / YYYY-MM-DD.json``:
  {
    "version": 2,
    "trading_day": "2026-06-06",
    "fetched_at": "...",
    "stocks": [
      {"code":"sh600519", "name":"", "industry":"白酒",
       "topics":[{"topic_id":"226","topic_name":"白酒概念","reason":"..."}]}
    ],
    "industries": [{"name":"白酒", "stock_codes":[...]}],
    "topics":     [{"topic_id":"226","topic_name":"白酒概念", "stock_codes":[...]}]
  }

CLI 拉取: ``python -m backend.scripts.refresh_stock_universe``
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
from typing import Any

from backend.config.settings import STOCK_UNIVERSE_DIR, STOCK_UNIVERSE_INDEX_FILE

logger = logging.getLogger(__name__)

# 拉取并发: 单 TdxClient + pool_size=4 长连接池 + 8 worker 线程.
# 关键: eltdx TdxClient 内部串行化请求, 多 client 才能并行;
# 但单 client pool_size=4 也能让 4 路 TCP 长连接并发转发 F10 请求.
# 实测:
#   串行          -> 0.3 股/s
#   pool=8+wrk=8  -> 2.1 股/s  (单 RPC 0.3-0.5s)
# 估算 5530 / 2.1 = ~45 分钟
# 这是 eltdx TQLEX HTTP 网关的硬上限, 没法再快;
# 进一步提速必须走 别的 行情 API (push2.eastmoney / ths).
DEFAULT_WORKERS = 8
DEFAULT_POOL_SIZE = 4

SCHEMA_VERSION = 2  # 不再含 quote 字段

# ---------- reason 字段提取行业 ----------
# 样本: "公司属于白酒（通达信研究行业）"
_INDUSTRY_RE = re.compile(r"公司属于([\u4e00-\u9fa5]+)（通达信研究行业）")
_FALLBACK_INDUSTRY_RE = re.compile(r"公司主营([\u4e00-\u9fa5]+)")


def extract_industry_from_reason(reason: str) -> str | None:
    if not reason:
        return None
    m = _INDUSTRY_RE.search(reason)
    if m:
        return m.group(1)
    m2 = _FALLBACK_INDUSTRY_RE.search(reason)
    if m2:
        return m2.group(1)
    return None


# ---------- 题材拉取（最慢的一步） ----------
# helpers.stock_topics(code) 返回 StockTopics, .topics 是元组
# 每个 StockTopic: topic_id, topic_name, reason, relation_level


def _connect(pool_size: int = 1):
    import eltdx
    return eltdx.TdxClient(pool_size=pool_size, timeout=8.0)


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


@dataclass
class RefreshResult:
    trading_day: str
    file_path: Path
    stock_count: int
    industry_count: int
    topic_count: int
    elapsed_s: float


def refresh(
    progress: bool = True,
    workers: int = DEFAULT_WORKERS,
    pool_size: int = DEFAULT_POOL_SIZE,
) -> RefreshResult:
    """拉全 A 股 code + 每只股的题材, 写映射 JSON.

    慢, 仅供每日 17:00 跑一次. 行情/涨幅/成交额 全部不存.

    5530 只股按 ``pool_size`` 长连接池 + ``workers`` 个线程并发拉.
    eltdx TdxClient 内部已串行化请求, 但 ``pool_size`` 长连接池会让
    F10 HTTP 请求被多 TCP 链路并行处理, 提升 server 侧并发.
    单 worker 失败 (502 / 超时) 不影响其他 worker, 失败 code 走空 topics.
    """
    t0 = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    target_file = STOCK_UNIVERSE_DIR / f"{today}.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)

    if progress:
        print(f"[1/2] 拉全 A 股 code (eltdx.get_a_share_codes_all)")
    with _connect(pool_size=1) as c:
        codes = c.get_a_share_codes_all()
    if progress:
        print(f"  -> {len(codes)} 只 code")

    if progress:
        print(
            f"[2/2] 并发拉每只股的题材 "
            f"(pool_size={pool_size} 长连接池, workers={workers} 线程, 5530+ 次)"
        )

    # 单 client 多 TCP 长连接 (pool_size > 1) + 多 worker 线程
    # 这样: 一个 client 实例 + N 条 TCP 链路 + M 个线程
    # eltdx 内部 锁/连接池 派发请求到不同 TCP 链路, 线程侧只需等 future
    client = _connect(pool_size=pool_size)
    client.connect()

    def _worker(code: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            return code, _fetch_topics(client, code)
        except Exception as exc:
            logger.debug("worker %s error: %s", code, exc)
            return code, []

    results: dict[str, list[dict[str, Any]]] = {}
    done_count = 0
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="topics") as executor:
            futures = {executor.submit(_worker, code): code for code in codes}
            for future in as_completed(futures):
                try:
                    code, topics = future.result()
                    results[code] = topics
                except Exception as exc:
                    code = futures[future]
                    logger.debug("future %s error: %s", code, exc)
                    results[code] = []
                done_count += 1
                if progress and done_count % 200 == 0:
                    speed = done_count / (time.time() - t0)
                    eta = (len(codes) - done_count) / max(speed, 0.1)
                    print(
                        f"  -> 进度 {done_count}/{len(codes)} "
                        f"({speed:.0f} 股/s, ETA {eta:.0f}s, 已用 {time.time() - t0:.0f}s)"
                    )
    finally:
        client.close()

    # 按 industry / topic 聚合 (用稳定顺序: codes 原顺序)
    industry_map: dict[str, list[str]] = {}
    topic_map: dict[str, dict[str, Any]] = {}
    stocks: list[dict[str, Any]] = []
    for code in codes:
        topics = results.get(code, [])
        industry: str | None = None
        for t in topics:
            reason = t.get("reason") or ""
            if industry is None:
                industry = extract_industry_from_reason(reason)
            tid = t.get("topic_id") or ""
            tname = t.get("topic_name") or ""
            if not tid or not tname:
                continue
            bucket = topic_map.setdefault(tid, {"topic_id": tid, "topic_name": tname, "stock_codes": []})
            bucket["stock_codes"].append(code)
        if industry:
            industry_map.setdefault(industry, []).append(code)
        stocks.append({
            "code": code,
            "name": "",
            "industry": industry or "",
            "topics": topics,
        })

    if progress:
        print(f"  -> 写文件 -> {target_file}")

    payload = {
        "version": SCHEMA_VERSION,
        "trading_day": today,
        "fetched_at": datetime.now().isoformat(),
        "source": f"eltdx.helpers.stock_topics (pool_size={pool_size}, workers={workers})",
        "stock_count": len(stocks),
        "industry_count": len(industry_map),
        "topic_count": len(topic_map),
        "stocks": stocks,
        "industries": [
            {"name": k, "stock_codes": v} for k, v in sorted(industry_map.items(), key=lambda x: -len(x[1]))
        ],
        "topics": [
            {"topic_id": v["topic_id"], "topic_name": v["topic_name"], "stock_codes": v["stock_codes"]}
            for v in sorted(topic_map.values(), key=lambda x: -len(x["stock_codes"]))
        ],
    }

    _atomic_write(target_file, payload)
    _update_index(today, target_file, payload)

    elapsed = time.time() - t0
    if progress:
        print(
            f"done. {elapsed:.0f}s, {len(stocks)} stocks, {len(industry_map)} industries, "
            f"{len(topic_map)} topics ({len(stocks)/elapsed:.0f} 股/s)"
        )

    return RefreshResult(
        trading_day=today,
        file_path=target_file,
        stock_count=len(stocks),
        industry_count=len(industry_map),
        topic_count=len(topic_map),
        elapsed_s=elapsed,
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
        "industry_count": payload["industry_count"],
        "topic_count": payload["topic_count"],
        "fetched_at": payload["fetched_at"],
    })
    index["versions"] = history[:30]
    index["latest"] = history[0]
    _atomic_write(STOCK_UNIVERSE_INDEX_FILE, index)


def load_latest() -> dict[str, Any] | None:
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


# ---------- 运行时便捷查询 ----------


def find_industry_for(code: str) -> str | None:
    """hotpath: 查某只 code 属于哪个行业 (用最近一份 universe)."""
    universe = load_latest()
    if not universe:
        return None
    for s in universe.get("stocks", []):
        if s.get("code") == code:
            return s.get("industry") or None
    return None


def find_topics_for(code: str) -> list[dict[str, Any]]:
    """hotpath: 查某只 code 所属题材."""
    universe = load_latest()
    if not universe:
        return []
    for s in universe.get("stocks", []):
        if s.get("code") == code:
            return s.get("topics") or []
    return []


def list_industries() -> list[dict[str, Any]]:
    """hotpath: 列出所有行业 + 成分股 codes."""
    universe = load_latest()
    if not universe:
        return []
    return universe.get("industries", [])
