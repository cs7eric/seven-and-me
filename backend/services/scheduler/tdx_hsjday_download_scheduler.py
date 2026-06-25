"""TDX hsjday.zip 下载 + 解压 + 覆盖 scheduler.

工作日 16:30 触发 (cron ``30 16 * * mon-fri`` + ``is_trading_day`` 二次过滤),
调 ``scripts/download_tdx_hsjday.py``:

  1. 下载 https://data.tdx.com.cn/vipdoc/hsjday.zip (~538 MB) → reference/stock/download/{date}/
  2. 解压 → reference/stock/download/{date}/hsjday_extracted/hsjday/
  3. 备份旧 reference/tdx/day/hsjday → hsjday.bak.{ts}
  4. mv 新 hsjday/ 覆盖 reference/tdx/day/hsjday/
  5. 失败自动回滚 (恢复 backup → target)

启动: :mod:`backend.bootstrap` 调 :func:`start_tdx_hsjday_download_scheduler`.
关闭: ``MINIMAX_TDX_HSJDAY_DOWNLOAD_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\tdx_hsjday_download_job.json``
Jobs 注册表: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.stock.trading_calendar import is_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.services.scheduler.target_date import resolve_scheduler_target_date

logger = logging.getLogger(__name__)

DOWNLOAD_CRON = "30 16 * * mon-fri"  # 工作日 16:30 (北京时间)
_JOB_ID = "tdx_hsjday_download"
_STATUS_FILE_NAME = "tdx_hsjday_download_job.json"
_SCRIPT_PATH_KEY = "tdx_hsjday_download_script"  # 状态文件可覆盖脚本路径 (测试用)

# 下载 + 解压 + 替换: 538 MB 下 30-60s, 解压 1-2 min, 替换 5-10s. 上限 30 min 留余量.
_JOB_TIMEOUT_SECONDS = 30 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_tdx_hsjday_download_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_TDX_HSJDAY_DOWNLOAD_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "download_tdx_hsjday.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None,
        "lastRunOk": None,
        "lastRunError": None,
        "lastRunDate": None,
        "lastStatus": None,                # "success" | "failed" | "skipped"
        "lastSkipped": False,
        "lastSkipReason": None,
        # ---- 交易日校验 ----
        "lastTradingDayCheck": None,       # {ok, latestDataDate, checked, error}
        "lastTradingDayChecked": False,
        # ---- 存量数据 ----
        "lastExistingDataDate": None,       # 存量 .day 文件最新日期
        "lastAlreadyHaveData": False,
        # ---- 下载 ----
        "lastZipPath": None,
        "lastZipName": None,
        "lastZipBytes": None,
        "lastDownloadNote": None,          # "已存在, 跳过下载"
        "lastDownloadError": None,
        # ---- 解压 ----
        "lastExtractOk": None,
        # ---- 重命名 ----
        "lastRenameOk": None,
        # ---- 文件列表 ----
        "lastDayFileCount": None,
        "lastFileSamples": None,           # [str] 采样文件名
        # ---- 下载字节数 (旧字段兼容) ----
        "lastDownloadBytes": None,
        "lastDurationSeconds": None,
        # ---- 验证字段 ----
        "lastVerifyOk": None,
        "lastVerifyTotalFiles": None,
        "lastVerifyTotalBytes": None,
        "lastVerifyPerMarket": None,      # {sh: {files, bytes}, sz: ..., bj: ...}
        "lastVerifySamples": None,         # [{code, market, firstDate, lastDate, records, ok}, ...]
        "lastVerifySampleOk": None,        # 通过采样的数量
        "lastVerifySampleTotal": None,     # 总采样数
        "lastVerifyTradingDay": None,      # 验证的目标交易日
        "lastVerifyErrors": None,          # [str] 验证失败详情
        "totalRuns": 0,
        "totalFailures": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    status = load_status("tdx_hsjday_download")
    if status:
        return status
    return _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("tdx_hsjday_download", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "工作日 16:30 触发, 调 scripts/download_tdx_hsjday.py 下载 TDX hsjday.zip (~538MB), "
            "解压到 reference/stock/download/{date}/, 备份旧 reference/tdx/day/hsjday, "
            "mv 新 hsjday 覆盖 target; 失败回滚; 周末 / 节假日由 is_trading_day 拦下; "
            "预计耗时 3-5 min (下载 30-60s + 解压 1-2 min + 替换 5-10s)"
        ),
        service_module="backend.services.scheduler.tdx_hsjday_download_scheduler",
        service_class="TdxHsjdayDownloadScheduler",
        config_file=_STATUS_FILE_NAME,
        default_config=_job_default_status(),
    )


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_download(target_date=None) -> None:
    """16:30 跑 download_tdx_hsjday.py (subprocess, 不阻塞 scheduler).

    周末 / 节假日不 skip, 改按最近一个交易日 (target_date) 跑, 避免 cron 漏跑.
    TDX hsjday.zip 每个交易日发布一次, 上一个交易日有最新数据.
    """
    now = _beijing_now()
    today = now.date()
    target_date = resolve_scheduler_target_date(today, target_date)

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    status["lastRunDate"] = target_date.isoformat()
    if target_date != today:
        status["lastTargetTradeDate"] = target_date.isoformat()
        logger.info(
            "tdx_hsjday_download: today=%s 非交易日, 改按 target=%s 跑",
            today, target_date,
        )
    else:
        status["lastTargetTradeDate"] = target_date.isoformat()

    # 脚本路径: 状态文件可覆盖 (测试用), 默认走 repo root
    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("tdx_hsjday_download: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} {msg}"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            "tdx_hsjday_download",
            status="failed",
            duration_seconds=status.get("lastDurationSeconds"),
            start_at=start_at_iso,
            end_at=datetime.now().isoformat(timespec="seconds"),
            error=status.get("lastRunError"),
            message=status.get("lastMessage"),
        )
        return

    try:
        script_env = {
            **os.environ,
            "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat(),
        }
        r = subprocess.run(
            [sys.executable, "-u", str(script), f"--date={target_date.isoformat()}"],
            cwd=str(_repo_root()),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # stderr → stdout: JSON 块和错误消息都在一条流里
            text=True,
            env=script_env,
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)

        # 所有输出 (日志 + JSON 块) 都在 stdout
        stdout = r.stdout or ""
        stderr = ""  # 已合并到 stdout

        # 0) 交易日校验
        td_data = _parse_json_block(stdout, "---begin-trading-day-json---", "---end-trading-day-json---")
        if td_data:
            status["lastTradingDayCheck"] = td_data
            status["lastTradingDayChecked"] = td_data.get("checked")

        # 1) 存量数据检查
        existing_data = _parse_json_block(stdout, "---begin-existing-data-json---", "---end-existing-data-json---")
        if existing_data:
            status["lastExistingDataDate"] = existing_data.get("latestDate")
            status["lastAlreadyHaveData"] = existing_data.get("alreadyHaveData")

        # 2) 下载结果 JSON
        download_data = _parse_json_block(stdout, "---begin-download-json---", "---end-download-json---")
        if download_data:
            status["lastZipName"] = download_data.get("fileName")
            status["lastZipPath"] = download_data.get("filePath")
            status["lastZipBytes"] = download_data.get("fileBytes")
            if download_data.get("alreadyExisted"):
                status["lastDownloadNote"] = "已存在, 跳过下载"
            if download_data.get("error"):
                status["lastDownloadError"] = download_data.get("error")

        # 3) 解压结果 JSON
        extract_data = _parse_json_block(stdout, "---begin-extract-json---", "---end-extract-json---")
        if extract_data:
            status["lastExtractOk"] = extract_data.get("ok")
            if extract_data.get("totalDayFiles"):
                status["lastDayFileCount"] = extract_data.get("totalDayFiles")

        # 4) 验证 JSON
        verify_data = _parse_json_block(stdout, "---begin-verify-json---", "---end-verify-json---")
        if verify_data:
            status["lastVerifyOk"] = verify_data.get("ok")
            status["lastVerifyTotalFiles"] = verify_data.get("totalFiles")
            status["lastVerifyTotalBytes"] = verify_data.get("totalBytes")
            status["lastVerifyPerMarket"] = verify_data.get("perMarket")
            status["lastVerifySamples"] = verify_data.get("samples")
            status["lastVerifySampleOk"] = verify_data.get("sampleOkCount")
            status["lastVerifySampleTotal"] = verify_data.get("sampleTotalCount")
            status["lastVerifyTradingDay"] = verify_data.get("targetTradingDay")
            status["lastVerifyErrors"] = verify_data.get("errors")

        # 5) 重命名结果 JSON
        rename_data = _parse_json_block(stdout, "---begin-rename-json---", "---end-rename-json---")
        if rename_data:
            status["lastRenameOk"] = rename_data.get("ok")

        # 6) 文件列表 JSON
        files_data = _parse_json_block(stdout, "---begin-files-json---", "---end-files-json---")
        if files_data:
            status["lastDayFileCount"] = files_data.get("totalDayFiles")
            status["lastFileSamples"] = files_data.get("samples")

        # 兼容旧格式 (grep 兜底)
        if not status.get("lastZipPath"):
            status["lastZipPath"] = _grep_path(stdout, "zip_path=") or str(
                _repo_root() / "reference" / "stock" / "download" / now.date().isoformat() / "hsjday.zip"
            )

        # ═══════════════════════════════════════════════════════════════
        # 成功 / 失败判定
        # ═══════════════════════════════════════════════════════════════
        verify_ok = bool(verify_data and verify_data.get("ok"))

        if r.returncode == 0 and not verify_data and not download_data:
            # 脚本成功退出但没有 download/verify JSON → 跳过了
            # (非交易日 或 已有最新数据)
            skip_reason = ""
            if td_data and not td_data.get("ok"):
                skip_reason = f"{cst_time} 非交易日 (目标={status.get('lastRunDate')}, K线最新={td_data.get('latestDataDate') or '?'})"
            elif existing_data and existing_data.get("alreadyHaveData"):
                skip_reason = f"{cst_time} 已有最新数据 (最新={existing_data.get('latestDate')})"
            else:
                skip_reason = f"{cst_time} 跳过 (无下载/验证输出)"
            status["lastRunOk"] = True
            status["lastRunError"] = f"{cst_time} " + str(skip_reason)
            status["lastSkipped"] = True
            status["lastSkipReason"] = skip_reason
            status["lastStatus"] = "skipped_non_trading_day" if (td_data and not td_data.get("ok")) else "skipped"
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "tdx_hsjday_download skipped: %s (%.1fs)", skip_reason, elapsed,
            )
        elif r.returncode == 0 and verify_ok:
            status["lastRunOk"] = True
            status["lastRunError"] = None

            status["lastMessage"] = (
                f"下载成功: {status.get('lastDayFileCount','?')}文件 "
                f"{_fmt_status_bytes(status.get('lastZipBytes'))}, "
                f"验证{status.get('lastVerifySampleOk','?')}/{status.get('lastVerifySampleTotal','?')}通过"
                f" (target={target_date.isoformat()})"
            )
            status["lastSkipped"] = False
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "tdx_hsjday_download ok in %.1fs: file=%s (%s) day_files=%s verify=%s/%s",
                elapsed,
                status.get("lastZipName"), _fmt_status_bytes(status.get("lastZipBytes")),
                status.get("lastDayFileCount"),
                status.get("lastVerifySampleOk"), status.get("lastVerifySampleTotal"),
            )
        elif r.returncode == 2:
            # 下载失败
            dl_err = status.get("lastDownloadError") or _grep_last_error(stdout) or (stderr or stdout)[-400:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + f"[下载失败] {dl_err[:500]}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download download failed in %.1fs: file=%s error=%s",
                elapsed, status.get("lastZipName") or "?", status.get("lastRunError"),
            )
        elif r.returncode == 3:
            # 验证未通过
            verify_errors = status.get("lastVerifyErrors") or []
            if verify_errors:
                err_detail = "; ".join(str(e) for e in verify_errors[:5])
            else:
                err_detail = _grep_verify_fail(stdout) or "最新交易日数据缺失"
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + f"[验证失败] {err_detail}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download verify failed in %.1fs: exit=3 file=%s (%s) errors=%s",
                elapsed,
                status.get("lastZipName") or "?",
                _fmt_status_bytes(status.get("lastZipBytes")),
                status.get("lastRunError"),
            )
        elif r.returncode == 4:
            # 解压失败
            extract_err = (extract_data or {}).get("error") if extract_data else None
            err_msg = extract_err or _grep_last_error(stdout) or (stderr or stdout)[-400:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + f"[解压失败] {err_msg[:500]}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download extract failed in %.1fs: exit=4 file=%s error=%s",
                elapsed, status.get("lastZipName") or "?", status.get("lastRunError"),
            )
        elif r.returncode == 5:
            # 重命名失败
            rename_err = (rename_data or {}).get("error") if rename_data else None
            err_msg = rename_err or _grep_last_error(stdout) or f"exit=5"
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + f"[替换失败] {err_msg[:500]}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download rename failed in %.1fs: exit=5 file=%s error=%s",
                elapsed, status.get("lastZipName") or "?", status.get("lastRunError"),
            )
        else:
            # 其他错误
            phase_hint = _grep_last_error(stdout)
            err_tail = (stderr or stdout)[-600:].strip()
            err_msg = phase_hint or err_tail or f"exit={r.returncode}"
            if phase_hint:
                if any(tag in phase_hint for tag in ("下载", "download", "JS challenge", "urlopen")):
                    phase = "[下载失败]"
                elif any(tag in phase_hint for tag in ("解压", "extract", "zipfile")):
                    phase = "[解压失败]"
                elif any(tag in phase_hint for tag in ("替换", "重命名", "rename", "rename")):
                    phase = "[替换失败]"
                else:
                    phase = "[运行失败]"
            else:
                phase = "[运行失败]"
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + f"{phase} {err_msg[:500]}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download failed in %.1fs: exit=%d file=%s error=%s",
                elapsed, r.returncode,
                status.get("lastZipName") or "?",
                status.get("lastRunError"),
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("tdx_hsjday_download timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "tdx_hsjday_download crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)

    if status.get("lastSkipped"):
        hist_status = "skipped"
    elif status.get("lastRunOk"):
        hist_status = "success"
    else:
        hist_status = "failed"
    record_run(
        "tdx_hsjday_download",
        status=hist_status,
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
        message=status.get("lastMessage"),
    )


def _grep_path(stdout: str, key: str) -> str | None:
    """从 stdout 找形如 'key=... ' 的字段."""
    for line in stdout.splitlines():
        if key in line:
            parts = line.split(key, 1)
            if len(parts) == 2:
                tail = parts[1].strip().split()
                if tail:
                    return tail[0]
    return None


def _grep_int(stdout: str, marker: str) -> int | None:
    """从 stdout 找 'marker <int>' 模式."""
    for line in stdout.splitlines():
        idx = line.find(marker)
        if idx == -1:
            continue
        tail = line[idx + len(marker):].strip().split()
        if tail:
            try:
                return int(tail[0])
            except ValueError:
                pass
    return None


def _grep_bytes_from_log(stdout: str) -> int | None:
    """从 'download done: 538.2MB in ...' 这种行里抓字节数."""
    for line in stdout.splitlines():
        if "download done:" in line and " in " in line:
            # "  download done: 538.3MB in 53.4s (10.1 MB/s)"
            head = line.split("download done:", 1)[1]
            num = head.strip().split()[0]
            try:
                return _parse_size_to_bytes(num)
            except ValueError:
                pass
    return None


def _parse_size_to_bytes(s: str) -> int:
    s = s.strip()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for u, mul in units.items():
        if s.endswith(u):
            return int(float(s[: -len(u)]) * mul)
    return int(s)


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态
# ---------------------------------------------------------------------------
def start_tdx_hsjday_download_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[TdxHsjdayDownloadScheduler] disabled by config (%s enabled=false), not started",
                _STATUS_FILE_NAME,
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_download,
            CronTrigger.from_crontab(DOWNLOAD_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(
            _JOB_ID,
            "tdx_hsjday_download (16:30 工作日, 下 hsjday.zip + 覆盖 reference/tdx/day/hsjday)",
            )
        _save_job_status(status)
        logger.info(
            "tdx_hsjday_download_scheduler started: cron=%s (workday only via is_trading_day)",
            DOWNLOAD_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def stop_tdx_hsjday_download_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("tdx_hsjday_download_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)

    


def get_tdx_hsjday_download_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_tdx_hsjday_download_now(target_date=None) -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_download(target_date=target_date)
    status = get_tdx_hsjday_download_scheduler_status()
    # 包装成前端友好的 {ok, count, failed_count} 形态 (跟其他 scheduler 一致)
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }


def _parse_verify_json(stdout: str) -> dict[str, Any] | None:
    """从 stdout 提取 ``---begin-verify-json--- ... ---end-verify-json---`` 块并解析 JSON.

    脚本 ``download_tdx_hsjday.py`` 在替换后输出这个结构化块.
    解析失败返回 None (不抛异常).
    """
    import json as _json
    try:
        start_marker = "---begin-verify-json---"
        end_marker = "---end-verify-json---"
        start_idx = stdout.find(start_marker)
        if start_idx == -1:
            return None
        start_idx += len(start_marker)
        end_idx = stdout.find(end_marker, start_idx)
        if end_idx == -1:
            return None
        body = stdout[start_idx:end_idx].strip()
        if not body:
            return None
        return dict(_json.loads(body))
    except Exception:
        return None

def _parse_json_block(stdout: str, start_marker: str, end_marker: str) -> dict[str, Any] | None:
    """从 stdout 提取 start_marker ... end_marker 块并解析 JSON. 解析失败返回 None."""
    import json as _json
    try:
        start_idx = stdout.find(start_marker)
        if start_idx == -1:
            return None
        start_idx += len(start_marker)
        end_idx = stdout.find(end_marker, start_idx)
        if end_idx == -1:
            return None
        body = stdout[start_idx:end_idx].strip()
        if not body:
            return None
        return dict(_json.loads(body))
    except Exception:
        return None


def _grep_last_error(stdout: str) -> str | None:
    """从脚本 stdout 中提取最后一个 ERROR/CRITICAL/Traceback 附近的错误消息."""
    lines = stdout.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if any(tag in line for tag in ("[ERROR]", "[CRITICAL]", "ERROR:", "CRITICAL:")):
            ctx = lines[i: i + 4]
            return " | ".join(s.strip() for s in ctx if s.strip())
    for i in range(len(lines) - 1, -1, -1):
        if "Traceback" in lines[i]:
            ctx = lines[i: i + 4]
            return " | ".join(s.strip() for s in ctx if s.strip())
    return None
def _grep_verify_fail(stdout: str) -> str | None:
    """从 stdout 提取 "验证未通过: ..." 行中的具体消息."""
    for line in stdout.splitlines():
        if "验证未通过" in line:
            # "2026-06-20 12:00:00,123 [ERROR] 验证未通过: 2/9 采样文件缺少 2026-06-20 交易日数据, 退出码=3"
            # 取 "验证未通过" 之后、最后一个逗号之前的部分
            idx = line.find("验证未通过")
            if idx >= 0:
                msg = line[idx:].rstrip()
                # 截掉末尾的 ", 退出码=3" / ", retcode=3"
                for suffix in (", 退出码=3", ", exit=3", ", retcode=3"):
                    if msg.endswith(suffix):
                        msg = msg[: -len(suffix)]
                if msg:
                    return msg
    return None
def _fmt_status_bytes(n) -> str:
    """把字节数格式化为人类可读字符串, None 安全."""
    if n is None:
        return "0 B"
    n = int(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}TB"
