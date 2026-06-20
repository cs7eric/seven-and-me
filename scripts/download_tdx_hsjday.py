"""下载 TDX hsjday.zip → 解压到临时目录 → 验证 → 原子替换.

URL: https://data.tdx.com.cn/vipdoc/hsjday.zip (~538 MB)

流程 (6 步):
  0. 交易日校验 (腾讯 K 线 API, 非交易日跳过)
  1. 存量检查 (已有最新数据则跳过)
  2. 下载 zip → reference/stock/download/{date}/hsjday.zip
  3. 解压 → reference/tdx/day/hsjday-{date}/  (临时, 旧 hsjday/ 不动)
  4. 验证 .day 文件含目标交易日数据 (失败则清理临时目录, 旧数据完好)
  5. 原子替换: 删旧 hsjday/ → 重命名 hsjday-{date} → hsjday
  6. 清理: 删临时目录, 只保留最近 2 天 zip

用法:
    python scripts/download_tdx_hsjday.py                          # 今天
    python scripts/download_tdx_hsjday.py --date 2026-06-19         # 指定日期
    python scripts/download_tdx_hsjday.py --dry-run                # 只看计划
    python scripts/download_tdx_hsjday.py --skip-download          # 假定 zip 已下好
    python scripts/download_tdx_hsjday.py --skip-trading-day-check # 跳过交易日校验
"""
from __future__ import annotations

import argparse
import json as _json
import logging
import os
import shutil
import struct
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

# data.tdx.com.cn 走 Cloudflare-style JS challenge, 单纯 urlopen/requests 会被挡
# (返回 988B 的 JS 解算页, 不是真 zip). 优先尝试 Playwright 真实浏览器拿 cookie.
# 如果 playwright 没装, 退回到 urllib, 让用户手动下载到 download/{date}/hsjday.zip 后用 --skip-download 触发解压.
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except Exception:
    sync_playwright = None
    _HAS_PLAYWRIGHT = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,  # 必须 stdout: scheduler 从 stdout 解析 JSON 块和错误消息
)
log = logging.getLogger("download_tdx_hsjday")

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_BASE = REPO_ROOT / "reference" / "stock" / "download"
TDX_TARGET = REPO_ROOT / "reference" / "tdx" / "day" / "hsjday"
ZIP_URL = "https://data.tdx.com.cn/vipdoc/hsjday.zip"
CHUNK_SIZE = 1024 * 1024  # 1 MB
PROGRESS_EVERY_BYTES = 50 * 1024 * 1024  # 50 MB

# data.tdx.com.cn 用 JS challenge 挡非浏览器, urllib 拿到的是 988B 的 <script> 页
# 用这个 magic 判断下载是不是被挑战页挡了
_JS_CHALLENGE_MARKERS = (b"<script>", b"function a(a)", b"_0x649a")


def _looks_like_js_challenge(head_bytes: bytes) -> bool:
    return any(m in head_bytes[:2048] for m in _JS_CHALLENGE_MARKERS)


def _download(url: str, dst: Path) -> int:
    """流式下载到 dst. 返回字节数.

    data.tdx.com.cn 用 JS challenge 挡 urllib, 先试 urllib 拿前 4KB 嗅探,
    如果是 JS challenge 就回退到 Playwright 真实浏览器.
    """
    log.info("downloading %s → %s", url, dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # 1) 快速嗅探
    sniff = _sniff(url)
    if sniff and _looks_like_js_challenge(sniff):
        log.warning("urlopen 拿到 JS challenge 页 (%d B), 切换到 Playwright 真实浏览器", len(sniff))
        if not _HAS_PLAYWRIGHT:
            raise RuntimeError(
                "site 走 JS challenge 拦截, 需要 playwright 真实浏览器绕过. "
                "请: pip install playwright && playwright install chromium"
            )
        return _download_via_playwright(url, dst)

    # 2) urlopen 流式下载
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Referer": "https://www.tdx.com.cn/",
    })
    with urlopen(req, timeout=120) as resp, dst.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        t0 = time.time()
        next_log = PROGRESS_EVERY_BYTES
        first_chunk_checked = False
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            # 第一次写盘前再确认不是 challenge
            if not first_chunk_checked:
                first_chunk_checked = True
                if _looks_like_js_challenge(chunk):
                    raise RuntimeError(
                        f"下载的不是 zip (前 {len(chunk)}B 是 JS challenge). "
                        "需要 playwright 真实浏览器绕过"
                    )
            f.write(chunk)
            got += len(chunk)
            if got >= next_log or total and got == total:
                elapsed = time.time() - t0
                rate = got / elapsed if elapsed else 0
                eta = (total - got) / rate if rate and total else 0
                pct = (got / total * 100) if total else 0
                log.info(
                    "  %s / %s  %.1f%%  %.1f MB/s  ETA %ds",
                    _fmt_bytes(got), _fmt_bytes(total) if total else "?",
                    pct, rate / 1024 / 1024, int(eta),
                )
                next_log += PROGRESS_EVERY_BYTES
        elapsed = time.time() - t0
        log.info("  download done: %s in %.1fs (%.1f MB/s)",
                 _fmt_bytes(got), elapsed, got / elapsed / 1024 / 1024 if elapsed else 0)
        return got


def _sniff(url: str) -> bytes | None:
    """GET url 的前 ~4KB, 用于嗅探. None 表示失败."""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Range": "bytes=0-4095",
        })
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def _download_via_playwright_ranges(request_ctx, url: str, total: int, dst: Path, t0: float) -> int:
    """Range 分块下载, 1 MB 每片, 进度打印, 写到 dst.

    `request_ctx` 是 ``ctx.request`` (APIRequestContext), 不是 ``ctx`` 本身.
    """
    chunk_size = 4 * 1024 * 1024  # 4 MB 每片, 平衡请求数和吞吐
    next_log = 50 * 1024 * 1024
    written = 0
    with dst.open("wb") as f:
        while written < total:
            end = min(written + chunk_size - 1, total - 1)
            r = request_ctx.get(
                url,
                headers={"Range": f"bytes={written}-{end}"},
                timeout=60_000,
            )
            if r.status not in (200, 206):
                raise RuntimeError(f"Range GET HTTP {r.status}")
            data = r.body()
            if _looks_like_js_challenge(data[:512]) and written == 0:
                raise RuntimeError("Range 返回 JS challenge, 失败")
            f.write(data)
            written += len(data)
            if written >= next_log or written == total:
                elapsed = time.time() - t0
                rate = written / elapsed if elapsed else 0
                eta = (total - written) / rate if rate else 0
                log.info(
                    "  %s / %s  %.1f%%  %.1f MB/s  ETA %ds",
                    _fmt_bytes(written), _fmt_bytes(total),
                    written / total * 100, rate / 1024 / 1024, int(eta),
                )
                next_log += 50 * 1024 * 1024
    return written


def _download_via_playwright(url: str, dst: Path) -> int:
    """用 Playwright 真实浏览器绕 JS challenge 后下到 dst."""
    log.info("Playwright 启动 chromium, 等待 JS challenge 过...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        # 1) 访问首页, 拿过 challenge 所需的 cookies
        page.goto("https://www.tdx.com.cn/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)  # 等 challenge 跑完

        # 2) 用 browser fetch API 拿 zip (走 browser TLS fingerprint + cookies)
        log.info("浏览器 fetch %s", url)
        t0 = time.time()
        # 注意: Playwright timeout 单位是毫秒, 538MB @ 10MB/s 约 60s, 给 5 min 上限
        resp = ctx.request.get(url, timeout=300_000)
        if resp.status != 200:
            raise RuntimeError(f"browser fetch HTTP {resp.status}: {resp.text()[:200]}")
        # resp.body() 一次性读 538MB 经常卡 OOM / timeout, 改用 Range 分块下载
        total = int(resp.headers.get("content-length") or 0)
        if not total or total < 1024 * 1024:
            # 范围 headers 缺失, 降级到全读 (可能是个错误页)
            body = resp.body()
            if _looks_like_js_challenge(body[:2048]):
                raise RuntimeError(
                    f"浏览器拿到的还是 JS challenge (前 {min(2048, len(body))}B 是 script)"
                )
            dst.write_bytes(body)
            return len(body)
        # Range 分块, 不一次性灌内存
        written = _download_via_playwright_ranges(ctx.request, url, total, dst, t0)
        elapsed = time.time() - t0
        log.info("  playwright download done: %s in %.1fs (%.1f MB/s)",
                 _fmt_bytes(written), elapsed, written / elapsed / 1024 / 1024 if elapsed else 0)
        ctx.close()
        browser.close()
        return written


def _download_via_playwright_ranges(ctx, url: str, total: int, dst: Path, t0: float) -> int:
    """Range 分块下载, 1 MB 每片, 进度打印, 写到 dst."""
    chunk_size = 1024 * 1024  # 1 MB
    next_log = 50 * 1024 * 1024  # 50 MB
    written = 0
    with dst.open("wb") as f:
        while written < total:
            end = min(written + chunk_size - 1, total - 1)
            r = ctx.get(
                url,
                headers={"Range": f"bytes={written}-{end}"},
                timeout=60_000,
            )
            if r.status not in (200, 206):
                raise RuntimeError(f"Range GET HTTP {r.status}")
            data = r.body()
            if _looks_like_js_challenge(data[:512]) and written == 0:
                raise RuntimeError("Range 返回 JS challenge, 失败")
            f.write(data)
            written += len(data)
            if written >= next_log or written == total:
                elapsed = time.time() - t0
                rate = written / elapsed if elapsed else 0
                eta = (total - written) / rate if rate else 0
                log.info(
                    "  %s / %s  %.1f%%  %.1f MB/s  ETA %ds",
                    _fmt_bytes(written), _fmt_bytes(total),
                    written / total * 100, rate / 1024 / 1024, int(eta),
                )
                next_log += 50 * 1024 * 1024
    ctx.parent.browser.close() if hasattr(ctx, "parent") else None
    # 上面 ctx.close() 由外层调用, 这里只返回字节数
    return written


def _extract(zip_path: Path, out_dir: Path) -> int:
    """解压到 out_dir. 返回文件数."""
    log.info("extracting %s → %s", zip_path, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        log.info("  zip has %d entries", len(members))
        for m in members:
            zf.extract(m, out_dir)
            count += 1
            if count % 500 == 0:
                log.info("  extracted %d / %d", count, len(members))
    log.info("  extract done: %d entries in %.1fs", count, time.time() - t0)
    return count


def _find_hsjday_root(extracted: Path) -> Path:
    """在解压目录里找 hsjday/ 实际位置.
    zip 顶层可能是 hsjday/sh/lday/... 也可能是 sh/lday/... (无 hsjday/ 前缀).
    返回内含 sh/sz/bj/lday 的目录.
    """
    # 候选 1: extracted/hsjday/
    cand1 = extracted / "hsjday"
    if cand1.is_dir() and any((cand1 / m / "lday").is_dir() for m in ("sh", "sz", "bj")):
        return cand1
    # 候选 2: extracted/ 本身就是 (sh/lday 在 extracted/sh/lday)
    if any((extracted / m / "lday").is_dir() for m in ("sh", "sz", "bj")):
        return extracted
    # 候选 3: 找最深的 sh/lday/sh*.day 父目录
    sample = next(extracted.rglob("sh*.day"), None)
    if sample:
        # sample = .../hsjday/sh/lday/sh000001.day  →  parent.parent.parent = hsjday
        # 假设 layout 是 <root>/sh/lday/<file>.day
        for ancestor in sample.parents:
            if ancestor.name == "lday":
                return ancestor.parent.parent
    raise FileNotFoundError(f"can't find hsjday root under {extracted}")


# 采样验证用的指数代码 (只校验上证指数 + 深证成指)
_VERIFY_CODES = {
    "sh": ["000001"],   # 上证指数
    "sz": ["399001"],   # 深证成指
}


def _verify_download(hsjday_root: Path, target_date: date) -> dict:
    """验证 .day 文件完整性 + 数据可靠性.

    1) 统计每个市场 (sh/sz/bj) 的 .day 文件数和总字节
    2) 采样关键文件, 读取最后一条记录的日期来判断是否包含 target_date

    stdout 输出 ``[verify]`` 前缀的结构化行, 供 scheduler 解析.
    Returns dict 供程序内判断是否通过.
    """
    result: dict = {
        "ok": True,
        "perMarket": {},
        "samples": [],
        "errors": [],
    }

    # 1) 全量统计
    total_files = 0
    total_bytes = 0
    for market in ("sh", "sz", "bj"):
        lday = hsjday_root / market / "lday"
        if not lday.is_dir():
            log.info("[verify] market=%s 目录不存在, 跳过", market)
            continue
        files = list(lday.glob(f"{market}*.day"))
        market_bytes = sum(p.stat().st_size for p in files)
        n = len(files)
        total_files += n
        total_bytes += market_bytes
        result["perMarket"][market] = {"files": n, "bytes": market_bytes}

        mib = market_bytes / 1024 / 1024
        log.info(
            "[verify] market=%s  files=%d  bytes=%s  (%d MiB)",
            market, n, _fmt_bytes(market_bytes), int(mib),
        )

    log.info("[verify] total files=%d  bytes=%s", total_files, _fmt_bytes(total_bytes))

    # 2) 采样验证
    td_int = target_date.year * 10000 + target_date.month * 100 + target_date.day
    all_ok = True

    for market, codes in _VERIFY_CODES.items():
        lday = hsjday_root / market / "lday"
        for code in codes:
            fp = lday / f"{market}{code}.day"
            if not fp.is_file():
                msg = f"{market}{code}.day 不存在"
                log.warning("[verify] code=%s  %s", f"{market}{code}", msg)
                result["errors"].append(f"{market}{code}: {msg}")
                result["samples"].append({
                    "code": code, "market": market,
                    "ok": False, "error": msg,
                })
                all_ok = False
                continue

            size = fp.stat().st_size
            record_count = size // 32

            # 读第一条和最后一条记录的日期
            first_date_int = None
            last_date_int = None
            first_date_str = None
            last_date_str = None
            try:
                with fp.open("rb") as fh:
                    # 第一条
                    first_raw = fh.read(32)
                    if len(first_raw) == 32:
                        first_date_int = struct.unpack('<I', first_raw[0:4])[0]
                        first_date_str = str(first_date_int)
                    # 最后一条 (seek 到倒数第二个记录)
                    if record_count > 1:
                        fh.seek(-32, 2)
                        last_raw = fh.read(32)
                        if len(last_raw) == 32:
                            last_date_int = struct.unpack('<I', last_raw[0:4])[0]
                            last_date_str = str(last_date_int)
            except Exception as exc:
                msg = f"读取失败: {exc}"
                log.warning("[verify] code=%s  %s", f"{market}{code}", msg)
                result["errors"].append(f"{market}{code}: {msg}")
                result["samples"].append({
                    "code": code, "market": market,
                    "ok": False, "error": msg,
                    "bytes": size, "records": record_count,
                })
                all_ok = False
                continue

            # 判断最后一条记录的日期是否 >= target_date
            date_ok = last_date_int is not None and last_date_int >= td_int
            if not date_ok:
                actual = str(last_date_int) if last_date_int else "N/A"
                msg = f"最后日期={actual} < 目标日期={td_int}"
                log.warning("[verify] code=%s  %s", f"{market}{code}", msg)
                result["errors"].append(f"{market}{code}: {msg}")
                all_ok = False

            log.info(
                "[verify] code=%s  first=%s  last=%s  records=%d  size=%s  ok=%s",
                f"{market}{code}",
                first_date_str or "?",
                last_date_str or "?",
                record_count,
                _fmt_bytes(size),
                "✓" if date_ok else "✗",
            )
            result["samples"].append({
                "code": code,
                "market": market,
                "firstDate": first_date_str,
                "lastDate": last_date_str,
                "records": record_count,
                "bytes": size,
                "ok": date_ok,
            })

    result["ok"] = all_ok
    if not all_ok:
        log.error("[verify] ⚠ 部分采样文件未通过验证, 请检查")
        for err in result["errors"]:
            log.error("  [verify] error: %s", err)
    else:
        log.info("[verify] ✅ 全部采样文件通过验证, 均包含 %s 数据", target_date)
    return result


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ---------------------------------------------------------------------------
# 交易日校验 (腾讯 K 线 API)
# ---------------------------------------------------------------------------
def _check_is_trading_day(target_date: date) -> dict:
    """用腾讯 K 线 API 查 sh000001, 判断 target_date 是否为交易日.

    返回 {"ok": bool, "latestDataDate": str|None, "error": str|None}
    """
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param=sh000001,day,{target_date.isoformat()},,2,qfq"
    )
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://gu.qq.com/",
        })
        with urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "latestDataDate": None, "error": f"API 请求失败: {exc}"}

    try:
        klines = data.get("data", {}).get("sh000001", {})
        # qfqday 或 day 字段
        days = klines.get("qfqday") or klines.get("day") or []
        if not days:
            return {"ok": False, "latestDataDate": None, "error": "K 线数据为空"}

        last = days[-1]
        last_date_str = last[0] if isinstance(last, list) else last.get("date", "")
        if not last_date_str:
            return {"ok": False, "latestDataDate": None, "error": "无法解析日期"}

        last_date = date.fromisoformat(last_date_str)
        is_td = last_date >= target_date
        return {
            "ok": is_td,
            "latestDataDate": last_date_str,
            "error": None if is_td else f"最近 K 线日期={last_date_str} < 目标={target_date.isoformat()}",
        }
    except Exception as exc:
        return {"ok": False, "latestDataDate": None, "error": f"解析响应失败: {exc}"}


# ---------------------------------------------------------------------------
# 存量数据新鲜度检查
# ---------------------------------------------------------------------------
def _check_existing_data_latest(target: Path, target_date: date) -> dict:
    """检查 target (tdx/day/hsjday) 下 .day 文件的最新记录日期.

    返回 {"ok": bool, "latestDate": str|None, "alreadyHaveData": bool}
    """
    if not target.is_dir():
        return {"ok": True, "latestDate": None, "alreadyHaveData": False}

    sample = target / "sh" / "lday" / "sh000001.day"
    if not sample.is_file():
        return {"ok": True, "latestDate": None, "alreadyHaveData": False}

    try:
        size = sample.stat().st_size
        record_count = size // 32
        with sample.open("rb") as fh:
            if record_count > 0:
                fh.seek(-32, 2)
                raw = fh.read(32)
                if len(raw) == 32:
                    last_date_int = struct.unpack('<I', raw[0:4])[0]
                    last_date_str = str(last_date_int)
                    already = last_date_int >= (target_date.year * 10000 + target_date.month * 100 + target_date.day)
                    return {
                        "ok": True,
                        "latestDate": last_date_str,
                        "alreadyHaveData": already,
                    }
    except Exception as exc:
        log.warning("存量数据检查失败: %s", exc)

    return {"ok": True, "latestDate": None, "alreadyHaveData": False}


def _cleanup_old_zips(download_base: Path, keep_days: int = 2) -> None:
    """清理 download_base 下超过 keep_days 天的 zip 文件.

    每个子目录 (YYYY-MM-DD) 下的 hsjday.zip 在对应日期 + keep_days 天后被删除.
    """
    if not download_base.is_dir():
        return
    cutoff = date.today() - timedelta(days=keep_days)
    for child in sorted(download_base.iterdir()):
        if not child.is_dir():
            continue
        try:
            dir_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if dir_date < cutoff:
            zip_file = child / "hsjday.zip"
            if zip_file.exists():
                zip_file.unlink()
                log.info("[cleanup] 删除旧 zip: %s (日期=%s, 保留 %d 天)", zip_file, dir_date, keep_days)
            # 如果目录为空, 一并删除
            if not any(child.iterdir()):
                child.rmdir()
                log.info("[cleanup] 删除空目录: %s", child)


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 TDX hsjday.zip → 覆盖 reference/tdx/day/hsjday")
    ap.add_argument("--date", type=str, default=None,
                    help="目标日期 (默认今天 YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--skip-download", action="store_true",
                    help="跳过下载, 假定 zip 已存在")
    ap.add_argument("--skip-trading-day-check", action="store_true",
                    help="跳过交易日校验")
    args = ap.parse_args()

    d = date.fromisoformat(args.date) if args.date else date.today()
    date_dir = DOWNLOAD_BASE / d.isoformat()
    zip_path = date_dir / "hsjday.zip"
    # 提取到带日期后缀的临时目录
    dated_target = TDX_TARGET.parent / f"hsjday-{d.isoformat()}"

    log.info("date=%s  date_dir=%s", d.isoformat(), date_dir)
    log.info("zip_url=%s  expected_zip=%s", ZIP_URL, zip_path)
    log.info("target=%s  dated_target=%s  dry_run=%s",
             TDX_TARGET, dated_target, args.dry_run)

    if args.dry_run:
        log.info("[dry-run] 不会下载 / 解压 / 替换")
        return 0

    date_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════════════
    # 0) 交易日校验 (腾讯 K 线 API)
    # ═══════════════════════════════════════════════════════════════════
    td_check = {"ok": None, "latestDataDate": None, "checked": False, "error": None}
    if not args.skip_trading_day_check:
        log.info("[step 0] 交易日校验: 目标日期=%s", d.isoformat())
        td_check = _check_is_trading_day(d)
        td_check["checked"] = True
        log.info(
            "---begin-trading-day-json---\n%s\n---end-trading-day-json---",
            _json.dumps(td_check, ensure_ascii=False),
        )
        if not td_check.get("ok"):
            log.warning(
                "[step 0] ⚠ %s 不是交易日 (最近 K 线: %s), 跳过下载",
                d.isoformat(), td_check.get("latestDataDate") or "?",
            )
            return 0  # 非交易日, 正常跳过 (非错误)
        log.info("[step 0] ✓ %s 是交易日 (最近 K 线: %s)", d.isoformat(), td_check.get("latestDataDate"))
    else:
        log.info("[step 0] 交易日校验跳过 (--skip-trading-day-check)")

    # ═══════════════════════════════════════════════════════════════════
    # 1) 存量数据新鲜度检查
    # ═══════════════════════════════════════════════════════════════════
    log.info("[step 1] 存量数据检查: target=%s", TDX_TARGET)
    existing_check = _check_existing_data_latest(TDX_TARGET, d)
    log.info(
        "---begin-existing-data-json---\n%s\n---end-existing-data-json---",
        _json.dumps(existing_check, ensure_ascii=False),
    )
    if existing_check.get("alreadyHaveData"):
        log.info(
            "[step 1] ✓ 存量数据已覆盖 %s (最新=%s), 跳过下载",
            d.isoformat(), existing_check.get("latestDate"),
        )
        return 0  # 已有最新数据, 正常跳过
    log.info(
        "[step 1] 存量数据最新=%s, 目标=%s, 需要下载",
        existing_check.get("latestDate") or "无", d.isoformat(),
    )

    # ═══════════════════════════════════════════════════════════════════
    # 2) 下载
    # ═══════════════════════════════════════════════════════════════════
    download_ok = False
    download_already_existed = False
    download_error = None
    log.info("[step 2] 下载 %s", ZIP_URL)
    if not args.skip_download:
        if zip_path.exists():
            log.info("[step 2] zip 已存在 (%s), 跳过下载", _fmt_bytes(zip_path.stat().st_size))
            download_ok = True
            download_already_existed = True
        else:
            try:
                _download(ZIP_URL, zip_path)
                download_ok = True
            except Exception as exc:
                download_error = f"{type(exc).__name__}: {exc}"
                log.error("[step 2] 下载失败: %s", download_error)
    elif not zip_path.exists():
        download_error = f"--skip-download 但 zip 不存在: {zip_path}"
        log.error("[step 2] %s", download_error)
    else:
        download_ok = True
        download_already_existed = True

    _download_info: dict = {
        "ok": download_ok,
        "fileName": zip_path.name,
        "filePath": str(zip_path),
        "fileBytes": zip_path.stat().st_size if zip_path.exists() else 0,
        "alreadyExisted": download_already_existed,
    }
    if download_error:
        _download_info["error"] = download_error
    log.info("---begin-download-json---\n%s\n---end-download-json---", _json.dumps(_download_info, ensure_ascii=False))

    if not download_ok:
        log.error("[step 2] 下载未完成, 终止")
        return 2

    log.info("[step 2] ✓ 下载完成: %s (%s)", zip_path.name, _fmt_bytes(_download_info["fileBytes"]))

    # ═══════════════════════════════════════════════════════════════════
    # 3) 解压到带日期后缀的临时目录 (不解压到正式目录, 先验证)
    # ═══════════════════════════════════════════════════════════════════
    if dated_target.exists():
        log.info("[step 3] dated target 已存在, 清理: %s", dated_target)
        shutil.rmtree(dated_target, ignore_errors=True)

    extract_tmp = date_dir / "hsjday_extract_tmp"
    if extract_tmp.exists():
        shutil.rmtree(extract_tmp, ignore_errors=True)

    log.info("[step 3] 解压 %s → %s", zip_path.name, extract_tmp)
    try:
        _extract(zip_path, extract_tmp)
    except Exception as exc:
        log.error("[step 3] 解压失败: %s", exc)
        extract_info = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        log.info("---begin-extract-json---\n%s\n---end-extract-json---", _json.dumps(extract_info, ensure_ascii=False))
        return 4

    # 找到解压后的 hsjday 根目录, 移动到 dated_target
    new_hsjday = _find_hsjday_root(extract_tmp)
    n_files = sum(1 for _ in new_hsjday.rglob("*.day"))
    log.info("[step 3] 解压根: %s  含 %d 个 .day 文件", new_hsjday, n_files)
    new_hsjday.rename(dated_target)
    extract_info = {"ok": True, "totalDayFiles": n_files, "extractedTo": str(dated_target)}
    log.info("---begin-extract-json---\n%s\n---end-extract-json---", _json.dumps(extract_info, ensure_ascii=False))
    log.info("[step 3] ✓ 解压完成: %s (%d files)", dated_target.name, n_files)

    # 清理临时目录
    if extract_tmp.exists():
        shutil.rmtree(extract_tmp, ignore_errors=True)

    # ═══════════════════════════════════════════════════════════════════
    # 4) 验证 dated_target 下的 .day 数据 (旧 hsjday/ 仍完好)
    # ═══════════════════════════════════════════════════════════════════
    log.info("[step 4] 验证数据: %s (旧数据仍在 %s, 未动)", dated_target, TDX_TARGET)
    verify_result = _verify_download(dated_target, d)
    brief = {
        "ok": verify_result["ok"],
        "totalFiles": sum(m["files"] for m in verify_result["perMarket"].values()),
        "totalBytes": sum(m["bytes"] for m in verify_result["perMarket"].values()),
        "perMarket": {k: {"files": v["files"], "bytes": v["bytes"]} for k, v in verify_result["perMarket"].items()},
        "samples": verify_result["samples"],
        "sampleOkCount": sum(1 for s in verify_result["samples"] if s.get("ok")),
        "sampleTotalCount": len(verify_result["samples"]),
        "targetTradingDay": d.isoformat(),
        "errors": verify_result.get("errors", []),
    }
    log.info("---begin-verify-json---\n%s\n---end-verify-json---", _json.dumps(brief, ensure_ascii=False))
    if not verify_result["ok"]:
        log.error(
            "[step 4] ✗ 验证未通过: %d/%d 采样文件缺少 %s 交易日数据, 旧 hsjday/ 保留不动",
            brief["sampleTotalCount"] - brief["sampleOkCount"],
            brief["sampleTotalCount"],
            d.isoformat(),
        )
        # 清理失败的 dated_target, 旧 hsjday/ 不受影响
        if dated_target.exists():
            shutil.rmtree(dated_target, ignore_errors=True)
            log.info("[step 4] 已清理失败数据: %s", dated_target)
        return 3
    log.info("[step 4] ✓ 验证通过: %d/%d 采样文件包含 %s 数据",
             brief["sampleOkCount"], brief["sampleTotalCount"], d.isoformat())

    # ═══════════════════════════════════════════════════════════════════
    # 5) 原子重命名: 验证通过后才删旧 hsjday, 把 hsjday-{date} 改名为 hsjday
    # ═══════════════════════════════════════════════════════════════════
    log.info("[step 5] 原子替换: %s → %s", dated_target.name, TDX_TARGET.name)
    if TDX_TARGET.exists():
        shutil.rmtree(TDX_TARGET, ignore_errors=True)
        log.info("[step 5] 已删除旧 target: %s", TDX_TARGET)
    try:
        dated_target.rename(TDX_TARGET)
    except Exception as exc:
        log.error("[step 5] ✗ 重命名失败, 旧数据已删除! 手动检查 %s", dated_target)
        rename_info = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        log.info("---begin-rename-json---\n%s\n---end-rename-json---", _json.dumps(rename_info, ensure_ascii=False))
        return 5
    rename_info = {"ok": True, "from": str(dated_target), "to": str(TDX_TARGET)}
    log.info("---begin-rename-json---\n%s\n---end-rename-json---", _json.dumps(rename_info, ensure_ascii=False))
    log.info("[step 5] ✓ 替换完成")

    # ═══════════════════════════════════════════════════════════════════
    # 6) 输出文件列表 + 清理旧 zip (只保留最近 2 天)
    # ═══════════════════════════════════════════════════════════════════
    day_files = sorted(TDX_TARGET.rglob("*.day"))
    file_samples = [str(p.relative_to(TDX_TARGET).as_posix()) for p in day_files[:6]]
    files_info = {
        "zipName": zip_path.name,
        "zipPath": str(zip_path),
        "zipBytes": zip_path.stat().st_size if zip_path.exists() else 0,
        "totalDayFiles": len(day_files),
        "samples": file_samples,
    }
    log.info("---begin-files-json---\n%s\n---end-files-json---", _json.dumps(files_info, ensure_ascii=False))

    # 清理旧 zip: 只保留最近 2 天下载的文件
    _cleanup_old_zips(DOWNLOAD_BASE, keep_days=2)

    # 清理中间目录
    for tmp_dir in [date_dir / "hsjday_extracted", date_dir / "hsjday_extract_tmp"]:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    log.info("✓ done. target=%s  files=%d  date=%s", TDX_TARGET, len(day_files), d.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
