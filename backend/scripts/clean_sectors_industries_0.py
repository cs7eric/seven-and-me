"""
清理 sectors_industries_0.json 的脏数据.

历史脏数据来源: eltdx v1.0.2 不返回 industry 字段 (helpers.stock_topics 没有 industry,
category_raw=0 行业分类基本是空), 旧版 sharded/refresh 直接拿 topics[0].reason
整段塞进 s.get("industry"), 然后 aggregate_sectors 又把这种脏 industry 当 sector.name
写进 sectors_industries_0.json. 3040 个 sector 里 ~1453 是 reason 脏 sector.

过滤规则 (按用户拍板):
  1. stock_count < 3  → 拒 (散 sector)
  2. name 含 reason 关键词  → 拒 ("业务/主营/研发/产品/服务/...")
  3. name 长度 > 10  → 拒 (reason 整段被塞进来都偏长)
  4. 无 topic_id  → 拒 (拿不到板块自身涨跌幅)

输出: sectors_industries_0.json (覆盖) + index.json (更新 sector_count)

用法: python backend/scripts/clean_sectors_industries_0.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTORS_DIR = ROOT / "reference" / "stock-universe" / "sectors"
INDUSTRIES_FILE = SECTORS_DIR / "sectors_industries_0.json"
INDEX_FILE = SECTORS_DIR / "index.json"

# reason 整段通常以这些词开头
_REASON_KEYWORDS = (
    "业务", "主营", "产品", "研发", "服务", "涉及", "聚焦", "用于", "提供",
    "生产", "设计", "销售", "管理", "咨询", "成立于", "公司为", "公司是", "公司属",
    "公司主", "公司以", "公司从", "公司致", "公司向", "公司致", "公司致",
)
_MAX_NAME_LEN = 10
_MIN_STOCK_COUNT = 3
_NAME_BLACKLIST_RE = re.compile("|".join(map(re.escape, _REASON_KEYWORDS)))


def is_dirty(name: str, stock_count: int, has_topic_id: bool) -> str | None:
    """返回脏数据的原因 (None 表示干净)."""
    if stock_count < _MIN_STOCK_COUNT:
        return f"stock_count<{_MIN_STOCK_COUNT}"
    if not has_topic_id:
        return "no_topic_id"
    if len(name) > _MAX_NAME_LEN:
        return f"name_len>{_MAX_NAME_LEN}"
    if _NAME_BLACKLIST_RE.search(name):
        return "name_has_reason_keyword"
    return None


def main() -> int:
    if not INDUSTRIES_FILE.exists():
        print(f"ERR: {INDUSTRIES_FILE} 不存在")
        return 1

    data = json.loads(INDUSTRIES_FILE.read_text(encoding="utf-8"))
    sectors = data.get("sectors", [])
    print(f"原始: {len(sectors)} 个 sector")

    keep: list[dict] = []
    reasons: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    for s in sectors:
        name = s.get("name", "")
        sc = s.get("stock_count", 0)
        tid = s.get("topic_id")
        reason = is_dirty(name, sc, bool(tid))
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            samples.setdefault(reason, []).append(name)
            continue
        keep.append(s)

    print(f"保留: {len(keep)} 个 sector")
    print()
    print("拒绝原因分布:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:30s}  {c:5d}  样例: {samples[r][:3]}")
    print()

    # 写回 sectors_industries_0.json
    data["sectors"] = keep
    data["cleaned_at"] = "2026-06-07"
    data["cleaned_filter"] = {
        "min_stock_count": _MIN_STOCK_COUNT,
        "max_name_len": _MAX_NAME_LEN,
        "reason_keywords": list(_REASON_KEYWORDS),
        "rejected_reasons": reasons,
    }
    INDUSTRIES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写回: {INDUSTRIES_FILE}")

    # 更新 index.json
    if INDEX_FILE.exists():
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if "categories" in idx and "0" in idx["categories"]:
            idx["categories"]["0"]["sector_count"] = len(keep)
            idx["fetched_at"] = "2026-06-07 (cleaned)"
        INDEX_FILE.write_text(
            json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已更新: {INDEX_FILE} (sector_count → {len(keep)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
