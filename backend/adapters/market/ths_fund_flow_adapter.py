"""同花顺 data.10jqka.com.cn 全行业主力资金动向适配器 (hexin-v 加密破解).

严格按 CSDN 2026-06-03 教程
  https://blog.csdn.net/weixin_73631017/article/details/161661381
  复刻 + 工程化:

  1. py_mini_racer.MiniRacer() 加载 akshare 内置的 ``ths.js`` (akshare 自动维护最新版)
  2. ``js_code.call('v')`` 生成 hexin-v 加密参数
  3. ``requests.get`` 带 hexin-v + Referer 头, 走 https://data.10jqka.com.cn/funds/hyzjl/cate/3/page/{n}/
  4. BeautifulSoup 抠 ``<span class="page_info">`` 总页数
  5. 循环每一页, 重新建 MiniRacer 拿新 hexin-v (每页都换, 避免过期)
  6. ``pd.read_html`` 解析表格 -> DataFrame
  7. 收尾 ``dropna(how='all')`` + drop ``序号`` 列 + 列名归一化 (新页 11 列 -> guide 10 列)

工程化调整:
  - URL 切到 10jqka 2026-03 改版后的新页 (旧 hyzj1 路径 404), JS / hexin-v / Referer 全流程保留
  - 每页新建 MiniRacer (跟 guide 一致; 单例是项目原方案, 这里改回 guide 行为)
  - 列名归一化: 新页多一个"行业指数"列 + "涨跌幅"列重名, pandas 改名 ``涨跌幅.1``;
    adapter 把表头改回 guide 原口径 (10 列), 前后端契约不变
  - 最终把 DataFrame 转 ``list[dict]`` 给 API 用, 落盘 JSON
  - 失败/限流: 单页失败 ``continue`` 不中断; 全部失败返空 dict
  - 依赖全部走 ``try import`` 软依赖, 缺包给清晰报错

字段口径 (跟 guide 一致, 对外契约 10 列):
  序号, 行业, 行业指数涨跌幅, 流入资金(亿), 流出资金(亿), 净额(亿),
  公司家数, 领涨股, 领涨股涨跌幅, 当前价(元)
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

# 软依赖: 缺包给清晰报错, 不让 import 阶段崩
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

try:
    from akshare.utils.tqdm import get_tqdm
    _TQDM_AVAILABLE = True
except ImportError:
    get_tqdm = None  # type: ignore[assignment]
    _TQDM_AVAILABLE = False


# ---------------------------------------------------------------------------
# 常量
#
# 10jqka 行业资金页 URL 在 2026-03 改版: ``hyzj1`` -> ``hyzjl/cate/3``,
# 其它反爬 / JS 加密 / Referer / User-Agent 都跟 guide 原文一致.
# 即:
#   guide 原 URL (404): http://data.10jqka.com.cn/funds/hyzj1/field/tradezdf/order/desc/page/{n}/
#   现网新 URL (200): https://data.10jqka.com.cn/funds/hyzjl/cate/3/page/{n}/
# 字段口径同步更新: 新页表头是 11 列 (多一个独立的"行业指数"列, "涨跌幅"出现两次);
# adapter 在 pandas 之后做一次列名归一化, 对外保持跟 guide 一致的 10 列口径.
# ---------------------------------------------------------------------------
_BASE_URL: Final[str] = "https://data.10jqka.com.cn/funds/hyzjl/cate/3/page/{page}/"
_HOST: Final[str] = "data.10jqka.com.cn"
_REFERER: Final[str] = "https://data.10jqka.com.cn/funds/hyzjl/cate/3/"
_UA: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT: Final[int] = 10
_PAGE_SLEEP: Final[float] = 0.4  # 翻页间隔, 避免触发反爬限流


# ---------------------------------------------------------------------------
# JS 加密 (跟 guide 原文一致: 每页新建 MiniRacer, 重新跑 v())
# ---------------------------------------------------------------------------
def _get_ths_js_text(file: str = "ths.js") -> str:
    if not _AKSHARE_AVAILABLE:
        raise RuntimeError("akshare 未安装, pip install akshare")
    path = get_ths_js(file)
    with open(path, encoding="utf-8") as fp:
        return fp.read()


def _new_js_engine_with_v() -> str:
    """按 guide 原文: 每次新建 MiniRacer, 加载 ths.js, 调 v() 拿 hexin-v."""
    if not _MINI_RACER_AVAILABLE:
        raise RuntimeError("py_mini_racer 未安装, pip install py-mini-racer")
    engine = py_mini_racer.MiniRacer()
    engine.eval(_get_ths_js_text("ths.js"))
    return str(engine.call("v"))


# ---------------------------------------------------------------------------
# HTTP 工具 (headers 跟 guide 1:1)
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


def _http_get(page: int, hexin_v: str) -> str:
    if not _REQUESTS_AVAILABLE:
        raise RuntimeError("requests 未安装, pip install requests")
    url = _BASE_URL.format(page=page)
    headers = _build_headers(hexin_v)
    resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    # 10jqka 行业页默认 gbk 解码
    return resp.content.decode("gbk", errors="replace")


# ---------------------------------------------------------------------------
# HTML 解析
# ---------------------------------------------------------------------------
def _extract_total_pages(html: str) -> int:
    """跟 guide 原文: ``<span class="page_info">1 / 18</span>`` 抠总页数."""
    if not _BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 未安装, pip install beautifulsoup4")
    soup = BeautifulSoup(html, features="lxml")
    page_info = soup.find(name="span", attrs={"class": "page_info"})
    if not page_info or not page_info.text:
        return 0
    try:
        return int(page_info.text.split("/")[1])
    except (TypeError, ValueError, IndexError):
        return 0


def _to_python(value: Any) -> Any:
    """DataFrame cell -> JSON-friendly Python 原生类型 (numpy.float64 -> float 之类)."""
    if value is None:
        return None
    # numpy scalar 兼容
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    if isinstance(value, float):
        # NaN -> None
        return value if value == value else None
    return value


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------
@dataclass
class FundFlowPage:
    page: int
    total_pages: int
    rows: list[dict[str, Any]]
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "totalPages": self.total_pages,
            "rows": self.rows,
            "fetchedAt": self.fetched_at,
        }


def fetch_industry_fund_flow_page(page: int = 1) -> FundFlowPage:
    """拉单页 (走 guide 流程)."""
    if not _PANDAS_AVAILABLE:
        raise RuntimeError("pandas 未安装, pip install pandas")
    hexin_v = _new_js_engine_with_v()
    html = _http_get(page=page, hexin_v=hexin_v)
    total_pages = _extract_total_pages(html)
    df = pd.read_html(StringIO(html))[0]
    rows = df.to_dict(orient="records")
    rows = [{k: _to_python(v) for k, v in row.items()} for row in rows]
    return FundFlowPage(
        page=page,
        total_pages=total_pages,
        rows=rows,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
    )


def fetch_industry_fund_flow_all(
    *,
    page_sleep: float = _PAGE_SLEEP,
    max_pages: int | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    """拉全量行业主力资金 (按 guide 流程).

    Args:
        page_sleep: 翻页间隔 (秒)
        max_pages:  最大页数 (测试用, None=全量)
        progress:   可选进度回调 ``progress(page, total_pages)``; 不阻塞
    """
    if not _PANDAS_AVAILABLE:
        raise RuntimeError("pandas 未安装, pip install pandas")

    # ---------------- 第 1 页: 拿总页数 (跟 guide 一致) ----------------
    first_hexin_v = _new_js_engine_with_v()
    first_html = _http_get(page=1, hexin_v=first_hexin_v)
    page_num = _extract_total_pages(first_html)
    if page_num <= 0:
        logger.warning("fund flow: 未获取到总页数, 返空")
        return {
            "totalPages": 0,
            "pageRowCounts": [],
            "fetchedAt": datetime.now().isoformat(timespec="seconds"),
            "rowCount": 0,
            "rows": [],
        }
    logger.info("fund flow: 共发现 %d 页数据, 开始爬取...", page_num)

    total_pages = page_num
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    # ---------------- 后续页: 跟 guide 一样循环 ----------------
    big_df = pd.DataFrame()
    page_counts: list[int] = []

    def _tqdm():
        if _TQDM_AVAILABLE and get_tqdm is not None:
            return get_tqdm()
        # fallback: 无 tqdm 时给个简单 range
        class _NoopTqdm:
            def __call__(self, iterable, **kwargs):
                return iterable
        return _NoopTqdm()

    rng = _tqdm()(range(1, total_pages + 1), leave=False)
    for page in rng:
        if page == 1:
            # 第 1 页已经拉过, 直接复用
            current_html = first_html
        else:
            time.sleep(page_sleep)
            try:
                # 每页重新生成 hexin-v (跟 guide 一致)
                v = _new_js_engine_with_v()
                current_html = _http_get(page=page, hexin_v=v)
            except Exception as exc:
                logger.warning("fund flow page %d failed: %s", page, exc)
                page_counts.append(0)
                if progress is not None:
                    progress(page, total_pages)
                continue
        try:
            temp_df = pd.read_html(StringIO(current_html))[0]
            big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
            page_counts.append(len(temp_df))
        except Exception as exc:
            logger.warning("fund flow page %d parse failed: %s", page, exc)
            page_counts.append(0)
        if progress is not None:
            progress(page, total_pages)

    # ---------------- 数据清洗 (跟 guide 一致) ----------------
    big_df = big_df.dropna(axis=1, how="all")
    if "序号" in big_df.columns:
        big_df = big_df.drop(columns=["序号"])

    # ---------------- 列名归一化 (适配 10jqka 2026-03 改版后的新页) ----------------
    # 新页 11 列: 序号/行业/行业指数/涨跌幅/流入资金(亿)/流出资金(亿)/净额(亿)/
    #              公司家数/领涨股/涨跌幅(领涨股)/当前价(元)
    # pandas 把重复的"涨跌幅"自动改成 "涨跌幅.1"; 我们手动归一化回 guide 原文 10 列:
    #   drop 行业指数 (要 % 不要指数值)
    #   涨跌幅    -> 行业指数涨跌幅
    #   涨跌幅.1  -> 领涨股涨跌幅
    # 旧页 (guide 原文) 没有这些列, dropna + rename 全部 no-op, 不影响.
    if "行业指数" in big_df.columns:
        big_df = big_df.drop(columns=["行业指数"])
    if "涨跌幅" in big_df.columns:
        big_df = big_df.rename(columns={"涨跌幅": "行业指数涨跌幅"})
    if "涨跌幅.1" in big_df.columns:
        big_df = big_df.rename(columns={"涨跌幅.1": "领涨股涨跌幅"})
    # 二次保险: 如果旧页直接就是 行业指数涨跌幅 + 领涨股涨跌幅, 也不冲突, 自然通过.

    # 排序: 按"净额(亿)" desc, 然后按"行业指数涨跌幅" desc (净额 desc 同花顺首页默认)
    sort_cols: list[str] = []
    if "净额(亿)" in big_df.columns:
        sort_cols.append("净额(亿)")
    if "行业指数涨跌幅" in big_df.columns:
        sort_cols.append("行业指数涨跌幅")
    if sort_cols:
        big_df = big_df.sort_values(by=sort_cols, ascending=[False] * len(sort_cols), na_position="last")
        big_df = big_df.reset_index(drop=True)

    # 序号列重生成 (1..N)
    big_df.insert(0, "序号", range(1, len(big_df) + 1))

    rows = big_df.to_dict(orient="records")
    rows = [{k: _to_python(v) for k, v in row.items()} for row in rows]

    logger.info("fund flow: 爬取完成, 共获取 %d 个行业的资金数据", len(rows))
    return {
        "totalPages": page_num,
        "pageRowCounts": page_counts,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "rowCount": len(rows),
        "rows": rows,
    }
