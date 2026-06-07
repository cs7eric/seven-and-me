"""挖 wapa.min.js + 其它."""
import urllib.request, re

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
]
# 行业内 概 + 排行 + ajax, 试常见路径
urls = [
    "http://q.10jqka.com.cn/thshy/detail/code/881121/",
]
for u in urls:
    body = opener.open(u, timeout=15).read().decode("gb18030", errors="ignore")
    # 找 ths 后台接口 / Service / doAction
    for m in list(re.finditer(r"['\"]([^'\"]+(?:stocklist|stockList|stockListIn|constituents|stockIn|hy\s|ajax[^'\"]*|q.\.10jqka\.com\.cn[^'\"]*\.json[^'\"]*))['\"]", body))[:30]:
        if m.group(1) and "/" in m.group(1):
            print(" api:", m.group(1)[:200])
    # ths_js 后台接口可能 base64 / unicode escape, 也找 _url / dataUrl / api
    for m in list(re.finditer(r"(?:\.post|\.get|ajax|jsonp)\s*\(\s*['\"]([^'\"]+)['\"]", body))[:30]:
        print(" ajax:", m.group(1)[:200])
    # 直接查 .json 路径
    for m in list(re.finditer(r"['\"]([^'\"]*\.json[^'\"]*)['\"]", body))[:30]:
        print(" json:", m.group(1)[:200])
    # 试查 thscommon
    for m in list(re.finditer(r"['\"]([^'\"]*thscommon[^'\"]*)['\"]", body))[:20]:
        print(" thscommon:", m.group(1)[:200])
