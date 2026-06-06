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

import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from backend.config.settings import (
    SCHEDULER_DIR,
    SCHEDULER_JOBS_FILE,
)
from backend.services.stock import stock_universe_service
from backend.utils.json_io import read_json_file, write_json_file


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
    "last_stock_count": 0,
    "last_industry_count": 0,
    "last_topic_count": 0,
    "last_duration_seconds": None,
    "last_error": None,
    "last_file": None,
    "total_runs": 0,
    "total_failures": 0,
}


_JOB_FILE = SCHEDULER_DIR / "stock_universe_job.json"


def _load_job_config() -> dict[str, Any]:
    cfg = read_json_file(_JOB_FILE, None)
    if not isinstance(cfg, dict):
        cfg = dict(DEFAULT_JOB_CONFIG)
    for key, value in DEFAULT_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def _save_job_config(cfg: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    cfg["_saved_at"] = datetime.now().isoformat()
    write_json_file(_JOB_FILE, cfg)


def _load_jobs_registry() -> dict[str, Any]:
    if not SCHEDULER_JOBS_FILE.exists():
        return {"version": 1, "jobs": []}
    return read_json_file(SCHEDULER_JOBS_FILE, {"version": 1, "jobs": []})


def _register_job() -> None:
    """把 stock_universe_refresh job 注册到 jobs.json (幂等)."""
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    registry = _load_jobs_registry()
    existing = next(
        (item for item in registry.get("jobs", []) if item.get("id") == "stock_universe_refresh"),
        None,
    )
    if existing is None:
        registry.setdefault("jobs", []).append({
            "id": "stock_universe_refresh",
            "name": "A 股全市场持久化",
            "description": "工作日 17:00 收盘后拉全 A 股行情 + 题材 + 行业归一, 持久化到 reference/stock-universe/",
            "config_file": "stock_universe_job.json",
            "service_module": "backend.services.scheduler.stock_universe_scheduler",
            "service_class": "StockUniverseRefreshScheduler",
            "enabled": True,
            "registered_at": datetime.now().isoformat(),
        })
        write_json_file(SCHEDULER_JOBS_FILE, registry)


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


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
            print("[StockUniverseRefreshScheduler] disabled by config, not started", flush=True)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="StockUniverseRefreshScheduler", daemon=True
        )
        self._thread.start()
        self._started_at = datetime.now()
        _save_job_config(cfg)
        print("[StockUniverseRefreshScheduler] started", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        print("[StockUniverseRefreshScheduler] stopped", flush=True)

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
                print(f"[StockUniverseRefreshScheduler] tick error: {exc}", flush=True)
                traceback.print_exc()
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
                print("[StockUniverseRefreshScheduler] previous run still inflight, skip", flush=True)
                return {"status": "skipped", "reason": "inflight"}
            self._inflight = True

        started = datetime.now()
        try:
            print(
                f"[StockUniverseRefreshScheduler] slot={slot} date={date_key} started",
                flush=True,
            )
            # 关闭 progress 打印, 走 service 自带的 print
            result = stock_universe_service.refresh(progress=True)
            elapsed = (datetime.now() - started).total_seconds()

            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_slot"] = slot
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "success"
            cfg["last_stock_count"] = result.stock_count
            cfg["last_industry_count"] = result.industry_count
            cfg["last_topic_count"] = result.topic_count
            cfg["last_duration_seconds"] = round(elapsed, 3)
            cfg["last_file"] = str(result.file_path)
            cfg["last_error"] = None
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            _save_job_config(cfg)

            print(
                f"[StockUniverseRefreshScheduler] slot={slot} done "
                f"stocks={result.stock_count} industries={result.industry_count} "
                f"topics={result.topic_count} elapsed={elapsed:.0f}s",
                flush=True,
            )
            return {
                "status": "success",
                "slot": slot,
                "date": date_key,
                "elapsed_seconds": elapsed,
                "stock_count": result.stock_count,
                "industry_count": result.industry_count,
                "topic_count": result.topic_count,
                "file": str(result.file_path),
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
            print(f"[StockUniverseRefreshScheduler] slot={slot} failed: {exc}", flush=True)
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
