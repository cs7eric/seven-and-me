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

from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.services.scheduler.backfill_validator import (
    fetch_scalar_value,
    resolve_latest_scalar_date,
    validate_scalar,
)

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
    s = load_status("profit_effect_refresh")
    return s if s else {
        "name": "profit_effect_refresh",
        "lastRunAt":None,"lastRunOk":None,"lastRunError":None,"lastDurationSeconds":None,"lastDaysRequested":None,"lastCoverage":None,"totalRuns":0,"totalFailures":0,"schedulerStartedAt":None,
    }


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("profit_effect_refresh", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="profit_effect_refresh", name=name,
        description="MSI Factor 7: profit_effect (赚钱效应, weight 10%%). Cron 17:09, 近5日上涨占比+60日新低反向 -> 3年分位.",
        service_module="backend.services.scheduler.profit_effect_scheduler",
        service_class="ProfitEffectScheduler",
        config_file="profit_effect_job.json",
        default_config={"name": "profit_effect_refresh", "lastRunAt":None,"lastRunOk":None,"lastRunError":None,"lastDurationSeconds":None,"lastDaysRequested":None,"lastCoverage":None,"totalRuns":0,"totalFailures":0,"schedulerStartedAt":None},
    )


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
    cst_time = cst_now_str()
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
        status["lastRunError"] = f"{cst_time} {msg}"
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
            message=status.get("lastMessage"),
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

        stdout = (r.stdout or "") + "\n" + (r.stderr or "")
        m = re.search(r"完成:\s*写入\s*(\d+)\s*跳过\s*(\d+)", stdout)
        if m:
            status["lastRowsUpserted"] = int(m.group(1))
            status["lastRowsSkipped"] = int(m.group(2))
        else:
            status["lastRowsUpserted"] = None
            status["lastRowsSkipped"] = None

        if r.returncode == 0:
            # DuckDB 数据校验: 有值且不为 0
            validated_date = resolve_latest_scalar_date("profit_effect_daily", "score", target_date) or target_date
            status["lastValidatedTradeDate"] = validated_date.isoformat()
            _valid_ok, _valid_err = validate_scalar("profit_effect_daily", "score", validated_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("profit_effect validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                score_val = fetch_scalar_value("profit_effect_daily", "score", validated_date)
                up = status.get("lastRowsUpserted")
                parts = [f"score={score_val:.2f}"] if score_val is not None else []
                if up is not None:
                    parts.append(f"覆盖写入{up}行")
                parts.append(f"(target={validated_date.isoformat()})")
                status["lastMessage"] = " ".join(parts) if score_val is not None else f"{cst_time}  ok"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info(
                "profit_effect ok in %.1fs: overwritten=%s score=%s",
                elapsed, status.get("lastRowsUpserted"), score_val,
            )
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or f"exit={r.returncode}")
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "profit_effect failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("profit_effect timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"{type(exc).__name__}: {exc}"[:300]
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
        message=status.get("lastMessage"),
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
        _register_job(
            _JOB_ID,
            "profit_effect_refresh (17:09 工作日, 赚钱效应合成得分回填 duckdb)",
            None,
            )
        _save_job_status(status)
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
