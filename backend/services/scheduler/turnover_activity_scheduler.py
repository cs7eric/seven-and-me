"""成交活跃度 (Turnover Activity) duckdb 回填 scheduler.

单 job:
  - 工作日 17:12 触发 (cron ``12 17 * * mon-fri``)
  - 调 ``scripts/backfill_turnover_activity.py --days=3``

校验: subprocess 成功后, 检查 turnover_activity_daily.ratio 不为 NULL 且 > 0.

启动: :mod:`backend.bootstrap` 调 :func:`start_turnover_activity_scheduler`.
关闭: ``MINIMAX_TURNOVER_ACTIVITY_SCHEDULER_ENABLED=0``.
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

from backend.services.scheduler.backfill_validator import (
    fetch_scalar_value,
    resolve_latest_scalar_date,
    validate_scalar,
)
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day

logger = logging.getLogger(__name__)

TURNOVER_ACTIVITY_CRON = "55 18 * * mon-fri"
_JOB_ID = "turnover_activity_refresh"
_SCRIPT_PATH_KEY = "turnover_activity_script"
_JOB_TIMEOUT_SECONDS = 5 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_turnover_activity_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_TURNOVER_ACTIVITY_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_turnover_activity.py")


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
        "lastDurationSeconds": None, "lastDaysRequested": None,
        "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("turnover_activity_refresh")
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("turnover_activity_refresh", status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="turnover_activity_refresh", name=name,
        description=(
            "MSI Factor 2: turnover (成交活跃度, weight 15%). "
            "工作日 17:12 触发, 调 scripts/backfill_turnover_activity.py --days=3, "
            "从 duckdb.daily_raw 的 999999 + 399001 成交额求和计算 ratio = 全市场成交额/20日均 -> 3年历史分位 0-100. "
            "依赖 TDX 日线已落 duckdb.daily_raw, 结果写入 duckdb.turnover_activity_daily."
        ),
        service_module="backend.services.scheduler.turnover_activity_scheduler",
        service_class="TurnoverActivityScheduler",
        config_file="turnover_activity_job.json",
        default_config=_job_default_status(),
    )


def _fetch_turnover_activity_debug_snapshot(target_date) -> dict[str, Any]:
    try:
        from backend.adapters.market.duckdb_store import get_conn

        with get_conn(read_only=True) as con:
            source_row = con.execute(
                """
                SELECT trade_date,
                       SUM(CASE WHEN code = '999999' THEN amount ELSE 0 END) AS sh_amount,
                       SUM(CASE WHEN code = '399001' THEN amount ELSE 0 END) AS sz_amount,
                       (SUM(CASE WHEN code = '999999' THEN amount ELSE 0 END)
                        + SUM(CASE WHEN code = '399001' THEN amount ELSE 0 END)) / 100000000.0 AS total_amount_yi
                  FROM daily_raw
                 WHERE trade_date <= ?
                   AND code IN ('999999', '399001')
                 GROUP BY trade_date
                HAVING COUNT(DISTINCT code) = 2
                 ORDER BY trade_date DESC
                 LIMIT 21
                """,
                [target_date],
            ).fetchall()
            saved_row = con.execute(
                """
                SELECT trade_date, total_amount, avg_20d_amount, ratio, score, elapsed_ms, source
                  FROM turnover_activity_daily
                 WHERE trade_date = ?
                """,
                [target_date],
            ).fetchone()
    except Exception as exc:
        return {"error": f"debug snapshot query failed: {exc}"}

    rows_asc = list(reversed(source_row or []))
    target_row = rows_asc[-1] if rows_asc else None
    sample_rows = rows_asc[:-1] if len(rows_asc) > 1 else []
    sample_amounts = [float(r[3]) for r in sample_rows if r[3] is not None]
    avg_20d = round(sum(sample_amounts) / len(sample_amounts), 4) if sample_amounts else None
    target_total = float(target_row[3]) if target_row and target_row[3] is not None else None
    target_sh_amount = float(target_row[1]) / 1e8 if target_row and target_row[1] is not None else None
    target_sz_amount = float(target_row[2]) / 1e8 if target_row and target_row[2] is not None else None
    ratio = round(target_total / avg_20d, 4) if target_total is not None and avg_20d not in (None, 0) else None

    result: dict[str, Any] = {
        "source": {
            "targetDate": target_date.isoformat(),
            "targetTotalAmount": round(target_total, 2) if target_total is not None else None,
            "targetShAmount": round(target_sh_amount, 2) if target_sh_amount is not None else None,
            "targetSzAmount": round(target_sz_amount, 2) if target_sz_amount is not None else None,
            "sampleCount": len(sample_rows),
            "sampleStart": sample_rows[0][0].isoformat() if sample_rows else None,
            "sampleEnd": sample_rows[-1][0].isoformat() if sample_rows else None,
            "sampleAmounts": [
                {
                    "tradeDate": r[0].isoformat(),
                    "shAmount": round(float(r[1]) / 1e8, 2),
                    "szAmount": round(float(r[2]) / 1e8, 2),
                    "totalAmount": round(float(r[3]), 2),
                }
                for r in sample_rows
                if r[3] is not None
            ],
        },
        "computed": {
            "totalAmount": round(target_total, 2) if target_total is not None else None,
            "shAmount": round(target_sh_amount, 2) if target_sh_amount is not None else None,
            "szAmount": round(target_sz_amount, 2) if target_sz_amount is not None else None,
            "avg20dAmount": avg_20d,
            "ratio": ratio,
        },
    }

    if saved_row:
        result["saved"] = {
            "tradeDate": saved_row[0].isoformat() if saved_row[0] else None,
            "totalAmount": float(saved_row[1]) if saved_row[1] is not None else None,
            "avg20dAmount": float(saved_row[2]) if saved_row[2] is not None else None,
            "ratio": float(saved_row[3]) if saved_row[3] is not None else None,
            "score": float(saved_row[4]) if saved_row[4] is not None else None,
            "elapsedMs": int(saved_row[5]) if saved_row[5] is not None else None,
            "source": str(saved_row[6]) if saved_row[6] is not None else None,
        }
    else:
        result["saved"] = None

    return result


def _build_turnover_activity_success_message(target_date) -> str:
    debug_info = _fetch_turnover_activity_debug_snapshot(target_date)
    if debug_info.get("error"):
        return f"target={target_date.isoformat()}\ndebug_error={debug_info['error']}"

    source = debug_info.get("source") or {}
    computed = debug_info.get("computed") or {}
    saved = debug_info.get("saved")
    lines = [
        f"target={target_date.isoformat()}",
        "source=" + json.dumps(source, ensure_ascii=False, separators=(",", ":")),
        "computed=" + json.dumps(computed, ensure_ascii=False, separators=(",", ":")),
        "saved=" + json.dumps(saved, ensure_ascii=False, separators=(",", ":")),
    ]
    return "\n".join(lines)


def job_run_backfill() -> dict:
    now = _beijing_now()
    target_date = resolve_target_trading_day(now.date())
    status = _load_job_status()
    t0 = time.time()
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    status["lastRunAt"] = start_at_iso
    status["lastTargetTradeDate"] = target_date.isoformat()

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = "script not found: {}".format(script)
        logger.error("turnover_activity: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} {msg}"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(_JOB_ID, status="failed", duration_seconds=status.get("lastDurationSeconds"),
                   start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
                   error=status.get("lastRunError"),
                   message=status.get("lastMessage"))
        return {"ok": False, "error": msg}

    try:
        script_env = {**os.environ, "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat()}
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--days=3"],
            cwd=str(_repo_root()), check=False, capture_output=True, text=True,
            env=script_env, timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 3

        if r.returncode == 0:
            validated_date = resolve_latest_scalar_date("turnover_activity_daily", "ratio", target_date) or target_date
            status["lastValidatedTradeDate"] = validated_date.isoformat()
            valid, err_msg = validate_scalar("turnover_activity_daily", "ratio", validated_date)
            if not valid:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(err_msg)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("turnover_activity validation failed in %.1fs: %s", elapsed, err_msg)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                ratio_val = fetch_scalar_value("turnover_activity_daily", "ratio", validated_date)
                score_val = fetch_scalar_value("turnover_activity_daily", "score", validated_date)
                status["lastMessage"] = _build_turnover_activity_success_message(validated_date)
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info("turnover_activity ok in %.1fs: ratio=%s score=%s", elapsed, ratio_val, score_val)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or "exit={}".format(r.returncode))
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning("turnover_activity failed in %.1fs: exit=%d\n%s", elapsed, r.returncode, err_tail)
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "timeout (>{}s)".format(_JOB_TIMEOUT_SECONDS)
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("turnover_activity timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "{}: {}".format(type(exc).__name__, exc)[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("turnover_activity crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(_JOB_ID, status="success" if status.get("lastRunOk") else "failed",
               duration_seconds=status.get("lastDurationSeconds"),
               start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
               error=status.get("lastRunError"),
               message=status.get("lastMessage"))
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    job_run_backfill()


def start_turnover_activity_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[TurnoverActivityScheduler] disabled by config, not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(_job_run_backfill, CronTrigger.from_crontab(TURNOVER_ACTIVITY_CRON),
                       id=_JOB_ID, max_instances=1, coalesce=True)
        sched.start()
        _scheduler = sched
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(_JOB_ID, "turnover_activity_refresh (17:12, 成交活跃度回填 duckdb)", None)
        _save_job_status(status)
        logger.info("turnover_activity_scheduler started: cron=%s", TURNOVER_ACTIVITY_CRON)
    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_turnover_activity_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("turnover_activity_scheduler stopped")
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_turnover_activity_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_turnover_activity_now() -> dict[str, Any]:
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_turnover_activity_scheduler_status()
    return {"ok": bool(result.get("ok")), "items": [status], "count": 1,
            "failed_count": 0 if result.get("ok") else 1}


def get_turnover_activity_scheduler() -> BackgroundScheduler | None:
    return _scheduler
