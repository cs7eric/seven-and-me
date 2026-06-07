"""试常见同花顺 ajax URL 模式."""
import urllib.request, json

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/thshy/detail/code/881121/"),
    ("Accept", "*/*"),
    ("X-Requested-With", "XMLHttpRequest"),
]
guesses = [
    "https://q.10jqka.com.cn/thshy/detail/code/881121/?page=2",
    "https://q.10jqka.com.cn/thshy/ajax/881121/2/",
    "https://q.10jqka.com.cn/thshy/ajax/index/code/881121/page/2/",
    "https://q.10jqka.com.cn/ajax/thshy/code/881121/page/2/",
    "http://q.10jqka.com.cn/thshy/detail/code/881121/?page=2",
    "https://q.10jqka.com.cn/gn/detail/code/881121/?page=2",  # 概念页 URL
    "https://d.10jqka.com.cn/v4/line/bk_881121/01/2026.js",  # K 线
    "https://d.10jqka.com.cn/v4/stock/bk_881121.js",         # 成分股?
    "https://d.10jqka.com.cn/v4/stock/881121.js",
    "https://d.10jqka.com.cn/v4/bk/881121.js",
    "https://d.10jqka.com.cn/v4/line/bk_881121/constituents.js",
    "https://q.10jqka.com.cn/thshy/data/code/881121/",
    "https://q.10jqka.com.cn/thshy/data/code/881121/?page=2",
    "https://d.10jqka.com.cn/v4/line/bk_881121/01/2026.js?type=stocklist",
]
for u in guesses:
    try:
        resp = opener.open(u, timeout=8)
        body = resp.read().decode("utf-8", errors="ignore")[:600]
        print(f"\n[200] {u}\n     {body[:300]}")
    except Exception as e:
        print(f"[err] {u}  {str(e)[:80]}")
