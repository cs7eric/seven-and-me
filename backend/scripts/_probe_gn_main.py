"""下 gn_main_v3.js 找 ajax URL."""
import urllib.request, re

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
]
urls = [
    "https://s.thsi.cn/js/q/newq/gn_main_v3.js",
    "https://s.thsi.cn/js/q/newq/gn_main.js",
]
for u in urls:
    try:
        body = opener.open(u, timeout=15).read().decode("utf-8", errors="ignore")
        print(f"=== {u} len={len(body)}")
        # 找 changePage / getStockList / loadPage / gn_ajax
        for m in re.finditer(r"(changePage|getStockList|loadPage|gnAjax|gn_data|ajax|getStockIn|loadMore|stocksIn|getIndustryStocks)", body):
            s = max(0, m.start() - 60)
            e = min(len(body), m.end() + 200)
            print(f"  [{m.group(1)}] {body[s:e].replace(chr(10),' ')[:260]}")
        # 找 URL
        for m in list(re.finditer(r"https?://[a-zA-Z0-9.\-/]+\?(?:[^'\"\s]*)?", body))[:30]:
            print("  url:", m.group(0)[:200])
    except Exception as e:
        print(u, "err", e)
