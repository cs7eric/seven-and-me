"""验证 ?page=2 真切到了不同成分股."""
import urllib.request, re

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://q.10jqka.com.cn/"),
]

def get_codes(page):
    url = f"https://q.10jqka.com.cn/thshy/detail/code/881121/?page={page}"
    body = opener.open(url, timeout=15).read().decode("gb18030", errors="ignore")
    # 找 page_info
    m = re.search(r'<span class="page_info">(\d+/\d+)</span>', body)
    info = m.group(1) if m else "?"
    codes = re.findall(r"stockpage\.10jqka\.com\.cn/(\d{6})", body)
    return info, codes

for p in (1, 2, 3, 9):
    info, codes = get_codes(p)
    print(f"page {p:>2d}  {info}  rows={len(codes)}  first={codes[:5]}  last={codes[-3:] if len(codes)>=3 else []}")
