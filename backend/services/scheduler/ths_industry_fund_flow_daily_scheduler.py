"""同花顺 90 行业资金流 → duckdb 回填 scheduler.

单 job:
  - 工作日 17:15 触发 (cron ``15 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_ths_industry_fund_flow.py``:
    1. 扫 reference/ths-fund-flow/history/YYYY-MM-DD.json
    2. 拆中文 key → 英文 key, 落 duckdb.ths_industry_fund_flow_daily
  - 幂等: 全部走 INSERT OR REPLACE by (trade_date, industry)

跟 market_overview_daily (17:10) 关系:
  - 17:10 大盘 / 行业 (akshare 源, market_pulse_sector_daily)
  - 17:15 同花顺 90 行业资金流 (hexin-v 源, ths_industry_fund_flow_daily)
  两表数据源不同 (akshare vs 同花顺 hexin-v), 口径可能略不同, **并存**不覆盖.

启动: :mod:`backend.bootstrap` 调 :func:`start_ths_industry_fund_flow_daily_scheduler`.
关闭: ``MINIMAX_THS_INDUSTRY_FUND_FLOW_DAILY_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\ths_industry_fund_flow_daily_job.json``
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

from backend.services.stock.trading_calendar import is_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str

logger = logging.getLogger(__name__)

FF_DAILY_CRON = "15 17 * * mon-fri"  # 工作日 17:15 (北京时间, 跟 17:10 market_overview_daily 错开)
_JOB_ID = "ths_industry_fund_flow_daily"
_SCRIPT_PATH_KEY = "ths_industry_fund_flow_daily_script"  # 状态文件可覆盖脚本路径 (测试用)

# backfill 扫 60 天 history (90 行业/天) 通常 < 5s; 给 2 min 上限
_JOB_TIMEOUT_SECONDS = 2 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_ths_industry_fund_flow_daily_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_THS_INDUSTRY_FUND_FLOW_DAILY_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_ths_industry_fund_flow.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None,
        "lastRunOk": None,
        "lastRunError": None,
        "lastDurationSeconds": None,
        "lastDaysRequested": None,
        "lastDaysUpserted": None,
        "lastRowsUpserted": None,
        "lastCoverage": None,
        "totalRuns": 0,
        "totalFailures": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("ths_industry_fund_flow_daily")
    if not cfg:
        return _job_default_status()
    return cfg


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("ths_industry_fund_flow_daily", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "工作日 17:15 触发, 调 scripts/backfill_ths_industry_fund_flow.py, "
            "扫 reference/ths-fund-flow/history/YYYY-MM-DD.json (中文 key), "
            "拆 key 落 duckdb.ths_industry_fund_flow_daily. 字段: rank/industry/industry_code/"
            "change_pct/inflow/outflow/net/company_count/leader_stock/leader_change/leader_price. "
            "跟 17:10 market_overview_daily (akshare 源) 解耦, 数据源不同 (hexin-v 同花顺), 字段一致但口径不同, 并存不覆盖. "
            "INSERT OR REPLACE 幂等; 周末 / 节假日由 is_trading_day 拦下; 预计耗时 < 5s."
        ),
        service_module="backend.services.scheduler.ths_industry_fund_flow_daily_scheduler",
        service_class="ThsIndustryFundFlowDailyScheduler",
        config_file="ths_industry_fund_flow_daily_job.json",
        default_config=_job_default_status(),
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
    """17:15 跑 backfill_ths_industry_fund_flow.py (subprocess).

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
            "ths_industry_fund_flow_daily: today=%s 非交易日, 改按 target=%s 跑",
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
        logger.error("ths_industry_fund_flow_daily: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            "ths_industry_fund_flow_daily",
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
            [sys.executable, "-u", str(script), "--days=60"],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            env=script_env,
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 60

        stdout = (r.stdout or "") + "\n" + (r.stderr or "")
        # 抓 days / rows (格式: "days=7 rows=630" 出现在 "done." 行)
        m_days = re.search(r"days=(\d+)\s+rows=(\d+)", stdout)
        if m_days:
            status["lastDaysUpserted"] = int(m_days.group(1))
            status["lastRowsUpserted"] = int(m_days.group(2))
        else:
            status["lastDaysUpserted"] = _grep_int(stdout, "history 命中 ")
            status["lastRowsUpserted"] = None

        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None

            status["lastMessage"] = (
                f"写入{status.get('lastDaysUpserted','?')}天 {status.get('lastRowsUpserted','?')}行 "
                f"(90行业/d, target={target_date.isoformat()})"
            )
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "ths_industry_fund_flow_daily ok in %.1fs: days=%s rows=%s",
                elapsed, status.get("lastDaysUpserted"), status.get("lastRowsUpserted"),
            )
            _refresh_coverage(status)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "ths_industry_fund_flow_daily failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("ths_industry_fund_flow_daily timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "ths_industry_fund_flow_daily crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)

    record_run(
        "ths_industry_fund_flow_daily",
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
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*), "
                "COUNT(DISTINCT trade_date) FROM ths_industry_fund_flow_daily"
            ).fetchone()
        status["lastCoverage"] = {
            "firstDate": r[0].isoformat() if r[0] else None,
            "lastDate": r[1].isoformat() if r[1] else None,
            "rowCount": int(r[2]) if r[2] else 0,
            "tradeDayCount": int(r[3]) if r[3] else 0,
        }
    except Exception as exc:
        logger.debug("refresh_coverage failed: %s", exc)


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态 / 手动触发
# ---------------------------------------------------------------------------
def start_ths_industry_fund_flow_daily_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[ThsIndustryFundFlowDailyScheduler] disabled by config, not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(FF_DAILY_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(
            _JOB_ID,
            "ths_industry_fund_flow_daily (17:15 工作日, 同花顺 90 行业资金流 → duckdb)",
            None,
            )
        _save_job_status(status)
        logger.info(
            "ths_industry_fund_flow_daily_scheduler started: cron=%s (workday only via is_trading_day)",
            FF_DAILY_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_ths_industry_fund_flow_daily_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("ths_industry_fund_flow_daily_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)

    


def get_ths_industry_fund_flow_daily_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_ths_industry_fund_flow_daily_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_backfill()
    status = get_ths_industry_fund_flow_daily_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }
