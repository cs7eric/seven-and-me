"""A 股全市场日持久化调度器（工作日 17:00 收盘后跑一次）。

启动方式：
    在 :mod:`backend.bootstrap` 里调 :func:`start_stock_universe_scheduler`。
    也可通过环境变量 ``MINIMAX_STOCK_UNIVERSE_SCHEDULER_ENABLED=0`` 关闭。

Job 配置文件：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\stock_universe_job.json``。
Jobs 注册表：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``。

调度策略：
    - 工作日 (周一~周五，按 ``datetime.weekday()`` 判定)
    - 17:00 收盘后 30 分钟窗口内触发一次 (避免 A 股收盘前的行情还在抖动)
    - 一天只跑一次 (last_run_date 兜底)
"""
from __future__ import annotations

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

from backend.config.settings import BASE_DIR
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 时间窗工具
# ---------------------------------------------------------------------------


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _is_workday(now: datetime) -> bool:
    return now.weekday() < 5


def _current_slot(now: datetime) -> str | None:
    """17:00:00 - 17:00:59 视为 17:00 slot, 用于触发每日一次. 其它时间不触发."""
    if now.hour == 17 and now.minute == 0:
        return "17:00"
    return None


# ---------------------------------------------------------------------------
# Job 配置 (对应 scheduler/stock_universe_job.json)
# ---------------------------------------------------------------------------

DEFAULT_JOB_CONFIG: dict[str, Any] = {
    "job_name": "stock_universe_refresh",
    "description": "工作日 17:00 收盘后, 拉全 A 股行情 + 题材, 持久化到 reference/stock-universe/YYYY-MM-DD.json",
    "enabled": True,
    "schedule": {
        "workday_only": True,
        "run_time": "17:00",
        "run_once_per_day": True,
    },
    "timezone_offset_hours": 8,
    "tick_seconds": 60,
    "last_run_at": None,
    "last_run_slot": None,
    "last_run_date": None,
    "last_status": "idle",
    "last_duration_seconds": None,
    "last_error": None,
    "last_log_file": None,
    "last_exit_code": None,
    "last_file": None,
    "total_runs": 0,
    "total_failures": 0,
}


def _load_job_config() -> dict[str, Any]:
    cfg = load_status("stock_universe_refresh")
    if not cfg:
        cfg = dict(DEFAULT_JOB_CONFIG)
    for key, value in DEFAULT_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def _save_job_config(cfg: dict[str, Any]) -> None:
    save_status("stock_universe_refresh", cfg)


def _register_job() -> None:
    """把 stock_universe_refresh job 注册到 DB (幂等)."""
    register_job(
        code="stock_universe_refresh",
        name="A 股全市场持久化",
        description="工作日 17:00 收盘后拉全 A 股行情 + 题材 + 行业归一, 持久化到 reference/stock-universe/",
        service_module="backend.services.scheduler.stock_universe_scheduler",
        service_class="StockUniverseRefreshScheduler",
        config_file="stock_universe_job.json",
        default_config=dict(DEFAULT_JOB_CONFIG),
    )


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


# refresh_stock_universe_loop.py 路径 (Python 版, 替代 .ps1)
_REFRESH_LOOP_SCRIPT = BASE_DIR / "backend" / "scripts" / "refresh_stock_universe_loop.py"
_REFRESH_LOGS_DIR = BASE_DIR / "reference" / "stock-universe" / "_logs"
_REFRESH_SNAPSHOT = BASE_DIR / "reference" / "stock-universe" / f"{datetime.now().strftime('%Y-%m-%d')}.json"


def _run_refresh_loop_script(slot: str, date_key: str) -> dict[str, Any]:
    """运行 refresh_stock_universe_loop.py (init → clean → 各组 → run-failed → aggregate).

    Python 版, 替代原来的 .ps1. 在调用方线程里阻塞到脚本结束;
    stdout+stderr 实时写入 ``_logs/{date}-slot-{HHMM}.log``.
    返回: ``status`` / ``exit_code`` / ``elapsed_seconds`` / ``log_file`` / ``snapshot_file`` / ``error``
    """
    _REFRESH_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    slot_tag = (slot or "manual").replace(":", "")
    log_file = _REFRESH_LOGS_DIR / f"{date_key}-slot-{slot_tag}.log"
    snapshot_file = BASE_DIR / "reference" / "stock-universe" / f"{date_key}.json"

    if not _REFRESH_LOOP_SCRIPT.exists():
        return {
            "status": "failed",
            "exit_code": None,
            "log_file": str(log_file),
            "snapshot_file": None,
            "error": f"script not found: {_REFRESH_LOOP_SCRIPT}",
        }

    cmd = [
        sys.executable,
        "-m", "backend.scripts.refresh_stock_universe_loop",
    ]
    logger.info(
        "[StockUniverseRefreshScheduler] launching loop slot=%s date=%s cmd=%s cwd=%s log=%s",
        slot, date_key, " ".join(cmd), BASE_DIR, log_file,
    )
    started = datetime.now()
    with log_file.open("w", encoding="utf-8") as logf:
        logf.write(f"# stock_universe_refresh slot={slot} date={date_key}\n")
        logf.write(f"# started={started.isoformat()}\n")
        logf.write(f"# cmd={' '.join(cmd)}\n")
        logf.write(f"# cwd={BASE_DIR}\n\n")
        logf.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(BASE_DIR),
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=None,  # 跑完为止, 脚本本身有内部 max_retry 限制
            )
        except Exception as exc:
            logf.write(f"\n# subprocess raised: {exc}\n")
            logf.write(traceback.format_exc())
            return {
                "status": "failed",
                "exit_code": None,
                "log_file": str(log_file),
                "snapshot_file": str(snapshot_file) if snapshot_file.exists() else None,
                "error": str(exc),
            }
    elapsed = round((datetime.now() - started).total_seconds(), 3)
    return {
        "status": "success" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "log_file": str(log_file),
        "snapshot_file": str(snapshot_file) if snapshot_file.exists() else None,
        "error": None if proc.returncode == 0 else f"exit_code={proc.returncode}",
    }


class StockUniverseRefreshScheduler:
    """A 股全市场持久化后台调度器 (每 60 秒 tick 一次)."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._inflight: bool = False
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        _register_job()
        cfg = _load_job_config()
        if not cfg.get("enabled", True):
            logger.info("[StockUniverseRefreshScheduler] disabled by config, not started")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="StockUniverseRefreshScheduler", daemon=True
        )
        self._thread.start()
        self._started_at = datetime.now()
        _save_job_config(cfg)
        logger.info("[StockUniverseRefreshScheduler] started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        logger.info("[StockUniverseRefreshScheduler] stopped")

    def status(self) -> dict[str, Any]:
        cfg = _load_job_config()
        with self._lock:
            inflight = self._inflight
        return {
            "running": self.is_running(),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "tick_count": self._tick_count,
            "inflight": inflight,
            "config": cfg,
        }

    def trigger_now(self) -> dict[str, Any]:
        """手动触发一次完整拉取 (绕开时间窗), 给路由 / 调试用."""
        return self._run_once(slot="manual", date_key=datetime.now().strftime("%Y-%m-%d"))

    # -------- 主循环 --------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.exception("[StockUniverseRefreshScheduler] tick error: %s", exc)
            cfg = _load_job_config()
            sleep_seconds = int(cfg.get("tick_seconds") or 60)
            self._stop_event.wait(sleep_seconds)

    def _tick(self) -> None:
        self._tick_count += 1
        cfg = _load_job_config()
        if not cfg.get("enabled", True):
            return
        now_beijing = _beijing_now()
        if cfg.get("schedule", {}).get("workday_only", True) and not _is_workday(now_beijing):
            return

        slot = _current_slot(now_beijing)
        if not slot:
            return

        date_key = now_beijing.strftime("%Y-%m-%d")
        if cfg.get("last_run_date") == date_key:
            return

        self._run_once(slot=slot, date_key=date_key)

    def _run_once(self, slot: str, date_key: str) -> dict[str, Any]:
        with self._lock:
            if self._inflight:
                logger.info("[StockUniverseRefreshScheduler] previous run still inflight, skip")
                return {"status": "skipped", "reason": "inflight"}
            self._inflight = True

        started = datetime.now()
        try:
            logger.info(
                "[StockUniverseRefreshScheduler] slot=%s date=%s started",
                slot, date_key,
            )
            # 走 refresh_stock_universe_loop.ps1 (init → groups → run-failed → aggregate)
            result = _run_refresh_loop_script(slot=slot, date_key=date_key)
            elapsed = (datetime.now() - started).total_seconds()

            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_slot"] = slot
            cfg["last_run_date"] = date_key
            cfg["last_status"] = result["status"]
            cfg["last_duration_seconds"] = round(elapsed, 3)
            cfg["last_error"] = result.get("error")
            cfg["last_log_file"] = result.get("log_file")
            cfg["last_exit_code"] = result.get("exit_code")
            cfg["last_file"] = result.get("snapshot_file")
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            if result["status"] != "success":
                cfg["total_failures"] = int(cfg.get("total_failures", 0)) + 1
            _save_job_config(cfg)

            logger.info(
                "[StockUniverseRefreshScheduler] slot=%s status=%s exit=%s elapsed=%.0fs log=%s",
                slot, result["status"], result.get("exit_code"), elapsed, result.get("log_file"),
            )
            return {
                "status": result["status"],
                "slot": slot,
                "date": date_key,
                "elapsed_seconds": elapsed,
                "exit_code": result.get("exit_code"),
                "log_file": result.get("log_file"),
                "file": result.get("snapshot_file"),
            }
        except Exception as exc:
            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_slot"] = slot
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "failed"
            cfg["last_duration_seconds"] = round((datetime.now() - started).total_seconds(), 3)
            cfg["last_error"] = str(exc)
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + 1
            _save_job_config(cfg)
            logger.warning("[StockUniverseRefreshScheduler] slot=%s failed: %s", slot, exc)
            return {"status": "failed", "slot": slot, "error": str(exc)}
        finally:
            with self._lock:
                self._inflight = False


# ---------------------------------------------------------------------------
# 单例 + 启停 API
# ---------------------------------------------------------------------------

_singleton: StockUniverseRefreshScheduler | None = None
_singleton_lock = threading.Lock()


def get_stock_universe_scheduler() -> StockUniverseRefreshScheduler:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = StockUniverseRefreshScheduler()
        return _singleton


def start_stock_universe_scheduler() -> None:
    get_stock_universe_scheduler().start()


def stop_stock_universe_scheduler() -> None:
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()


def is_stock_universe_scheduler_enabled() -> bool:
    return os.getenv("MINIMAX_STOCK_UNIVERSE_SCHEDULER_ENABLED", "1") not in {"0", "false", "False", "no"}


def get_stock_universe_scheduler_status() -> dict[str, Any]:
    return get_stock_universe_scheduler().status()
