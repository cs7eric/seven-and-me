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

import json
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

from backend.config.settings import (
    SCHEDULER_DIR,
    SCHEDULER_JOBS_FILE,
    SCHEDULER_TDX_HSJDAY_DOWNLOAD_JOB_FILE,
)
from backend.services.stock.trading_calendar import is_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.utils.json_io import read_json_file

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
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULER_TDX_HSJDAY_DOWNLOAD_JOB_FILE.exists():
        return {
            "name": _JOB_ID,
            "lastRunAt": None,
            "lastRunOk": None,
            "lastRunError": None,
            "lastRunDate": None,
            "lastZipPath": None,
            "lastDayFileCount": None,
            "lastDownloadBytes": None,
            "lastDurationSeconds": None,
            "totalRuns": 0,
            "totalFailures": 0,
            "schedulerStartedAt": None,
        }
    try:
        return json.loads(SCHEDULER_TDX_HSJDAY_DOWNLOAD_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("tdx_hsjday_download job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_TDX_HSJDAY_DOWNLOAD_JOB_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(SCHEDULER_TDX_HSJDAY_DOWNLOAD_JOB_FILE)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if SCHEDULER_JOBS_FILE.exists():
        data = read_json_file(SCHEDULER_JOBS_FILE, {"version": 1, "jobs": []})
    else:
        data = {"version": 1, "jobs": []}
    if isinstance(data, list):
        data = {"version": 1, "jobs": data}
    if not isinstance(data, dict):
        data = {"version": 1, "jobs": []}
    jobs = data.setdefault("jobs", [])
    jobs = [j for j in jobs if j.get("id") != job_id]
    now_iso = _beijing_now().isoformat(timespec="seconds")
    payload = {
        "id": job_id,
        "name": name,
        "description": (
            "工作日 16:30 触发, 调 scripts/download_tdx_hsjday.py 下载 TDX hsjday.zip (~538MB), "
            "解压到 reference/stock/download/{date}/, 备份旧 reference/tdx/day/hsjday, "
            "mv 新 hsjday 覆盖 target; 失败回滚; 周末 / 节假日由 is_trading_day 拦下; "
            "预计耗时 3-5 min (下载 30-60s + 解压 1-2 min + 替换 5-10s)"
        ),
        "config_file": _STATUS_FILE_NAME,
        "service_module": "backend.services.scheduler.tdx_hsjday_download_scheduler",
        "service_class": "TdxHsjdayDownloadScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.tdx_hsjday_download_scheduler",
        "nextRunTime": next_run_time,
        "updatedAt": now_iso,
    }
    jobs.append(payload)
    from backend.utils.json_io import write_json_file
    write_json_file(SCHEDULER_JOBS_FILE, data)


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_download() -> None:
    """16:30 跑 download_tdx_hsjday.py (subprocess, 不阻塞 scheduler).

    周末 / 节假日不 skip, 改按最近一个交易日 (target_date) 跑, 避免 cron 漏跑.
    TDX hsjday.zip 每个交易日发布一次, 上一个交易日有最新数据.
    """
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")
    start_at_iso = now.isoformat(timespec="seconds")
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
        status["lastRunError"] = msg
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
            capture_output=True,
            text=True,
            env=script_env,
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)

        # 从 stdout 抓关键信息 (脚本会 log.info "[download] / [extract]")
        stdout = r.stdout or ""
        status["lastZipPath"] = _grep_path(stdout, "zip_path=")
        # 写当日预期目录 (脚本默认行为)
        status["lastZipPath"] = status["lastZipPath"] or str(
            _repo_root() / "reference" / "stock" / "download" / now.date().isoformat() / "hsjday.zip"
        )
        # 文件数 / 字节数
        day_count = _grep_int(stdout, "含 ")
        if day_count is not None:
            status["lastDayFileCount"] = day_count
        zip_bytes = _grep_bytes_from_log(stdout)
        if zip_bytes is not None:
            status["lastDownloadBytes"] = zip_bytes

        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "tdx_hsjday_download ok in %.1fs: day_files=%s zip_bytes=%s",
                elapsed, status.get("lastDayFileCount"), status.get("lastDownloadBytes"),
            )
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "tdx_hsjday_download failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("tdx_hsjday_download timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "tdx_hsjday_download crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)

    record_run(
        "tdx_hsjday_download",
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
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
        _save_job_status(status)
        _register_job(
            _JOB_ID,
            "tdx_hsjday_download (16:30 工作日, 下 hsjday.zip + 覆盖 reference/tdx/day/hsjday)",
            None,
        )
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


def run_tdx_hsjday_download_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_download()
    status = get_tdx_hsjday_download_scheduler_status()
    # 包装成前端友好的 {ok, count, failed_count} 形态 (跟其他 scheduler 一致)
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }
