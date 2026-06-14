"""一次性脚本: 把 reference/market-overview/archive/*.json 中 6 个 eltdx 字段
重置为 null. 用于在 seed 脚本运行后, 修复 PowerShell 早期误改导致的格式错乱.

⚠️ 仅在重做时运行一次. 正常运行 seed 脚本不会产生此问题.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = REPO / "reference" / "market-overview" / "archive"

ELTDX_FIELDS = [
    "totalAmount", "totalVolume", "stockCount",
    "risingCount", "fallingCount", "flatCount",
    "limitUpCount", "limitDownCount",
]


def main() -> int:
    for path in sorted(ARCHIVE_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8-sig")
        new = text
        for key in ELTDX_FIELDS:
            pat = re.compile(
                r'^(?P<indent>[ \t]*)"' + re.escape(key) + r'"\s*:\s*[^,\n]+(?P<suffix>[,\n])',
                re.MULTILINE,
            )
            new = pat.sub(
                lambda m, k=key: f'{m.group("indent")}"{k}": null{m.group("suffix")}',
                new,
                count=1,
            )
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(f"  reset {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
