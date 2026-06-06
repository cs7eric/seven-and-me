"""
初始化 stock_universe 拉取:
  1. 一次性从 eltdx 拉全 A 股 code+name (1-2 秒)
  2. 写 _codes.json
  3. 按 --shard-size (默认 1000) 拆 groups/0001.json, 0002.json ...
  4. 已存在的 group 不重写 (幂等)

用法:
  python -m backend.scripts.refresh_stock_universe_init
  python -m backend.scripts.refresh_stock_universe_init --shard-size 500
  python -m backend.scripts.refresh_stock_universe_init --reset
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from backend.config.settings import STOCK_UNIVERSE_DIR
from backend.services.stock import stock_universe_service as svc

logger = logging.getLogger(__name__)

CODES_FILE = STOCK_UNIVERSE_DIR / "_codes.json"
GROUPS_DIR = STOCK_UNIVERSE_DIR / "groups"
DEFAULT_SHARD_SIZE = 600


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch_all_codes() -> list[dict[str, str]]:
    """从 eltdx 拉全 A 股 code+name.

    步骤:
      1. c.codes.all 拿 ~50000 个全市场 code+name (含指数/债券/基金)
      2. get_a_share_codes_all 拿权威 A 股 code 集
      3. dedup: set 去重, 显式打印去重数
      4. 交叉: 留 a-share set 里的 code, 用 c.codes.all 补 name
    """
    print(f"[init] 拉全 A 股 code+name (eltdx.codes.all + get_a_share_codes_all 交叉过滤)")
    with svc._connect() as c:
        sh = c.codes.all("sh", page_size=1600)
        sz = c.codes.all("sz", page_size=1600)
        raw_a_share = c.get_a_share_codes_all()
    print(f"  codes.all -> sh={len(sh)} sz={len(sz)} (含指数/债券/基金)")
    print(f"  get_a_share_codes_all -> raw {len(raw_a_share)}")

    # 1) codes.all 内去重 (sh+sz 直接 concat 可能重复)
    name_map: dict[str, str] = {}
    name_dup_count = 0
    for s in sh + sz:
        if not s.full_code or not s.name:
            continue
        key = s.full_code
        if key in name_map:
            name_dup_count += 1
            continue
        name_map[key] = s.name.strip()
    print(f"  codes.all name_map: unique={len(name_map)} (dedup {name_dup_count} 重复)")

    # 2) get_a_share_codes_all 内部去重
    a_share: set[str] = set()
    raw_dup_count = 0
    for c in raw_a_share:
        if c in a_share:
            raw_dup_count += 1
        a_share.add(c)
    print(f"  a_share set: unique={len(a_share)} (dedup {raw_dup_count} 重复)")

    # 3) 交叉: 仅 a-share 集内的 code
    out: list[dict[str, str]] = []
    for full in sorted(a_share):
        out.append({
            "code": full[2:],          # sh600519 -> 600519
            "full_code": full,
            "exchange": full[:2],
            "name": name_map.get(full, ""),
        })
    # 4) 再 dedup by full_code
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    final_dup_count = 0
    for c in out:
        if c["full_code"] in seen:
            final_dup_count += 1
            continue
        seen.add(c["full_code"])
        deduped.append(c)
    if final_dup_count:
        print(f"  WARN: full_code dedup again: 移除 {final_dup_count} 重复")
    out = deduped
    no_name = sum(1 for c in out if not c["name"])
    print(f"  -> 交叉后 {len(out)} 只 A 股, {no_name} 只没 name (后续用 qt 补)")

    # 用 qt.gtimg.cn 补全缺失的 name (500/0.22s, 5530 个 12 次 = ~3s)
    if no_name > 0:
        print(f"[init] 用 qt.gtimg.cn 补 {no_name} 只 name")
        out = _fill_names_via_qt(out)

    return out


def _fill_names_via_qt(codes: list[dict[str, str]]) -> list[dict[str, str]]:
    """qt.gtimg.cn 一次 500/请求, ~0.22s/请求, 5530/500 = 12 次, 3 秒."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("Referer", "https://gu.qq.com/"),
    ]
    # dedup 入参
    by_code: dict[str, dict[str, str]] = {}
    for c in codes:
        by_code[c["full_code"]] = c
    codes = list(by_code.values())
    needs = [c["full_code"] for c in codes if not c["name"]]
    needs = list(dict.fromkeys(needs))  # dedup
    print(f"  qt 补 {len(needs)} 只, 每批 500 ...")
    for i in range(0, len(needs), 500):
        batch = needs[i:i+500]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            resp = opener.open(url, timeout=10)
            body = resp.read().decode("gbk", errors="ignore")
        except Exception as exc:
            print(f"  qt batch {i//500+1} failed: {exc}")
            continue
        for line in body.strip().split(";"):
            if "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 2:
                continue
            key = parts[0].strip().lstrip("v_=")
            name = parts[1].strip()
            if key in by_code and name:
                by_code[key]["name"] = name
        print(f"  qt batch {i//500+1} done")
    return list(by_code.values())


def main():
    parser = argparse.ArgumentParser(description="初始化 stock_universe: 拉 code+name + 分组")
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE,
                        help=f"每组大小, 默认 {DEFAULT_SHARD_SIZE} (5530/600=10 组)")
    parser.add_argument("--reset", action="store_true",
                        help="重新拉全 code (覆盖 _codes.json 和 groups/)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    print(f"=== refresh_stock_universe_init ===")
    print(f"  target: {STOCK_UNIVERSE_DIR}")
    print(f"  shard_size: {args.shard_size}")
    print()

    if args.reset and CODES_FILE.exists():
        CODES_FILE.unlink()
    if args.reset and GROUPS_DIR.exists():
        for f in GROUPS_DIR.glob("*.json"):
            f.unlink()

    if not CODES_FILE.exists() or args.reset:
        t0 = time.time()
        codes = fetch_all_codes()
        # 终末保险: dict by full_code 去重
        final_by_code: dict[str, dict] = {}
        for c in codes:
            fc = c.get("full_code")
            if not fc:
                continue
            if fc in final_by_code:
                # 合并: 已有的用第一个, 缺的 name 从这里补
                if not final_by_code[fc].get("name") and c.get("name"):
                    final_by_code[fc]["name"] = c["name"]
                continue
            final_by_code[fc] = c
        codes = list(final_by_code.values())
        print(f"  -> 去重后 {len(codes)} 只 ({time.time()-t0:.1f}s)")
        _atomic_write(CODES_FILE, {
            "version": 2,
            "trading_day": datetime.now().strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().isoformat(),
            "source": "eltdx.codes.all + get_a_share_codes_all + qt.gtimg.cn",
            "count": len(codes),
            "codes": codes,
        })
        print(f"  -> 写 {CODES_FILE}")
    else:
        data = json.loads(CODES_FILE.read_text(encoding="utf-8"))
        codes = data["codes"]
        print(f"  已存在 {CODES_FILE}, 跳过拉取 (count={data['count']}, --reset 重拉)")

    # 拆组
    GROUPS_DIR.mkdir(parents=True, exist_ok=True)
    n_groups = (len(codes) + args.shard_size - 1) // args.shard_size
    print()
    print(f"[init] 拆 {len(codes)} 只成 {n_groups} 组 (每组 {args.shard_size})")

    # 探测: 旧 group 尺寸 ≠ 当前 shard_size -> 自动 delete groups/ 重写
    if not args.reset:
        first_group = GROUPS_DIR / "0001.json"
        if first_group.exists():
            try:
                old_data = json.loads(first_group.read_text(encoding="utf-8"))
                old_size = old_data.get("shard_size", 0)
                if old_size != args.shard_size:
                    print(f"  [init] 探测到旧 group 尺寸={old_size} ≠ 当前 {args.shard_size}, 自动 delete groups/ 重写")
                    for f in GROUPS_DIR.glob("*.json"):
                        f.unlink()
                    print(f"  [init] cleared groups/ ({old_size} -> {args.shard_size})")
            except Exception:
                pass
    # 防互斥 dedup: 跨 group 不重复同一个 full_code
    used: set[str] = set()
    written = 0
    skipped = 0
    for gi in range(n_groups):
        group_path = GROUPS_DIR / f"{gi+1:04d}.json"
        if group_path.exists() and not args.reset:
            skipped += 1
            # 把已存在组的 code 也登记到 used (防止 reset 部分 group 造成重复)
            try:
                g_data = json.loads(group_path.read_text(encoding="utf-8"))
                for c in g_data.get("codes", []):
                    used.add(c.get("full_code", ""))
            except Exception:
                pass
            continue
        chunk_full = codes[gi*args.shard_size:(gi+1)*args.shard_size]
        # 跳过已被 used 占用 (理论上不会, 但防御性)
        chunk_filtered: list[dict] = []
        for c in chunk_full:
            fc = c.get("full_code", "")
            if fc and fc in used:
                print(f"  WARN: skip {fc} (in earlier group)")
                continue
            chunk_filtered.append(c)
            if fc:
                used.add(fc)
        # 兜底: 末尾一组可能 < shard_size, 不补
        # dedup by full_code 一次保险
        seen: set[str] = set()
        deduped_chunk: list[dict] = []
        for c in chunk_filtered:
            fc = c.get("full_code", "")
            if not fc or fc in seen:
                continue
            seen.add(fc)
            deduped_chunk.append(c)
        _atomic_write(group_path, {
            "version": 1,
            "group_index": gi + 1,
            "total_groups": n_groups,
            "shard_size": args.shard_size,
            "count": len(deduped_chunk),
            "codes": deduped_chunk,
        })
        written += 1
    print(f"  -> 写 {written} 个新组, {skipped} 个已存在, 共 {n_groups} 组")

    # 跨 group dedup 校验
    all_used: set[str] = set()
    dups_cross: list[str] = []
    for gi in range(n_groups):
        gp = GROUPS_DIR / f"{gi+1:04d}.json"
        if not gp.exists():
            continue
        g = json.loads(gp.read_text(encoding="utf-8"))
        for c in g.get("codes", []):
            fc = c.get("full_code", "")
            if fc in all_used:
                dups_cross.append(fc)
            all_used.add(fc)
    if dups_cross:
        print(f"  WARN: 跨组重复 {len(dups_cross)} 个: {dups_cross[:5]}")
    else:
        print(f"  跨组校验: {len(all_used)} unique, 0 重复 [OK]")

    print()
    print(f"OK: {len(codes)} codes, {n_groups} groups of {args.shard_size}")
    print(f"  groups dir: {GROUPS_DIR}")
    print(f"  下一组: {GROUPS_DIR / '0001.json'}")


if __name__ == "__main__":
    sys.exit(main() or 0)
