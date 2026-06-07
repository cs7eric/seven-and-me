"""akshare 同花顺 90 行业 + 成分股爬虫 (HTML parse + Playwright 翻页).

数据源:
  - 行业列表:        ``ak.stock_board_industry_name_ths()``            90 行 {name, code(881xxx)}
  - 行业指数 K 线:    ``ak.stock_board_industry_index_ths(name)``        日 K 975 bars
  - 行业指数 9 项:    ``ak.stock_board_industry_info_ths(name)``         10 项 (今开/昨收/...)
  - 行业成分股列表:  爬 https://q.10jqka.com.cn/thshy/detail/code/{code}/
                     "成分股涨跌排行榜" 表格 13 列, 多页用 Playwright 翻页
                     (单页 20 只, 半导体等大行业有 9 页 = 180 只)

接口设计:
  - ``name`` 或 ``code (881xxx)`` 互通
  - 90 行业全量并发爬, 默认 4 路 (Playwright 单浏览器 1 个 page 串行翻页, 1 路就够)
  - 单行业结果本地缓存到 ``reference/stock-universe/ths_industry/constituents/{code}.json``
  - 单行业接口走磁盘缓存
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from backend.config.settings import STOCK_UNIVERSE_DIR

try:
    import akshare as ak  # noqa: F401
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    ak = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 持久化目录
INDUSTRY_DIR: Final[Path] = STOCK_UNIVERSE_DIR / "ths_industry"
INDUSTRY_DIR.mkdir(parents=True, exist_ok=True)
INDUSTRY_LIST_FILE: Final[Path] = INDUSTRY_DIR / "industry_list.json"
INDUSTRY_INFO_FILE: Final[Path] = INDUSTRY_DIR / "industry_info.json"
CONSTITUENTS_DIR: Final[Path] = INDUSTRY_DIR / "constituents"
CONSTITUENTS_DIR.mkdir(parents=True, exist_ok=True)
KLINE_DIR: Final[Path] = INDUSTRY_DIR / "kline"
KLINE_DIR.mkdir(parents=True, exist_ok=True)

# 网络爬虫
_PAGE_URL = "https://q.10jqka.com.cn/thshy/detail/code/{code}/"
_HEADERS = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
    ("Accept-Language", "zh-CN,zh;q=0.9"),
]
# 同花顺首页"成分股涨跌排行榜"表格列顺序 (13 列):
# 0 序号, 1 code, 2 名称, 3 现价, 4 涨跌幅%, 5 涨跌额, 6 涨速%,
# 7 换手%, 8 量比, 9 振幅%, 10 成交额(text), 11 流通股(text),
# 12 流通市值(text), 13 市盈率
_PER_PAGE_SIZE = 20
_PLAYWRIGHT_HEADLESS = True


# 进程级缓存
_cache_lock = threading.Lock()
_industry_list_cache: dict[str, dict[str, str]] | None = None
_industry_info_cache: dict[str, dict[str, Any]] | None = None
_opener = None


def _get_opener() -> urllib.request.OpenerDirector:
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        _opener.addheaders = _HEADERS
    return _opener


# =============================================================================
# 1. 90 行业列表
# =============================================================================
def _fetch_industry_list_from_ak() -> dict[str, dict[str, str]]:
    df = ak.stock_board_industry_name_ths()
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        name = str(row.get("name") or "").strip()
        code = str(row.get("code") or "").strip()
        if not name or not code:
            continue
        out[code] = {"name": name, "code": code}
    return out


def get_industry_list(*, refresh: bool = False) -> dict[str, dict[str, str]]:
    """90 行业列表, 进程内缓存 + 磁盘缓存."""
    global _industry_list_cache
    with _cache_lock:
        if not refresh and _industry_list_cache is not None:
            return dict(_industry_list_cache)
        if not refresh and INDUSTRY_LIST_FILE.exists():
            try:
                blob = json.loads(INDUSTRY_LIST_FILE.read_text(encoding="utf-8"))
                _industry_list_cache = blob.get("byCode") or {}
                if _industry_list_cache:
                    return dict(_industry_list_cache)
            except Exception:
                pass
        try:
            _industry_list_cache = _fetch_industry_list_from_ak()
        except Exception as exc:
            logger.warning("ak.stock_board_industry_name_ths failed: %s", exc)
            _industry_list_cache = {}
        # 写盘
        try:
            name_to_code = {v["name"]: c for c, v in _industry_list_cache.items()}
            INDUSTRY_LIST_FILE.write_text(
                json.dumps({
                    "fetchedAt": datetime.now().isoformat(timespec="seconds"),
                    "byCode": _industry_list_cache, "nameToCode": name_to_code,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("write industry list cache failed: %s", exc)
        return dict(_industry_list_cache)


def name_to_code(name: str) -> str | None:
    if not name: return None
    raw = str(name).strip()
    for code, info in get_industry_list().items():
        if info["name"] == raw:
            return code
    return None


def code_to_name(code: str) -> str | None:
    if not code: return None
    return get_industry_list().get(str(code).strip(), {}).get("name")


def resolve_symbol(name_or_code: str) -> str:
    """统一成 name (akshare / 爬虫都需要 name)."""
    if not name_or_code: return ""
    raw = str(name_or_code).strip()
    if not raw: return ""
    if raw.isdigit() and len(raw) == 6:
        n = code_to_name(raw)
        return n or raw
    return raw


# =============================================================================
# 2. 行业指数 9 项实时
# =============================================================================
def _to_float(s: Any) -> float | None:
    if s is None: return None
    try:
        v = float(s); return v if v == v else None
    except (TypeError, ValueError):
        return None


def _fetch_industry_info_all() -> dict[str, dict[str, Any]]:
    """90 行业 9 项实时, 8 并发 + 失败重试 1 次."""
    items = list(get_industry_list().values())
    out: dict[str, dict[str, Any]] = {}

    def _one(info: dict[str, str]) -> tuple[str, dict[str, Any]] | None:
        name = info["name"]
        for attempt in (1, 2):
            try:
                df = ak.stock_board_industry_info_ths(symbol=name)
            except Exception as exc:
                logger.debug("info %s attempt %d failed: %s", name, attempt, exc)
                time.sleep(0.2)
                continue
            if df is None or df.empty:
                return None
            kvs: dict[str, Any] = {}
            for _, row in df.iterrows():
                kvs[str(row.get("项目") or "").strip()] = row.get("值")
            return name, kvs
        return None

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ths-info") as pool:
        futures = [pool.submit(_one, info) for info in items]
        for fut, info in zip(futures, items):
            try:
                r = fut.result(timeout=20)
            except Exception as exc:
                logger.debug("info %s timeout: %s", info["name"], exc)
                continue
            if r:
                out[r[0]] = {"code": info["code"], "kvs": r[1], "fetchedAt": datetime.now().isoformat(timespec="seconds")}

    try:
        INDUSTRY_INFO_FILE.write_text(
            json.dumps({"fetchedAt": datetime.now().isoformat(timespec="seconds"), "byName": out},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("write industry info cache failed: %s", exc)
    return out


def get_industry_info(name_or_code: str, *, refresh: bool = False) -> dict[str, Any] | None:
    target_name = resolve_symbol(name_or_code)
    if not target_name: return None
    global _industry_info_cache
    with _cache_lock:
        if not refresh and _industry_info_cache is not None and target_name in _industry_info_cache:
            return _industry_info_cache[target_name]
        if not refresh and INDUSTRY_INFO_FILE.exists():
            try:
                blob = json.loads(INDUSTRY_INFO_FILE.read_text(encoding="utf-8"))
                _industry_info_cache = blob.get("byName") or {}
                if target_name in _industry_info_cache:
                    return _industry_info_cache[target_name]
            except Exception:
                pass
        try:
            _industry_info_cache = _fetch_industry_info_all()
        except Exception as exc:
            logger.warning("ak industry info all failed: %s", exc)
            _industry_info_cache = {}
    return _industry_info_cache.get(target_name)


# =============================================================================
# 3. 行业指数 K 线
# =============================================================================
def _kline_path(code: str, period: str) -> Path:
    return KLINE_DIR / f"{code}_{period}.json"


def get_industry_kline(name_or_code: str, period: str = "day",
                       start_date: str | None = None,
                       end_date: str | None = None,
                       *, refresh: bool = False) -> list[dict[str, Any]]:
    target_name = resolve_symbol(name_or_code)
    if not target_name: return []
    code = name_to_code(target_name) or target_name
    p = _kline_path(code, period)
    if not refresh and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            return blob.get("rows") or []
        except Exception:
            pass
    if not start_date:
        start_date = (date.today() - timedelta(days=365 * 5)).strftime("%Y%m%d")
    if not end_date:
        end_date = date.today().strftime("%Y%m%d")
    try:
        df = ak.stock_board_industry_index_ths(symbol=target_name, start_date=start_date, end_date=end_date)
    except Exception as exc:
        logger.warning("ak.stock_board_industry_index_ths(%s) failed: %s", target_name, exc)
        return []
    rows: list[dict[str, Any]] = []
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            d = row.get("日期")
            rows.append({
                "date":   d.isoformat() if hasattr(d, "isoformat") else str(d),
                "open":   row.get("开盘价"),
                "high":   row.get("最高价"),
                "low":    row.get("最低价"),
                "close":  row.get("收盘价"),
                "volume": row.get("成交量"),
                "amount": row.get("成交额"),
            })
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({
                "name": target_name, "code": code, "period": period,
                "start_date": start_date, "end_date": end_date,
                "fetchedAt": datetime.now().isoformat(timespec="seconds"),
                "rows": rows,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("write kline cache failed: %s", exc)
    return rows


# =============================================================================
# 4. 行业成分股列表 (HTML 爬虫, 同花顺详情页)
# =============================================================================
def _constituents_path(code: str) -> Path:
    return CONSTITUENTS_DIR / f"{code}.json"


def _fetch_page_html(code: str, page: int = 1) -> str:
    url = _PAGE_URL.format(code=code)
    if page > 1:
        url = f"{url}?page={page}"
    return _get_opener().open(url, timeout=15).read().decode("gb18030", errors="replace")


def _extract_total_pages(html: str) -> int:
    m = re.search(r'<span class="page_info">(\d+)\s*/\s*(\d+)</span>', html)
    if not m:
        return 1
    try:
        return max(1, int(m.group(2)))
    except (TypeError, ValueError):
        return 1


def _parse_constituents_html(html: str) -> list[dict[str, Any]]:
    """从 '成分股涨跌排行榜' 表格抠 13 列数据."""
    m = re.search(r"成分股涨跌排行榜", html)
    if not m:
        return []
    seg = html[m.start(): m.start() + 20000]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", seg, re.DOTALL):
        tr_html = tr.group(1)
        cm = re.search(r"stockpage\.10jqka\.com\.cn/(\d{6})", tr_html)
        if not cm: continue
        sc = cm.group(1)
        if sc in seen: continue
        seen.add(sc)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, re.DOTALL)
        plain = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        rows.append({
            "rank":         _to_float(plain[0]) if len(plain) > 0 else None,
            "code6":        sc,
            "name":         plain[2] if len(plain) > 2 else None,
            "price":        _to_float(plain[3]) if len(plain) > 3 else None,
            "changePct":    _to_float(plain[4]) if len(plain) > 4 else None,
            "change":       _to_float(plain[5]) if len(plain) > 5 else None,
            "riseSpeed":    _to_float(plain[6]) if len(plain) > 6 else None,
            "turnoverRate": _to_float(plain[7]) if len(plain) > 7 else None,
            "volumeRatio":  _to_float(plain[8]) if len(plain) > 8 else None,
            "amplitude":    _to_float(plain[9]) if len(plain) > 9 else None,
            "amountText":   plain[10] if len(plain) > 10 else None,
            "freeFloatText": plain[11] if len(plain) > 11 else None,
            "marketCapText": plain[12] if len(plain) > 12 else None,
            "pe":           plain[13] if len(plain) > 13 else None,
        })
    return rows


def _crawl_constituents_payload(code: str, target_name: str) -> dict[str, Any]:
    """同花顺行业详情页翻全页: 优先 Playwright, 失败回退 urllib 1 页.

    Playwright 模拟点击 "下一页" <a class="changePage"> 按钮, 真实翻页.
    """
    # 1) 尝试 Playwright
    try:
        return _pw_crawl_payload(code, target_name)
    except Exception as exc:
        logger.warning("playwright crawl %s failed: %s, fallback to urllib", code, exc)

    # 2) urllib fallback (单页 20 只)
    first_html = _fetch_page_html(code, page=1)
    total_pages = _extract_total_pages(first_html)
    rows = _parse_constituents_html(first_html)
    page_counts = [len(rows)]

    for page in range(2, total_pages + 1):
        html = _fetch_page_html(code, page=page)
        page_rows = _parse_constituents_html(html)
        page_counts.append(len(page_rows))
        rows.extend(page_rows)

    # 去重
    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for r in rows:
        k = str(r.get("code6") or "").strip()
        if not k or k in seen: continue
        seen.add(k)
        dedup.append(r)

    return {
        "code": code,
        "name": target_name,
        "pages": total_pages,
        "pageRowCounts": page_counts,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "rows": dedup,
    }


# ---------------------------------------------------------------------------
# Playwright 翻页
# ---------------------------------------------------------------------------
_pw_lock = threading.Lock()
_pw_playwright = None
_pw_browser = None


def _get_pw_browser():
    """全局单例 chromium 浏览器, 第一次创建, 后续复用."""
    global _pw_playwright, _pw_browser
    if _pw_browser is not None:
        return _pw_browser
    with _pw_lock:
        if _pw_browser is not None:
            return _pw_browser
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "playwright not installed; run `pip install playwright` "
                "then `playwright install chromium`"
            ) from exc
        _pw_playwright = sync_playwright().start()
        _pw_browser = _pw_playwright.chromium.launch(headless=_PLAYWRIGHT_HEADLESS)
        return _pw_browser


def _pw_crawl_payload(code: str, target_name: str) -> dict[str, Any]:
    """用 Playwright 真实浏览器 + 翻页按钮拿全所有页.

    注意: 同花顺对高并发访问会触发 IP 风控 (返回 "Nginx forbidden").
    - 我们 1 行业 1 个 context, 翻完就 close, 不并发.
    - 每次 goto 之前 sleep 1-2s 随机; 翻页间隔 1.5-2.5s 随机, 模拟人.
    - 失败 1 次重试, retry 也失败抛出去走 urllib fallback.
    """
    import random
    browser = _get_pw_browser()
    last_err: Exception | None = None
    for attempt in (1, 2):
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://q.10jqka.com.cn/thshy/",
            },
        )
        page = ctx.new_page()
        page.set_default_timeout(15000)
        try:
            time.sleep(random.uniform(0.6, 1.6))
            page.goto(_PAGE_URL.format(code=code), wait_until="domcontentloaded", timeout=20000)
            # 等排行榜首行 / 等表格行
            try:
                page.wait_for_selector("table tbody tr", timeout=10000)
            except Exception:
                pass
            time.sleep(random.uniform(0.4, 1.0))

            all_rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            page_counts: list[int] = []
            page_no = 1
            max_pages = 100
            while page_no <= max_pages:
                html = page.content()
                # 风控页: <h1>Nginx forbidden.</h1>
                if "Nginx forbidden" in html or "forbidden." in html.lower():
                    raise RuntimeError(f"403 forbidden at page {page_no}")
                rows = _parse_constituents_html(html)
                page_counts.append(len(rows))
                for r in rows:
                    k = str(r.get("code6") or "").strip()
                    if not k or k in seen: continue
                    seen.add(k)
                    all_rows.append(r)
                # 找 "下一页" (有 href="javascript:void(0)" page="N")
                next_btn = page.query_selector('a.changePage:has-text("下一页")')
                if not next_btn:
                    # 兜底: 任何 class 含 changePage + page=N (N>1)
                    next_btn = page.query_selector('a.changePage:not([page="1"])')
                if not next_btn:
                    break
                try:
                    next_btn.click()
                    time.sleep(random.uniform(1.5, 2.5))
                except Exception as exc:
                    logger.debug("click next failed: %s", exc)
                    break
                page_no += 1
            return {
                "code": code,
                "name": target_name,
                "pages": page_no,
                "pageRowCounts": page_counts,
                "fetchedAt": datetime.now().isoformat(timespec="seconds"),
                "rows": all_rows,
            }
        except Exception as exc:
            last_err = exc
            logger.warning("pw crawl %s attempt %d failed: %s", code, attempt, exc)
            if attempt < 2:
                time.sleep(random.uniform(2.0, 4.0))
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    raise RuntimeError(f"playwright crawl {code} failed after retries: {last_err}")


def get_constituents_payload(name_or_code: str, *, refresh: bool = False) -> dict[str, Any]:
    """单行业成分股全分页结果，包含页数与去重后的 rows。"""
    target_name = resolve_symbol(name_or_code)
    if not target_name:
        return {"code": "", "name": "", "pages": 0, "pageRowCounts": [], "rows": []}
    code = name_to_code(target_name) or target_name
    p = _constituents_path(code)
    if not refresh and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(blob, dict) and isinstance(blob.get("rows"), list):
                blob.setdefault("code", code)
                blob.setdefault("name", target_name)
                blob.setdefault("pages", 1)
                blob.setdefault("pageRowCounts", [len(blob.get("rows") or [])])
                return blob
        except Exception:
            pass
    try:
        payload = _crawl_constituents_payload(code, target_name)
    except Exception as exc:
        logger.warning("crawl constituents for %s failed: %s", code, exc)
        return {"code": code, "name": target_name, "pages": 0, "pageRowCounts": [], "rows": []}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("write constituents cache failed: %s", exc)
    return payload


def get_constituents(name_or_code: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    """单行业成分股: 13 列 (序号/code/名称/现价/涨跌幅/涨跌/涨速/换手/量比/振幅/成交额/流通股/流通市值/市盈率)."""
    return get_constituents_payload(name_or_code, refresh=refresh).get("rows") or []


def get_all_constituents(*, refresh: bool = False, inter_industry_sleep: float = 8.0) -> dict[str, list[dict[str, Any]]]:
    """90 行业成分股全量. 单线程串行 (IP 风控), 每个行业间 sleep ``inter_industry_sleep`` 秒.

    设计原则: 同花顺对出口 IP 高并发会封 (Nginx forbidden).
    - 1 行业 1 context, 翻完 close, 不并发
    - 每个行业间 sleep 8s 模拟人, 避免触发频率阈值
    - 预计 90 行业 × (8s + 翻页 5-20s) = 20-40 分钟
    - 落盘后 ``refresh=False`` 直接读缓存, 不再爬
    """
    import random
    items = get_industry_list()
    out: dict[str, list[dict[str, Any]]] = {}
    for code, info in items.items():
        if not refresh:
            p = _constituents_path(code)
            if p.exists():
                try:
                    blob = json.loads(p.read_text(encoding="utf-8"))
                    cached_rows = blob.get("rows") or []
                    if cached_rows:
                        out[code] = cached_rows
                        continue
                except Exception:
                    pass
        try:
            rows = get_constituents(code, refresh=refresh)
            if rows:
                out[code] = rows
        except Exception as exc:
            logger.warning("cons %s failed: %s", code, exc)
        # 行业间 sleep (随机 0.5-1.5x)
        if inter_industry_sleep > 0:
            time.sleep(inter_industry_sleep * random.uniform(0.5, 1.5))
    return out


# =============================================================================
# 顶层: 一次拿三块
# =============================================================================
def build_industry_payload() -> dict[str, Any]:
    listing = get_industry_list()
    items: list[dict[str, Any]] = []
    for code, info in listing.items():
        name = info["name"]
        kv = get_industry_info(name) or {}
        kvs = kv.get("kvs") or {}
        items.append({
            "code":         code,
            "name":         name,
            "lastPrice":    _to_float(kvs.get("最新")),
            "openPrice":    _to_float(kvs.get("今开")),
            "highPrice":    _to_float(kvs.get("最高")),
            "lowPrice":     _to_float(kvs.get("最低")),
            "change":       _to_float(kvs.get("涨跌额")),
            "changePercent":_to_float(kvs.get("涨跌幅")),
            "volume":       _to_float(kvs.get("成交量(万手)")),
            "amount":       _to_float(kvs.get("成交额(亿)")),
            "turnoverRate": _to_float(kvs.get("换手率")),
            "amplitude":    _to_float(kvs.get("振幅")),
        })
    return {
        "ok": True, "kind": "akshare.ths_industry", "label": "行业 (同花顺)",
        "count": len(items), "items": items,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare.stock_board_industry_*_ths",
    }
