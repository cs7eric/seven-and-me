"""波动率情绪 (Volatility Sentiment) duckdb 回填 scheduler.

单 job:
  - 工作日 17:07 触发 (cron ``7 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_volatility_sentiment.py --days=2``:
    1. 检查 duckdb.index_daily_raw[sh000300] 是否有 ≥ 282 行, 不足自动调
       fetch_index_history.py --days=300 --codes=000300 补数
    2. 算近 20 日日收益 std × √252 → vol
    3. 算近 252 日 vol 滚动分位 → 1 - percentile → 情绪得分 0-100
    4. 落 duckdb.volatility_sentiment_daily (1 日 1 行)

依赖: duckdb.index_daily_raw 沪深300 数据 (auto-pull 会拉),
      daily_eod_incremental (17:00) 先把 daily_raw 落库 (auto-pull 走的脚本不依赖).

启动: :mod:`backend.bootstrap` 调 :func:`start_volatility_sentiment_scheduler`.
关闭: ``MINIMAX_VOLATILITY_SENTIMENT_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\volatility_sentiment_job.json``
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
    SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE,
)
from backend.services.stock.trading_calendar import is_trading_day
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

VOLATILITY_SENTIMENT_CRON = "7 17 * * mon-fri"  # 工作日 17:07 (北京时间, 跟 17:06 ma_count 错开 1 min)
_JOB_ID = "volatility_sentiment_refresh"
_SCRIPT_PATH_KEY = "volatility_sentiment_script"  # 状态文件可覆盖脚本路径 (测试用)
# 单日 --days=2 计算 < 0.5s; auto-pull 拉一次 ~ 3s; 给 5 min 上限足够
_JOB_TIMEOUT_SECONDS = 5 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_volatility_sentiment_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_VOLATILITY_SENTIMENT_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_volatility_sentiment.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE.exists():
        return {
            "name": _JOB_ID,
            "lastRunAt": None,
            "lastRunOk": None,
            "lastRunError": None,
            "lastDurationSeconds": None,
            "lastDaysRequested": None,
            "lastRowsUpserted": None,
            "lastCoverage": None,
            "totalRuns": 0,
            "totalFailures": 0,
            "schedulerStartedAt": None,
        }
    try:
        return json.loads(SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("volatility_sentiment job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE)


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
            "工作日 17:07 触发, 调 scripts/backfill_volatility_sentiment.py --days=2, "
            "对 duckdb.index_daily_raw[sh000300] 算近 20 日日收益 std × √252 → vol, "
            "近 252 日 vol 滚动分位 → 1 - percentile → 情绪得分 0-100, "
            "落 duckdb.volatility_sentiment_daily (1 日 1 行). "
            "数据不足自动调 fetch_index_history.py 补 300 天 K 线 (auto-pull 默认开). "
            "INSERT OR REPLACE 幂等; 周末 / 节假日由 is_trading_day 二次过滤. 预计耗时 < 5s."
        ),
        "config_file": SCHEDULER_VOLATILITY_SENTIMENT_JOB_FILE.name,
        "service_module": "backend.services.scheduler.volatility_sentiment_scheduler",
        "service_class": "VolatilitySentimentScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.volatility_sentiment_scheduler",
        "nextRunTime": next_run_time,
        "updatedAt": now_iso,
    }
    jobs.append(payload)
    from backend.utils.json_io import write_json_file
    write_json_file(SCHEDULER_JOBS_FILE, data)


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_backfill() -> None:
    """17:07 跑 backfill_volatility_sentiment.py --days=2 (subprocess, --auto-pull 默认开)."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("volatility_sentiment skipped: %s not trading day", now.date())
        return

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("volatility_sentiment: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        return

    try:
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--days=2"],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 2

        stdout = r.stdout or ""
        # 抓脚本 stdout: "完成: 写入 X 跳过 Y 失败 Z"
        m = re.search(r"完成:\s*写入\s*(\d+)\s*跳过\s*(\d+)", stdout)
        if m:
            status["lastRowsUpserted"] = int(m.group(1))
            status["lastRowsSkipped"] = int(m.group(2))

        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "volatility_sentiment ok in %.1fs: upserted=%s skipped=%s",
                elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"),
            )
            _refresh_coverage(status)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "volatility_sentiment failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("volatility_sentiment timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("volatility_sentiment crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)


def _refresh_coverage(status: dict[str, Any]) -> None:
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn() as c:
            r = c.execute(
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
                "FROM volatility_sentiment_daily"
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
def start_volatility_sentiment_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[VolatilitySentimentScheduler] disabled by config (enabled=false), not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(VOLATILITY_SENTIMENT_CRON),
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
            "volatility_sentiment_refresh (17:07 工作日, 波动率情绪回填 duckdb)",
            None,
        )
        logger.info(
            "volatility_sentiment_scheduler started: cron=%s (workday only via is_trading_day)",
            VOLATILITY_SENTIMENT_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_volatility_sentiment_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("volatility_sentiment_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_volatility_sentiment_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_volatility_sentiment_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用)."""
    _job_run_backfill()
    status = get_volatility_sentiment_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }