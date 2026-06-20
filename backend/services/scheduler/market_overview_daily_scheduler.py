"""大盘概况 / 市场脉搏 90 行业 duckdb 回填 scheduler.

单 job:
  - 工作日 17:10 触发 (cron ``10 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_market_overview_daily.py``:
    1. 扫 reference/market-overview/archive/YYYYMMDD.json
       → duckdb.market_overview_daily (akshare 资金流 + spot_em)
    2. 扫 reference/market-overview/market-overview/archive/YYYYMMDD.json
       → duckdb.market_overview_daily (eltdx 字段, 不覆盖已有)
    3. 扫 reference/stock-universe/market_pulse/rotation/YYYY-MM-DD.json
       → duckdb.market_pulse_sector_daily (90 行业)
  - 幂等: 全部走 INSERT OR REPLACE / 字段级 UPSERT

跟 daily_eod_incremental 关系:
  - 17:00 daily_eod_incremental 跑完 → daily_raw 已落地
  - 17:10 这个 job 跑 → 落 market_overview_daily + market_pulse_sector_daily
    (跟 daily_eod 不冲突, 一个写 daily_raw / limit_emotion, 一个写 overview / sector)

启动: :mod:`backend.bootstrap` 调 :func:`start_market_overview_daily_scheduler`.
关闭: ``MINIMAX_MARKET_OVERVIEW_DAILY_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\market_overview_daily_job.json``
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
    SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE,
)
from backend.services.stock.trading_calendar import is_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

OVERVIEW_DAILY_CRON = "10 17 * * mon-fri"  # 工作日 17:10 (北京时间, 在 17:00 daily_eod 之后)
_JOB_ID = "market_overview_daily"
_SCRIPT_PATH_KEY = "market_overview_daily_script"  # 状态文件可覆盖脚本路径 (测试用)

# backfill 扫 60 天 archive 通常 < 30s; 给 5 min 上限足够, 防止 90 行业 rotation archive 异常卡住
_JOB_TIMEOUT_SECONDS = 5 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_market_overview_daily_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_MARKET_OVERVIEW_DAILY_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_market_overview_daily.py")


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE.exists():
        return {
            "name": _JOB_ID,
            "lastRunAt": None,
            "lastRunOk": None,
            "lastRunError": None,
            "lastDurationSeconds": None,
            "lastDaysRequested": None,
            "lastAkshareUpserted": None,
            "lastEltdxUpserted": None,
            "lastSectorDays": None,
            "lastOverviewCoverage": None,
            "lastSectorCoverage": None,
            "totalRuns": 0,
            "totalFailures": 0,
            "schedulerStartedAt": None,
        }
    try:
        return json.loads(SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("market_overview_daily job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE)


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
            "工作日 17:10 触发, 调 scripts/backfill_market_overview_daily.py 扫本地 JSON archive, "
            "把 (1) akshare 资金流 + spot_em 全 A 涨跌家数 "
            "(2) eltdx 涨跌家数 / 成交额 "
            "(3) akshare 90 行业 涨跌幅 / 流入流出 / 主力净流入 "
            "全部 upsert 到 duckdb (market_overview_daily + market_pulse_sector_daily 表). "
            "全部走 INSERT OR REPLACE / 字段级 UPSERT, 幂等. 周末 / 节假日由 is_trading_day 二次过滤. "
            "预计耗时 < 30s (扫 60 天 archive)."
        ),
        "config_file": SCHEDULER_MARKET_OVERVIEW_DAILY_JOB_FILE.name,
        "service_module": "backend.services.scheduler.market_overview_daily_scheduler",
        "service_class": "MarketOverviewDailyScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.market_overview_daily_scheduler",
        "nextRunTime": next_run_time,
        "updatedAt": now_iso,
    }
    jobs.append(payload)
    from backend.utils.json_io import write_json_file
    write_json_file(SCHEDULER_JOBS_FILE, data)


# ---------------------------------------------------------------------------
# stdout 解析 (跟 tdx_hsjday 一样, 从 print 抓关键信息)
# ---------------------------------------------------------------------------
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


def _parse_kv_count(stdout: str, key: str) -> int | None:
    """从 stdout 找 'key=NN' 模式."""
    m = re.search(rf"{re.escape(key)}=(\d+)", stdout)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_backfill() -> None:
    """17:10 跑 backfill_market_overview_daily.py (subprocess).

    周末 / 节假日不 skip, 改按最近一个交易日 (target_date) 跑, 避免 cron 漏跑.
    """
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")
    start_at_iso = now.isoformat(timespec="seconds")
    if target_date != today:
        status["lastTargetTradeDate"] = target_date.isoformat()
        logger.info(
            "market_overview_daily: today=%s 非交易日, 改按 target=%s 跑",
            today, target_date,
        )
    else:
        status["lastTargetTradeDate"] = target_date.isoformat()

    # 脚本路径: 状态文件可覆盖 (测试用)
    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("market_overview_daily: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            "market_overview_daily",
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

        # 抓脚本 stdout 关键行
        stdout = r.stdout or ""
        status["lastAkshareUpserted"] = (
            _grep_int(stdout, "akshare archive 命中 ")
            or _parse_kv_count(stdout, "akshare_upserted")
        )
        status["lastEltdxUpserted"] = (
            _grep_int(stdout, "eltdx archive 命中 ")
            or _parse_kv_count(stdout, "eltdx_upserted")
        )
        status["lastSectorDays"] = (
            _grep_int(stdout, "rotation 命中 ")
            or _parse_kv_count(stdout, "sector_days")
        )

        if r.returncode == 0:
            # DuckDB 数据校验: 有值且不为 0
            _valid_ok, _valid_err = validate_scalar("market_overview_daily", "total_amount", target_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("market_overview_daily validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info(
                "market_overview_daily ok in %.1fs: akshare=%s eltdx=%s sector_days=%s",
                elapsed, status.get("lastAkshareUpserted"),
                status.get("lastEltdxUpserted"), status.get("lastSectorDays"),
            )
            # 写覆盖度给前端看
            _refresh_coverage(status)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "market_overview_daily failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"timeout (>{_JOB_TIMEOUT_SECONDS}s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("market_overview_daily timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "market_overview_daily crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)

    record_run(
        "market_overview_daily",
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
    )


def _refresh_coverage(status: dict[str, Any]) -> None:
    """回填成功后, 读 2 张表的覆盖度写到 status (前端展示用)."""
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn() as c:
            r1 = c.execute(
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
                "FROM market_overview_daily"
            ).fetchone()
            r2 = c.execute(
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*), "
                "COUNT(DISTINCT trade_date) FROM market_pulse_sector_daily"
            ).fetchone()
        if r1:
            status["lastOverviewCoverage"] = {
                "firstDate": r1[0].isoformat() if r1[0] else None,
                "lastDate": r1[1].isoformat() if r1[1] else None,
                "rowCount": int(r1[2]) if r1[2] else 0,
            }
        if r2:
            status["lastSectorCoverage"] = {
                "firstDate": r2[0].isoformat() if r2[0] else None,
                "lastDate": r2[1].isoformat() if r2[1] else None,
                "rowCount": int(r2[2]) if r2[2] else 0,
                "tradeDayCount": int(r2[3]) if r2[3] else 0,
            }
    except Exception as exc:
        logger.debug("refresh_coverage failed: %s", exc)


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态 / 手动触发
# ---------------------------------------------------------------------------
def start_market_overview_daily_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[MarketOverviewDailyScheduler] disabled by config (enabled=false), not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(OVERVIEW_DAILY_CRON),
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
            "market_overview_daily (17:10 工作日, 大盘 / 行业 回填 duckdb)",
            None,
        )
        logger.info(
            "market_overview_daily_scheduler started: cron=%s (workday only via is_trading_day)",
            OVERVIEW_DAILY_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_market_overview_daily_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("market_overview_daily_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)

    


def get_market_overview_daily_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_market_overview_daily_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_backfill()
    status = get_market_overview_daily_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }
