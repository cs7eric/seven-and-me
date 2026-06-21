"""市场情绪指数 composite (Market Sentiment Index) duckdb 回填 scheduler.

单 job:
  - 工作日 17:20 触发 (cron ``20 17 * * mon-fri``)
  - 前置检查: 9 张子表全部有当天非 NULL 且 > 0 的数据, 不全则 skip
  - 调 ``scripts/backfill_market_sentiment_index.py --days=2 --force --require-full``
  - 输出: duckdb.market_sentiment_index_daily

依赖 (9 factor 全部完成后才能跑):
  - 17:03 limit_emotion         → limit_emotion_summary_daily
  - 17:05 risk_appetite         → risk_appetite_daily
  - 17:06 ma_count              → ma_count_daily
  - 17:07 volatility_sentiment  → volatility_sentiment_daily
  - 17:08 style_risk_appetite   → style_risk_appetite_daily
  - 17:09 profit_effect         → profit_effect_daily
  - 17:10 market_overview_daily → market_overview_daily
  - 17:12 turnover_activity     → turnover_activity_daily
  - 17:17 sector_breadth        → market_pulse_sector_breadth_daily

启动: :mod:`backend.bootstrap` 调 :func:`start_market_sentiment_index_scheduler`.
关闭: ``MINIMAX_MARKET_SENTIMENT_INDEX_SCHEDULER_ENABLED=0``.
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
from backend.services.scheduler.backfill_validator import fetch_scalar_value, validate_scalar
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day

logger = logging.getLogger(__name__)

MARKET_SENTIMENT_INDEX_CRON = "20 17 * * mon-fri"  # 工作日 17:20 (北京时间, 等全部 9 factor + upstream 完成后)
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
# 9 factor 数据就绪检查 — MSI 跑之前必须全部有当天数据
# ---------------------------------------------------------------------------
_NINE_FACTOR_TABLES = [
    ("volatility_sentiment_daily",       "sentiment_score",  "Factor 1: vol"),
    ("turnover_activity_daily",          "score",            "Factor 2: turnover"),
    ("ma_count_daily",                   "new_high_252d_pct","Factor 3: price_strength"),
    ("risk_appetite_daily",              "spread_weighted",  "Factor 4: risk_appetite"),
    ("ma_count_daily",                   "breadth_raw",      "Factor 5: breadth"),
    ("limit_emotion_summary_daily",      "composite_score",  "Factor 6: limit_emotion"),
    ("profit_effect_daily",              "score",            "Factor 7: profit_effect"),
    ("market_pulse_sector_breadth_daily","advance_pct",      "Factor 8: sector_breadth"),
    ("style_risk_appetite_daily",        "spread",           "Factor 9: style_risk"),
]


def _all_nine_factors_ready(target_date) -> tuple[bool, list[str]]:
    """检查 9 张因子子表在 target_date 是否都有非 NULL 且 > 0 的数据.

    Returns:
        (all_ready, missing) — all_ready=True 表示全部就绪;
        missing 列出缺失的因子描述.
    """
    from backend.services.scheduler.backfill_validator import validate_scalar

    missing: list[str] = []
    for table, column, label in _NINE_FACTOR_TABLES:
        ok, err = validate_scalar(table, column, target_date)
        if not ok:
            missing.append(f"{label} ({table}.{column}): {err}")
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    s = load_status("market_sentiment_index_refresh")
    return s if s else {
        "name": "market_sentiment_index_refresh",
        "lastRunAt":None,"lastRunOk":None,"lastRunError":None,"lastDurationSeconds":None,"lastDaysRequested":None,"lastCoverage":None,"totalRuns":0,"totalFailures":0,"schedulerStartedAt":None,
    }


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("market_sentiment_index_refresh", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="market_sentiment_index_refresh", name=name,
        description="工作日 17:20 触发, 前置检查 9/9 factor 全就绪, 调 backfill_market_sentiment_index.py --require-full, 加权合成 composite_score -> duckdb.",
        service_module="backend.services.scheduler.market_sentiment_index_scheduler",
        service_class="MarketSentimentIndexScheduler",
        config_file="market_sentiment_index_job.json",
        default_config={"name": "market_sentiment_index_refresh", "lastRunAt":None,"lastRunOk":None,"lastRunError":None,"lastDurationSeconds":None,"lastDaysRequested":None,"lastCoverage":None,"totalRuns":0,"totalFailures":0,"schedulerStartedAt":None},
    )


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def job_run_backfill() -> dict:
    """17:20 跑 backfill_market_sentiment_index.py --days=2 --force --require-full (subprocess).
    前置检查: 9 factor 全部就绪才跑, 不全则 skip."""
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
        logger.error("market_sentiment_index: %s", msg)
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

    # --- 前置检查: 9 factor 必须全部就绪 ---
    all_ready, missing_factors = _all_nine_factors_ready(target_date)
    if not all_ready:
        msg = "[前置检查] 以下因子在 {} 无数据, MSI 跳过: {}".format(
            target_date.isoformat(), "; ".join(missing_factors))
        logger.warning("market_sentiment_index: %s", msg)
        status["lastRunOk"] = True
        status["lastRunError"] = f"{cst_time} {msg}"
        status["lastStatus"] = "skipped"
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
        _save_job_status(status)
        record_run(
            _JOB_ID, status="skipped",
            duration_seconds=status.get("lastDurationSeconds"),
            start_at=start_at_iso,
            end_at=datetime.now().isoformat(timespec="seconds"),
            error=msg,
        )
        return {"ok": True, "skipped": True, "reason": msg}

    try:
        script_env = {
            **os.environ,
            "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat(),
        }
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--days=2", "--force", "--require-full"],
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
            _valid_ok, _valid_err = validate_scalar("market_sentiment_index_daily", "composite_score", target_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("market_sentiment_index validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                msi_val = fetch_scalar_value("market_sentiment_index_daily", "composite_score", target_date)
                up = status.get("lastRowsUpserted"); sk = status.get("lastRowsSkipped")
                parts = [f"MSI={msi_val:.2f}"] if msi_val is not None else []
                if up is not None:
                    parts.append(f"{up}行" + (f"+{sk}行skip" if sk and sk > 0 else ""))
                parts.append(f"(target={target_date.isoformat()})")
                status["lastMessage"] = " ".join(parts) if msi_val is not None else f"{cst_time}  ok"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info(
                "market_sentiment_index ok in %.1fs: upserted=%s skipped=%s msi=%s",
                elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"), msi_val,
            )
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or f"exit={r.returncode}")
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "market_sentiment_index failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("market_sentiment_index timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + f"{type(exc).__name__}: {exc}"[:300]
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
        message=status.get("lastMessage"),
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
        _register_job(
            _JOB_ID,
            "market_sentiment_index_refresh (17:10 工作日, composite 情绪指数回填 duckdb)",
            None,
            )
        _save_job_status(status)
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