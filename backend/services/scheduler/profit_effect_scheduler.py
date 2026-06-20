"""赚钱效应 (Profit Effect) duckdb 回填 scheduler.

单 job:
  - 工作日 17:09 触发 (cron ``9 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_profit_effect.py --days=2 --force``
  - 输出: duckdb.profit_effect_daily

依赖: ma_count_scheduler (17:06) 必须先把 ma_count_daily 落库, 这里才能算.

启动: :mod:`backend.bootstrap` 调 :func:`start_profit_effect_scheduler`.
关闭: ``MINIMAX_PROFIT_EFFECT_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\profit_effect_job.json``
Jobs 注册表: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import json
import logging
import os
import re
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
    SCHEDULER_PROFIT_EFFECT_JOB_FILE,
)
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

PROFIT_EFFECT_CRON = "9 17 * * mon-fri"  # 工作日 17:09 (北京时间, 跟 17:08 style_risk_appetite 错开 1 min)
_JOB_ID = "profit_effect_refresh"
_SCRIPT_PATH_KEY = "profit_effect_script"  # 状态文件可覆盖脚本路径 (测试用)
_JOB_TIMEOUT_SECONDS = 2 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_profit_effect_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_PROFIT_EFFECT_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_profit_effect.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULER_PROFIT_EFFECT_JOB_FILE.exists():
        return {
            "name": _JOB_ID,
            "lastRunAt": None,
            "lastRunOk": None,
            "lastRunError": None,
            "lastDurationSeconds": None,
            "lastDaysRequested": None,
            "lastCoverage": None,
            "totalRuns": 0,
            "totalFailures": 0,
            "schedulerStartedAt": None,
        }
    try:
        return json.loads(SCHEDULER_PROFIT_EFFECT_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("profit_effect job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_PROFIT_EFFECT_JOB_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(SCHEDULER_PROFIT_EFFECT_JOB_FILE)


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
        data = {"version": 1, "jobs": []}
    if not isinstance(data, dict):
        data = {"version": 1, "jobs": []}
    jobs = data.setdefault("jobs", [])
    jobs = [j for j in jobs if j.get("id") != job_id]
    now_iso = _beijing_now().isoformat(timespec="seconds")
    payload = {
        "id": job_id,
        "name": name,
        "description": (
            "工作日 17:09 触发, 调 scripts/backfill_profit_effect.py --days=2 --force, "
            "对 ma_count_daily 算近 5 日上涨占比 + 60 日新低反向合成, "
            "落 duckdb.profit_effect_daily. 依赖 ma_count 17:06 必须先落 ma_count_daily."
        ),
        "config_file": SCHEDULER_PROFIT_EFFECT_JOB_FILE.name,
        "service_module": "backend.services.scheduler.profit_effect_scheduler",
        "service_class": "ProfitEffectScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.profit_effect_scheduler",
        "nextRunTime": next_run_time,
        "updatedAt": now_iso,
    }
    jobs.append(payload)
    from backend.utils.json_io import write_json_file
    write_json_file(SCHEDULER_JOBS_FILE, data)


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def job_run_backfill() -> dict:
    """17:09 跑 backfill_profit_effect.py --days=2 --force (subprocess)."""
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    start_at_iso = now.isoformat(timespec="seconds")
    status["lastRunAt"] = start_at_iso
    status["lastTargetTradeDate"] = target_date.isoformat()

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("profit_effect: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            _JOB_ID,
            status="failed",
            duration_seconds=status.get("lastDurationSeconds"),
            start_at=start_at_iso,
            end_at=datetime.now().isoformat(timespec="seconds"),
            error=status.get("lastRunError"),
        )
        return {"ok": False, "error": msg}

    try:
        script_env = {
            **os.environ,
            "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat(),
        }
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--days=2", "--force"],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            env=script_env,
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 2

        stdout = r.stdout or ""
        m = re.search(r"完成:\s*写入\s*(\d+)\s*跳过\s*(\d+)", stdout)
        if m:
            status["lastRowsUpserted"] = int(m.group(1))
            status["lastRowsSkipped"] = int(m.group(2))
        else:
            status["lastRowsUpserted"] = None
            status["lastRowsSkipped"] = None

        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "profit_effect ok in %.1fs: upserted=%s skipped=%s",
                elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"),
            )
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "profit_effect failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("profit_effect timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("profit_effect crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(
        _JOB_ID,
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
    )
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    """APScheduler 入口, 不返值."""
    job_run_backfill()


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态 / 手动触发
# ---------------------------------------------------------------------------
def start_profit_effect_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[ProfitEffectScheduler] disabled by config (enabled=false), not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(PROFIT_EFFECT_CRON),
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
            "profit_effect_refresh (17:09 工作日, 赚钱效应合成得分回填 duckdb)",
            None,
        )
        logger.info(
            "profit_effect_scheduler started: cron=%s (workday only via is_trading_day)",
            PROFIT_EFFECT_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_profit_effect_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("profit_effect_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_profit_effect_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_profit_effect_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_profit_effect_scheduler_status()
    return {
        "ok": bool(result.get("ok")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if result.get("ok") else 1,
    }


def get_profit_effect_scheduler() -> BackgroundScheduler | None:
    """给 api/scheduler.py 用, trigger_now 备用."""
    return _scheduler