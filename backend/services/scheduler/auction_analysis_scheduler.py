"""集合竞价 AI 分析调度器。

工作日北京时间 09:26 之后，对 application-analysis targets 中 enabled 的标的
逐个生成竞价 AI 解读，并持久化到 ``reference/application-analysis/auction/``。
前端盘中读取该持久化结果，不再因打开 tab 而触发 AI 调用。
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from backend.services.scheduler.config_store import load_config, save_config, register_job
from backend.services.stock.application_analysis_store import load_targets
from backend.services.stock.auction_ai_analysis_service import run_auction_ai_analysis_target


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _is_workday(now: datetime) -> bool:
    return now.weekday() < 5


DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG: dict[str, Any] = {
    "job_name": "auction_ai_analysis",
    "description": "工作日 09:26 后，对 application-analysis targets 中 enabled 标的生成集合竞价 AI 解读并持久化",
    "enabled": True,
    "schedule": {
        "workday_only": True,
        "run_time": "09:26",
        "run_once_per_day": True,
    },
    "timezone_offset_hours": 8,
    "tick_seconds": 30,
    "last_run_at": None,
    "last_run_date": None,
    "last_status": "idle",
    "last_targets_processed": 0,
    "last_duration_seconds": None,
    "last_error": None,
    "total_runs": 0,
    "total_targets_processed": 0,
    "total_failures": 0,
}


def _load_job_config() -> dict[str, Any]:
    cfg = load_config("auction_ai_analysis")
    if not cfg:
        cfg = dict(DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG)
    for key, value in DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    schedule = cfg.get("schedule")
    if not isinstance(schedule, dict):
        cfg["schedule"] = dict(DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG["schedule"])
    else:
        for key, value in DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG["schedule"].items():
            schedule.setdefault(key, value)
    return cfg


def _save_job_config(cfg: dict[str, Any]) -> None:
    save_config("auction_ai_analysis", cfg)


def _register_job() -> None:
    register_job(
        code="auction_ai_analysis",
        name="集合竞价 AI 分析",
        description=DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG["description"],
        service_module="backend.services.scheduler.auction_analysis_scheduler",
        service_class="AuctionAnalysisScheduler",
        config_file="auction_analysis_job.json",
        default_config=dict(DEFAULT_AUCTION_ANALYSIS_JOB_CONFIG),
    )


def _time_reached(now: datetime, run_time: str) -> bool:
    try:
        hour_text, minute_text = str(run_time or "09:26").split(":", 1)
        target_hour = int(hour_text)
        target_minute = int(minute_text)
    except (TypeError, ValueError):
        target_hour = 9
        target_minute = 26
    return (now.hour, now.minute) >= (target_hour, target_minute)


class AuctionAnalysisScheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._inflight = False
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        _register_job()
        cfg = _load_job_config()
        if not cfg.get("enabled", True):
            print("[AuctionAnalysisScheduler] disabled by config, not started", flush=True)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="AuctionAnalysisScheduler", daemon=True)
        self._thread.start()
        self._started_at = datetime.now()
        _save_job_config(cfg)
        print("[AuctionAnalysisScheduler] started", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        print("[AuctionAnalysisScheduler] stopped", flush=True)

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
        return self._run_once(date_key=_beijing_now().strftime("%Y-%m-%d"), source="manual")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(f"[AuctionAnalysisScheduler] tick error: {exc}", flush=True)
                traceback.print_exc()
            cfg = _load_job_config()
            self._stop_event.wait(int(cfg.get("tick_seconds") or 30))

    def _tick(self) -> None:
        self._tick_count += 1
        cfg = _load_job_config()
        if not cfg.get("enabled", True):
            return

        now = _beijing_now()
        schedule = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {}
        if schedule.get("workday_only", True) and not _is_workday(now):
            return
        if not _time_reached(now, str(schedule.get("run_time") or "09:26")):
            return

        date_key = now.strftime("%Y-%m-%d")
        if schedule.get("run_once_per_day", True) and cfg.get("last_run_date") == date_key:
            return

        self._run_once(date_key=date_key, source="scheduler")

    def _run_once(self, date_key: str, source: str) -> dict[str, Any]:
        with self._lock:
            if self._inflight:
                return {"ok": False, "status": "skipped", "reason": "inflight"}
            self._inflight = True

        started = datetime.now()
        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        try:
            targets = [item for item in load_targets().get("items", []) if item.get("enabled", True)]
            print(f"[AuctionAnalysisScheduler] source={source} date={date_key} targets={len(targets)} started", flush=True)
            for target in targets:
                target_id = target.get("id") or f"{target.get('target_type')}-{target.get('symbol')}"
                try:
                    item_started = time.monotonic()
                    payload = run_auction_ai_analysis_target(target, date_key=date_key)
                    elapsed = round(time.monotonic() - item_started, 3)
                    succeeded += 1
                    results.append({
                        "id": target_id,
                        "status": "success",
                        "elapsed_seconds": elapsed,
                        "snapshot_path": payload.get("snapshot_path"),
                        "date": payload.get("date"),
                    })
                except Exception as exc:
                    failed += 1
                    results.append({
                        "id": target_id,
                        "status": "failed",
                        "error": str(exc),
                    })
                    print(f"[AuctionAnalysisScheduler] target={target_id} failed: {exc}", flush=True)

            elapsed_total = round((datetime.now() - started).total_seconds(), 3)
            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "success" if failed == 0 else "partial_failed"
            cfg["last_targets_processed"] = succeeded + failed
            cfg["last_duration_seconds"] = elapsed_total
            cfg["last_error"] = None if failed == 0 else f"{failed} targets failed"
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_targets_processed"] = int(cfg.get("total_targets_processed", 0)) + succeeded + failed
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + failed
            _save_job_config(cfg)
            print(f"[AuctionAnalysisScheduler] done ok={succeeded} fail={failed} elapsed={elapsed_total}s", flush=True)
            return {
                "ok": failed == 0,
                "status": cfg["last_status"],
                "date": date_key,
                "succeeded": succeeded,
                "failed": failed,
                "items": results,
            }
        except Exception as exc:
            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "failed"
            cfg["last_duration_seconds"] = round((datetime.now() - started).total_seconds(), 3)
            cfg["last_error"] = str(exc)
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + 1
            _save_job_config(cfg)
            return {"ok": False, "status": "failed", "date": date_key, "error": str(exc)}
        finally:
            with self._lock:
                self._inflight = False


_singleton: AuctionAnalysisScheduler | None = None
_singleton_lock = threading.Lock()


def get_auction_analysis_scheduler() -> AuctionAnalysisScheduler:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AuctionAnalysisScheduler()
        return _singleton


def start_auction_analysis_scheduler() -> None:
    get_auction_analysis_scheduler().start()


def stop_auction_analysis_scheduler() -> None:
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()


def is_auction_analysis_scheduler_enabled() -> bool:
    return os.getenv("MINIMAX_AUCTION_ANALYSIS_SCHEDULER_ENABLED", "1") not in {"0", "false", "False", "no"}


def get_auction_analysis_scheduler_status() -> dict[str, Any]:
    return get_auction_analysis_scheduler().status()
