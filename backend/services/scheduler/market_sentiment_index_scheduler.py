"""市场情绪指数 composite (Market Sentiment Index) duckdb 回填 scheduler.

单 job:
  - 工作日 17:10 触发 (cron ``10 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_market_sentiment_index.py --days=2 --force``
  - 输出: duckdb.market_sentiment_index_daily

依赖 (必须全部完成才能跑):
  - 17:00 daily_eod_incremental → daily_raw + limit_emotion_summary_daily
  - 17:06 ma_count_scheduler    → ma_count_daily + index_returns_daily
  - 17:08 style_risk_appetite   → style_risk_appetite_daily
  - 17:09 profit_effect         → profit_effect_daily

启动: :mod:`backend.bootstrap` 调 :func:`start_market_sentiment_index_scheduler`.
关闭: ``MINIMAX_MARKET_SENTIMENT_INDEX_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\market_sentiment_index_job.json``
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
    SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE,
)
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

MARKET_SENTIMENT_INDEX_CRON = "10 17 * * mon-fri"  # 工作日 17:10 (北京时间, 等 17:09 profit_effect 完成后 1 min)
_JOB_ID = "market_sentiment_index_refresh"
_SCRIPT_PATH_KEY = "market_sentiment_index_script"  # 状态文件可覆盖脚本路径 (测试用)
_JOB_TIMEOUT_SECONDS = 5 * 60  # composite 算 9 张卡, 给 5 min 上限

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_market_sentiment_index_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_MARKET_SENTIMENT_INDEX_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_market_sentiment_index.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE.exists():
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
        return json.loads(SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("market_sentiment_index job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE)


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
            "工作日 17:10 触发, 调 scripts/backfill_market_sentiment_index.py --days=2 --force, "
            "对 8 张子卡 (volatility / turnover / ma_count / risk_appetite / limit_emotion_summary / "
            "profit_effect / sector_breadth / style_risk_appetite) 加权合成 composite_score, "
            "落 duckdb.market_sentiment_index_daily. 17:10 = 全部依赖完成 1 分钟后跑."
        ),
        "config_file": SCHEDULER_MARKET_SENTIMENT_INDEX_JOB_FILE.name,
        "service_module": "backend.services.scheduler.market_sentiment_index_scheduler",
        "service_class": "MarketSentimentIndexScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.market_sentiment_index_scheduler",
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
    """17:10 跑 backfill_market_sentiment_index.py --days=2 --force (subprocess)."""
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
        logger.error("market_sentiment_index: %s", msg)
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
            # DuckDB 数据校验: 有值且不为 0
            _valid_ok, _valid_err = validate_scalar("market_sentiment_index_daily", "composite_score", target_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("market_sentiment_index validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info(
                "market_sentiment_index ok in %.1fs: upserted=%s skipped=%s",
                elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"),
            )
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "market_sentiment_index failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("market_sentiment_index timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("market_sentiment_index crashed: %s\n%s", exc, traceback.format_exc())

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
def start_market_sentiment_index_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[MarketSentimentIndexScheduler] disabled by config (enabled=false), not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(MARKET_SENTIMENT_INDEX_CRON),
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
            "market_sentiment_index_refresh (17:10 工作日, composite 情绪指数回填 duckdb)",
            None,
        )
        logger.info(
            "market_sentiment_index_scheduler started: cron=%s (workday only via is_trading_day)",
            MARKET_SENTIMENT_INDEX_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_market_sentiment_index_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("market_sentiment_index_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_market_sentiment_index_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_market_sentiment_index_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_market_sentiment_index_scheduler_status()
    return {
        "ok": bool(result.get("ok")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if result.get("ok") else 1,
    }


def get_market_sentiment_index_scheduler() -> BackgroundScheduler | None:
    """给 api/scheduler.py 用, trigger_now 备用."""
    return _scheduler