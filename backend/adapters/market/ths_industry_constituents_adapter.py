"""同花顺 q.10jqka.com.cn 行业成分股适配器 (hexin-v 加密破解).

数据源: https://q.10jqka.com.cn/thshy/detail/code/{code}/
反爬: 请求头必须带 ``hexin-v``, 由 ``ths.js`` 里的 ``v()`` 函数动态生成
JS 引擎: py_mini_racer (py-mini-racer 0.6.0, 嵌入 V8)
JS 文件: ``akshare.datasets.get_ths_js("ths.js")`` (akshare 自动维护最新版)
表头 (14 列):
  序号, 代码, 名称, 现价, 涨跌幅(%), 涨跌, 涨速(%), 换手(%), 量比,
  振幅(%), 成交额, 流通股, 流通市值, 市盈率
分页: <span class="page_info">N/M</span> (单页 20 只)

公开接口:
- ``fetch_industry_constituents_page(code, page)``        -> 单页
- ``fetch_industry_constituents_all(code, ...)``           -> 全分页合并

字段口径 (跟 pandas 解析结果对齐, 中文表头):
  序号, 代码, 名称, 现价, 涨跌幅(%), 涨跌, 涨速(%), 换手(%), 量比,
  振幅(%), 成交额, 流通股, 流通市值, 市盈率
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any, Final

logger = logging.getLogger(__name__)

# 软依赖
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]
    _BS4_AVAILABLE = False

try:
    import py_mini_racer
    _MINI_RACER_AVAILABLE = True
except ImportError:
    py_mini_racer = None  # type: ignore[assignment]
    _MINI_RACER_AVAILABLE = False

try:
    from akshare.datasets import get_ths_js  # noqa: F401
    _AKSHARE_AVAILABLE = True
except ImportError:
    get_ths_js = None  # type: ignore[assignment]
    _AKSHARE_AVAILABLE = False

try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    _PANDAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# 常量 (跟 ths_fund_flow_adapter 一致的 hexin-v 流程, 域名换成 q.10jqka)
# ---------------------------------------------------------------------------
_BASE_URL: Final[str] = "https://q.10jqka.com.cn/thshy/detail/code/{code}/page/{page}/"
_HOST: Final[str] = "q.10jqka.com.cn"
_REFERER: Final[str] = "https://q.10jqka.com.cn/thshy/"
_UA: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT: Final[int] = 10
_PAGE_SLEEP: Final[float] = 0.4  # 翻页间隔, 跟 ths_fund_flow 一致


# ---------------------------------------------------------------------------
# JS 加密 (跟 ths_fund_flow 一致: 每页新建 MiniRacer, 调 v())
# ---------------------------------------------------------------------------
def _get_ths_js_text(file: str = "ths.js") -> str:
    if not _AKSHARE_AVAILABLE:
        raise RuntimeError("akshare 未安装, pip install akshare")
    path = get_ths_js(file)
    with open(path, encoding="utf-8") as fp:
        return fp.read()


def _new_js_engine_with_v() -> str:
    """每页新建 MiniRacer, 加载 ths.js, 调 v() 拿 hexin-v."""
    if not _MINI_RACER_AVAILABLE:
        raise RuntimeError("py_mini_racer 未安装, pip install py-mini-racer")
    engine = py_mini_racer.MiniRacer()
    engine.eval(_get_ths_js_text("ths.js"))
    return str(engine.call("v"))


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------
def _build_headers(hexin_v: str) -> dict[str, str]:
    return {
        "Accept": "text/html,*/*;q=0.01",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "hexin-v": hexin_v,
        "Host": _HOST,
        "Pragma": "no-cache",
        "Referer": _REFERER,
        "User-Agent": _UA,
    }


def _http_get(code: str, page: int, hexin_v: str) -> str:
    if not _REQUESTS_AVAILABLE:
        raise RuntimeError("requests 未安装, pip install requests")
    url = _BASE_URL.format(code=code, page=page)
    headers = _build_headers(hexin_v)
    resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    # q.10jqka 行业详情页默认 gbk
    return resp.content.decode("gbk", errors="replace")


# ---------------------------------------------------------------------------
# HTML 解析
# ---------------------------------------------------------------------------
def _extract_total_pages(html: str) -> int:
    """<span class="page_info">N / M</span> 抠总页数. 没有则 1."""
    if not _BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 未安装, pip install beautifulsoup4")
    soup = BeautifulSoup(html, features="lxml")
    page_info = soup.find(name="span", attrs={"class": "page_info"})
    if not page_info or not page_info.text:
        return 1
    try:
        return int(page_info.text.split("/")[1])
    except (TypeError, ValueError, IndexError):
        return 1


def _to_python(value: Any) -> Any:
    """DataFrame cell -> JSON-friendly Python 原生类型."""
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    if isinstance(value, float):
        return value if value == value else None
    return value


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------
@dataclass
class ConstituentsPage:
    code: str
    page: int
    total_pages: int
    rows: list[dict[str, Any]]
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "page": self.page,
            "totalPages": self.total_pages,
            "rows": self.rows,
            "fetchedAt": self.fetched_at,
        }


def fetch_industry_constituents_page(code: str, page: int = 1) -> ConstituentsPage:
    """拉单行业单页 (走 hexin-v 流程)."""
    if not _PANDAS_AVAILABLE:
        raise RuntimeError("pandas 未安装, pip install pandas")
    hexin_v = _new_js_engine_with_v()
    html = _http_get(code=code, page=page, hexin_v=hexin_v)
    total_pages = _extract_total_pages(html)
    df = pd.read_html(StringIO(html))[0]
    rows = list(df.to_dict(orient="records"))
    rows = [{k: _to_python(v) for k, v in row.items()} for row in rows]
    return ConstituentsPage(
        code=code,
        page=page,
        total_pages=total_pages,
        rows=rows,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
    )


def fetch_industry_constituents_all(
    code: str,
    *,
    page_sleep: float = _PAGE_SLEEP,
    max_pages: int | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    """拉单行业全分页, 去重 (按 code 6 位) 合并.

    Args:
        code: 行业 6 位代码, e.g. "881268" (工程机械)
        page_sleep: 翻页间隔
        max_pages: 最大页数 (测试用, None=全量)
        progress: 进度回调 ``progress(page, total_pages)``
    """
    if not _PANDAS_AVAILABLE:
        raise RuntimeError("pandas 未安装, pip install pandas")

    # 第 1 页: 拿总页数
    first_hexin_v = _new_js_engine_with_v()
    first_html = _http_get(code=code, page=1, hexin_v=first_hexin_v)
    total_pages = _extract_total_pages(first_html)
    if total_pages <= 0:
        logger.warning("constituents %s: 未获取到总页数, 返空", code)
        return {
            "code": code,
            "totalPages": 0,
            "pageRowCounts": [],
            "fetchedAt": datetime.now().isoformat(timespec="seconds"),
            "rowCount": 0,
            "rows": [],
        }
    logger.info("constituents %s: 共 %d 页, 开始爬取...", code, total_pages)

    pages_to_crawl = total_pages
    if max_pages is not None:
        pages_to_crawl = min(total_pages, max_pages)

    big_df = pd.DataFrame()
    page_counts: list[int] = []

    for page in range(1, pages_to_crawl + 1):
        if page == 1:
            current_html = first_html
        else:
            time.sleep(page_sleep)
            try:
                v = _new_js_engine_with_v()
                current_html = _http_get(code=code, page=page, hexin_v=v)
            except Exception as exc:
                logger.warning("constituents %s page %d failed: %s", code, page, exc)
                page_counts.append(0)
                if progress is not None:
                    progress(page, pages_to_crawl)
                continue
        try:
            temp_df = pd.read_html(StringIO(current_html))[0]
            big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
            page_counts.append(len(temp_df))
        except Exception as exc:
            logger.warning("constituents %s page %d parse failed: %s", code, page, exc)
            page_counts.append(0)
        if progress is not None:
            progress(page, pages_to_crawl)

    # 数据清洗
    big_df = big_df.dropna(axis=1, how="all")
    if "序号" in big_df.columns:
        big_df = big_df.drop(columns=["序号"])

    # 去重 (按 代码 6 位)
    if "代码" in big_df.columns:
        big_df = big_df.drop_duplicates(subset=["代码"], keep="first")
    big_df = big_df.reset_index(drop=True)

    # 重新生成 序号 1..N
    if len(big_df) > 0:
        big_df.insert(0, "序号", range(1, len(big_df) + 1))

    rows = list(big_df.to_dict(orient="records"))
    rows = [{k: _to_python(v) for k, v in row.items()} for row in rows]

    logger.info("constituents %s: 爬取完成, 共 %d 只", code, len(rows))
    return {
        "code": code,
        "totalPages": total_pages,
        "pageRowCounts": page_counts,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "rowCount": len(rows),
        "rows": rows,
    }
