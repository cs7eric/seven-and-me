"""basic.10jqka.com.cn 302 主页 HTML 找资金流."""
import urllib.request, re
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://basic.10jqka.com.cn/"),
]
resp = opener.open("https://basic.10jqka.com.cn/302/600519/", timeout=15)
body = resp.read().decode("gb18030", errors="ignore")
with open("backend/scripts/_basic_600519.html", "w", encoding="utf-8") as f:
    f.write(body)
# 找 资金/净额/流入/流出/主力 相关字段
for kw in ("资金", "净额", "流入", "流出", "主力", "大单", "中单", "小单", "流", "fund", "net", "inflow", "outflow"):
    for m in list(re.finditer(rf".{{0,80}}{kw}.{{0,160}}", body))[:3]:
        snippet = m.group(0)[:200].replace("\n", " ")
        print(f" [{kw}]", snippet)
