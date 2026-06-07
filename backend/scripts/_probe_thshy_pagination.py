"""找同花顺行业详情页的 ajax 成分股分页 URL."""
import urllib.request, re, json

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
    ("Accept-Language", "zh-CN,zh;q=0.9"),
]

# 1. 主页面找 ajax / jsonp / loadMore / page
url = "https://q.10jqka.com.cn/thshy/detail/code/881121/"
body = opener.open(url, timeout=15).read().decode("gb18030", errors="replace")

print("=== page len", len(body))
# 找含 page= / pageSize= / index= / pageNum= / 1/1 形式的路径
for m in re.findall(r"['\"](/[a-zA-Z0-9_/\.\-]*?(?:page|Page|loadMore|stocklist|stockList|constituent|ajax|api)[a-zA-Z0-9_/\.\-]*?)['\"]", body)[:30]:
    print(" ajax:", m[:200])

# 找 window.xxx 变量
for m in re.findall(r"(?:var\s+|window\.)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*", body)[:50]:
    if any(k in m.lower() for k in ("stock", "page", "code", "ajax", "url", "api")):
        print(" var:", m)

# 找 script src
print("---script srcs---")
for m in re.findall(r"src=['\"]([^'\"]+)['\"]", body)[:30]:
    if any(k in m for k in ("jqka", "thsi", "webHQ", "component", "thshy", "stock")):
        print(" script:", m[:200])

# 找 onclick / href 中的 ajax 调用
print("---onclick / loadMore---")
for m in re.findall(r"(onclick|href|loadMore|page)\s*=\s*['\"]([^'\"]{1,300})['\"]", body)[:30]:
    if any(k in m[1] for k in ("/ajax", "/api", "/thshy", "loadMore", "page", "/stock", "constituent")):
        print(" ", m[0], "=", m[1][:200])

# 找 page= 数字
print("---page= 数字---")
for m in re.findall(r"page[A-Za-z]*\s*[=:]\s*['\"]?(\d+)", body)[:20]:
    print(" page=", m)

# 把页面分块找 "成" / "页" 关键字
print("---翻页/分页关键字---")
for kw in ("下一页", "上一页", "翻页", "loadMore", "showMore", "nextPage", "pageSize"):
    for m in re.findall(rf".{{0,80}}{kw}.{{0,160}}", body, re.IGNORECASE)[:2]:
        print(f" [{kw}]", m[:200].replace("\n", " "))
