"""风险偏好 (Risk Appetite Spread) duckdb 回填 scheduler.

单 job:
  - 工作日 17:05 触发 (cron ``5 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_risk_appetite.py --days=2`` (增量, 默认跳过已有)
  - 数据源: duckdb.daily_qfq (沪深300 + 511010/511090 三个 ETF)
  - 输出: duckdb.risk_appetite_daily (1 日 1 行)

依赖: daily_eod_incremental (17:00) 必须先把 daily_raw + qfq 落库, 这里才能算.

启动: :mod:`backend.bootstrap` 调 :func:`start_risk_appetite_scheduler`.
关闭: ``MINIMAX_RISK_APPETITE_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\risk_appetite_job.json``
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
from backend.services.scheduler.backfill_validator import fetch_scalar_value, validate_scalar

logger = logging.getLogger(__name__)

RISK_APPETITE_CRON = "5 17 * * mon-fri"  # 工作日 17:05 (北京时间, 跟 17:00 daily_eod 错开 5 min)
_JOB_ID = "risk_appetite_refresh"
_SCRIPT_PATH_KEY = "risk_appetite_script"  # 状态文件可覆盖脚本路径 (测试用)
# 单日 --days=2 计算 < 0.5s, 给 2 min 上限足够
_JOB_TIMEOUT_SECONDS = 2 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_risk_appetite_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_RISK_APPETITE_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_risk_appetite.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    s = load_status("risk_appetite_refresh")
    return s if s else {
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


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("risk_appetite_refresh", status)


# ---------------------------------------------------------------------------
# Job 注册 (DB)
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="risk_appetite_refresh", name=name,
        description=(
            "MSI Factor 4: risk_appetite (风险偏好, weight 10%). "
            "Cron 17:05, 沪深300 20日收益 - 国债ETF 20日收益 spread → 3年分位 0-100. "
            "落 duckdb.risk_appetite_daily."
        ),
        service_module="backend.services.scheduler.risk_appetite_scheduler",
        service_class="RiskAppetiteScheduler",
        config_file="risk_appetite_job.json",
        default_config={
            "name": _JOB_ID, "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
            "lastDurationSeconds": None, "lastDaysRequested": None, "lastCoverage": None,
            "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
        },
    )


# ---------------------------------------------------------------------------
# stdout 解析
# ---------------------------------------------------------------------------
def _grep_int(stdout: str, marker: str) -> int | None:
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


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_backfill() -> None:
    """17:05 跑 backfill_risk_appetite.py --days=2 (subprocess).

    周末 / 节假日不 skip, 改按最近一个交易日 (target_date) 跑, 避免 cron 漏跑.
    """
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    if target_date != today:
        status["lastTargetTradeDate"] = target_date.isoformat()
        logger.info(
            "risk_appetite: today=%s 非交易日, 改按 target=%s 跑",
            today, target_date,
        )
    else:
        status["lastTargetTradeDate"] = target_date.isoformat()

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("risk_appetite: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} {msg}"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            "risk_appetite_refresh",
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
        # 抓脚本 stdout 关键行: "完成: 写入 X 跳过 Y 失败 Z"
        m = re.search(r"完成:\s*写入\s*(\d+)\s*跳过\s*(\d+)", stdout)
        if m:
            status["lastRowsUpserted"] = int(m.group(1))
            status["lastRowsSkipped"] = int(m.group(2))
        else:
            status["lastRowsUpserted"] = None
            status["lastRowsSkipped"] = None

        if r.returncode == 0:
            # DuckDB 数据校验: 有值且不为 0
            _valid_ok, _valid_err = validate_scalar("risk_appetite_daily", "spread_weighted", target_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("risk_appetite validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                spread_val = fetch_scalar_value("risk_appetite_daily", "spread_weighted", target_date)
                up = status.get("lastRowsUpserted"); sk = status.get("lastRowsSkipped")
                parts = [f"spread_weighted={spread_val:.4f}"] if spread_val is not None else []
                if up is not None:
                    parts.append(f"{up}行" + (f"+{sk}行skip" if sk and sk > 0 else ""))
                parts.append(f"(target={target_date.isoformat()})")
                status["lastMessage"] = " ".join(parts) if spread_val is not None else f"{cst_time}  ok"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info(
                "risk_appetite ok in %.1fs: upserted=%s skipped=%s spread=%s",
                elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"), spread_val,
            )
            _refresh_coverage(status)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or f"exit={r.returncode}")
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "risk_appetite failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("risk_appetite timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("risk_appetite crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)

    record_run(
        "risk_appetite_refresh",
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
        message=status.get("lastMessage"),
    )


def _refresh_coverage(status: dict[str, Any]) -> None:
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn() as c:
            r = c.execute(
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
                "FROM risk_appetite_daily"
            ).fetchone()
        status["lastCoverage"] = {
            "firstDate": r[0].isoformat() if r[0] else None,
            "lastDate": r[1].isoformat() if r[1] else None,
            "rowCount": int(r[2]) if r[2] else 0,
        }
    except Exception as exc:
        logger.debug("refresh_coverage failed: %s", exc)


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态 / 手动触发
# ---------------------------------------------------------------------------
def start_risk_appetite_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[RiskAppetiteScheduler] disabled by config (enabled=false), not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(RISK_APPETITE_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(
            _JOB_ID,
            "risk_appetite_refresh (17:05 工作日, 风险偏好 spread 回填 duckdb)",
            None,
            )
        _save_job_status(status)
        logger.info(
            "risk_appetite_scheduler started: cron=%s (workday only via is_trading_day)",
            RISK_APPETITE_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_risk_appetite_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("risk_appetite_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)

    


def get_risk_appetite_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_risk_appetite_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_backfill()
    status = get_risk_appetite_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }