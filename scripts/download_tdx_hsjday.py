"""下载 TDX hsjday.zip → 解压 → 覆盖 reference/tdx/day/hsjday.

URL: https://data.tdx.com.cn/vipdoc/hsjday.zip (~538 MB)
目标: reference/stock/download/{YYYY-MM-DD}/hsjday.zip
      → reference/stock/download/{YYYY-MM-DD}/hsjday_extracted/hsjday/
      → 覆盖 reference/tdx/day/hsjday/

步骤:
  1. 下载 zip (流式, 1MB chunk, 进度打印, 校验 Content-Length)
  2. 解压到 reference/stock/download/{date}/hsjday_extracted/
  3. 备份旧 reference/tdx/day/hsjday → reference/tdx/day/hsjday.bak.{ts}
  4. 移动解压出的 hsjday/* → reference/tdx/day/hsjday/
  5. 清理: 删 hsjday_extracted/ 中间目录, 保留 hsjday.zip 供回溯

失败回滚: 任一步失败, 把备份恢复成 hsjday/, 删半成品.

用法:
    python scripts/download_tdx_hsjday.py                          # 今天
    python scripts/download_tdx_hsjday.py --date 2026-06-17         # 指定日期
    python scripts/download_tdx_hsjday.py --dry-run                # 只看计划
    python scripts/download_tdx_hsjday.py --skip-download          # 假定 zip 已下好
    python scripts/download_tdx_hsjday.py --skip-replace           # 解压后不覆盖
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
import zipfile
from datetime import date, datetime
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


def _replace_target(new_hsjday: Path, target: Path) -> Path:
    """备份 target → 移动 new_hsjday/* → 覆盖 target. 返回 backup 路径."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(f"{target.name}.bak.{ts}")
    if not target.exists():
        log.warning("target %s 不存在, 跳过备份", target)
    else:
        log.info("backup %s → %s", target.name, backup.name)
        target.rename(backup)
    try:
        log.info("move %s/* → %s/*", new_hsjday, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 把 new_hsjday 本身 rename 成 target 路径 (atomic on same volume)
        new_hsjday.rename(target)
    except Exception:
        log.exception("替换失败, 回滚 backup → target")
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return backup


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 TDX hsjday.zip → 覆盖 reference/tdx/day/hsjday")
    ap.add_argument("--date", type=str, default=None,
                    help="下载日期目录名 (默认今天 YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--skip-download", action="store_true",
                    help="跳过下载, 假定 zip 已存在")
    ap.add_argument("--skip-replace", action="store_true",
                    help="解压后不覆盖 target")
    args = ap.parse_args()

    d = date.fromisoformat(args.date) if args.date else date.today()
    date_dir = DOWNLOAD_BASE / d.isoformat()
    zip_path = date_dir / "hsjday.zip"
    extracted_dir = date_dir / "hsjday_extracted"

    log.info("date=%s  date_dir=%s", d.isoformat(), date_dir)
    log.info("zip_url=%s  expected_zip=%s", ZIP_URL, zip_path)
    log.info("target=%s  skip_download=%s  skip_replace=%s  dry_run=%s",
             TDX_TARGET, args.skip_download, args.skip_replace, args.dry_run)

    if args.dry_run:
        log.info("[dry-run] 不会下载 / 解压 / 替换")
        return 0

    date_dir.mkdir(parents=True, exist_ok=True)

    # 1) 下载
    if not args.skip_download:
        if zip_path.exists():
            log.info("zip 已存在 (%s), 跳过下载", _fmt_bytes(zip_path.stat().st_size))
        else:
            _download(ZIP_URL, zip_path)
    elif not zip_path.exists():
        log.error("--skip-download 但 zip 不存在: %s", zip_path)
        return 1

    # 2) 解压
    if extracted_dir.exists():
        log.info("extracted 目录已存在: %s, 跳过解压", extracted_dir)
    else:
        _extract(zip_path, extracted_dir)

    # 3) 找 hsjday 实际根
    new_hsjday = _find_hsjday_root(extracted_dir)
    n_files = sum(1 for _ in new_hsjday.rglob("*.day"))
    log.info("新 hsjday 根: %s  含 %d 个 .day 文件", new_hsjday, n_files)

    if args.skip_replace:
        log.info("[--skip-replace] 不覆盖 target, 文件留在 %s", new_hsjday)
        return 0

    # 4) 替换 (含备份 + 回滚)
    t0 = time.time()
    backup = _replace_target(new_hsjday, TDX_TARGET)
    log.info("替换完成 in %.1fs, 备份: %s", time.time() - t0, backup)

    # 5) 清理中间目录 (zip 保留, extracted 删掉节省空间)
    if extracted_dir.exists():
        log.info("清理 %s", extracted_dir)
        shutil.rmtree(extracted_dir, ignore_errors=True)

    log.info("done.  target=%s  files=%d", TDX_TARGET, n_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
