"""挖 ajax 真实 URL: changePage 事件绑定到哪."""
import urllib.request, re

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
]
url = "https://q.10jqka.com.cn/thshy/detail/code/881121/"
body = opener.open(url, timeout=15).read().decode("gb18030", errors="replace")

# changePage 出现位置附近的代码
for m in re.finditer(r"changePage", body):
    start = max(0, m.start() - 200)
    end = min(len(body), m.end() + 600)
    print(f"--- changePage @ {m.start()} ---")
    print(body[start:end].replace("\n", " ")[:800])
    print()
