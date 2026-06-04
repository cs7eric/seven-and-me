"""换手率刷新调度器（盘内 30 分钟 + 16:00 收盘后）。

启动方式：
    在 :mod:`backend.bootstrap` 里调 :func:`start_turnover_scheduler`。
    也可通过环境变量 ``MINIMAX_TURNOVER_SCHEDULER_ENABLED=0`` 关闭。

Job 配置 + 状态文件：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\turnover_job.json``。
Jobs 注册表：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``。

时间窗：
    - 工作日（周一~周五，按 ``datetime.weekday()`` 判定，TODO: 接 eltdx 交易日历排除节假日）
    - 上午 9:30 - 11:30：每半小时（09:30, 10:00, 10:30, 11:00, 11:30）
    - 下午 13:00 - 15:00：每半小时（13:00, 13:30, 14:00, 14:30, 15:00）
    - 收盘后 16:00：跑一次
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from backend.config.settings import (
    APPLICATION_ANALYSIS_TARGETS_FILE,
    SCHEDULER_DIR,
    SCHEDULER_JOBS_FILE,
    SCHEDULER_TURNOVER_JOB_FILE,
)
from backend.services.stock.application_analysis_store import load_targets
from backend.services.stock.f10.turnover import refresh_all_targets_turnover
from backend.utils.json_io import read_json_file, write_json_file


# ---------------------------------------------------------------------------
# 时间窗工具
# ---------------------------------------------------------------------------


def _beijing_now() -> datetime:
    """当前北京时间（naive datetime，tz=Asia/Shanghai 等价）。"""
    return datetime.utcnow() + timedelta(hours=8)


def _is_workday(now: datetime) -> bool:
    """简单判断：周一~周五。后续可接 eltdx 交易日历做更精确的判定。"""
    return now.weekday() < 5  # 0=Mon, 6=Sun


def _current_slot(now: datetime) -> str | None:
    """返回当前时间对应的调度 slot key。

    Slot 列表：
        09:30, 10:00, 10:30, 11:00, 11:30, 13:00, 13:30, 14:00, 14:30, 15:00, 16:00
    """
    h, m = now.hour, now.minute
    # 上午 9:30 - 11:30
    if h == 9 and 30 <= m:
        return "09:30"
    if h == 10:
        return f"10:{m // 30 * 30:02d}"
    if h == 11 and m <= 30:
        return f"11:{m // 30 * 30:02d}"
    # 下午 13:00 - 15:00
    if 13 <= h <= 14:
        return f"{h:02d}:{m // 30 * 30:02d}"
    if h == 15 and m == 0:
        return "15:00"
    # 收盘后 16:00
    if h == 16 and m == 0:
        return "16:00"
    return None


# ---------------------------------------------------------------------------
# Job 状态 / 配置
# ---------------------------------------------------------------------------


DEFAULT_TURNOVER_JOB_CONFIG: dict[str, Any] = {
    "job_name": "turnover_refresh",
    "description": "工作日盘内每半小时 + 16:00 收盘后，刷新 target.json 中所有标的的换手率",
    "enabled": True,
    "schedule": {
        "workday_only": True,
        "intraday_windows": [
            {"start": "09:30", "end": "11:30", "every_minutes": 30},
            {"start": "13:00", "end": "15:00", "every_minutes": 30},
        ],
        "post_close_run": "16:00",
    },
    "timezone_offset_hours": 8,
    "tick_seconds": 30,
    "last_run_at": None,
    "last_run_slot": None,
    "last_run_date": None,
    "last_status": "idle",
    "last_targets_processed": 0,
    "last_duration_seconds": None,
    "last_error": None,
    "total_runs": 0,
    "total_targets_processed": 0,
    "total_failures": 0,
}


def _load_turnover_job_config() -> dict[str, Any]:
    cfg = read_json_file(SCHEDULER_TURNOVER_JOB_FILE, None)
    if not isinstance(cfg, dict):
        cfg = dict(DEFAULT_TURNOVER_JOB_CONFIG)
    # 字段补全（防止老文件缺字段）
    for key, value in DEFAULT_TURNOVER_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def _save_turnover_job_config(cfg: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    cfg["_saved_at"] = datetime.now().isoformat()
    write_json_file(SCHEDULER_TURNOVER_JOB_FILE, cfg)


def _load_jobs_registry() -> dict[str, Any]:
    if not SCHEDULER_JOBS_FILE.exists():
        return {"version": 1, "jobs": []}
    return read_json_file(SCHEDULER_JOBS_FILE, {"version": 1, "jobs": []})


def _register_turnover_job() -> None:
    """把 turnover_refresh job 注册到 ``jobs.json``。幂等。"""
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    registry = _load_jobs_registry()
    existing = next(
        (item for item in registry.get("jobs", []) if item.get("id") == "turnover_refresh"),
        None,
    )
    if existing is None:
        registry.setdefault("jobs", []).append({
            "id": "turnover_refresh",
            "name": "换手率刷新",
            "description": "工作日盘内每半小时 + 16:00 收盘后，刷新 target.json 中所有标的的换手率",
            "config_file": "turnover_job.json",
            "service_module": "backend.services.scheduler.turnover_scheduler",
            "service_class": "TurnoverRefreshScheduler",
            "enabled": True,
            "registered_at": datetime.now().isoformat(),
        })
        write_json_file(SCHEDULER_JOBS_FILE, registry)


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


class TurnoverRefreshScheduler:
    """换手率刷新后台调度器（每 30 秒 tick 一次）。"""

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
        _register_turnover_job()
        cfg = _load_turnover_job_config()
        if not cfg.get("enabled", True):
            print("[TurnoverRefreshScheduler] disabled by config, not started", flush=True)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="TurnoverRefreshScheduler", daemon=True
        )
        self._thread.start()
        self._started_at = datetime.now()
        _save_turnover_job_config(cfg)
        print("[TurnoverRefreshScheduler] started", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        print("[TurnoverRefreshScheduler] stopped", flush=True)

    def status(self) -> dict[str, Any]:
        cfg = _load_turnover_job_config()
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
        """手动触发一次刷新（绕开时间窗），主要给路由 / 调试用。"""
        return self._run_once(slot="manual", date_key=datetime.now().strftime("%Y-%m-%d"))

    # -------- 主循环 --------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(f"[TurnoverRefreshScheduler] tick error: {exc}", flush=True)
                traceback.print_exc()
            cfg = _load_turnover_job_config()
            sleep_seconds = int(cfg.get("tick_seconds") or 30)
            self._stop_event.wait(sleep_seconds)

    def _tick(self) -> None:
        self._tick_count += 1
        cfg = _load_turnover_job_config()
        if not cfg.get("enabled", True):
            return
        now_beijing = _beijing_now()
        if cfg.get("schedule", {}).get("workday_only", True) and not _is_workday(now_beijing):
            return

        slot = _current_slot(now_beijing)
        if not slot:
            return

        date_key = now_beijing.strftime("%Y-%m-%d")
        # 同一天同 slot 只跑一次
        if cfg.get("last_run_date") == date_key and cfg.get("last_run_slot") == slot:
            return

        self._run_once(slot=slot, date_key=date_key)

    def _run_once(self, slot: str, date_key: str) -> dict[str, Any]:
        with self._lock:
            if self._inflight:
                print("[TurnoverRefreshScheduler] previous run still inflight, skip", flush=True)
                return {"status": "skipped", "reason": "inflight"}
            self._inflight = True

        started = datetime.now()
        try:
            targets = load_targets().get("items", [])
            enabled_count = sum(1 for t in targets if t.get("enabled", True))
            print(
                f"[TurnoverRefreshScheduler] slot={slot} date={date_key} targets={enabled_count} started",
                flush=True,
            )
            result = refresh_all_targets_turnover(targets)
            elapsed = (datetime.now() - started).total_seconds()

            cfg = _load_turnover_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_slot"] = slot
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "success" if result.get("failed", 0) == 0 else "partial_failed"
            cfg["last_targets_processed"] = result.get("total", 0)
            cfg["last_duration_seconds"] = round(elapsed, 3)
            cfg["last_error"] = None
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_targets_processed"] = int(cfg.get("total_targets_processed", 0)) + result.get("total", 0)
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + result.get("failed", 0)
            _save_turnover_job_config(cfg)

            print(
                f"[TurnoverRefreshScheduler] slot={slot} done "
                f"ok={result.get('succeeded', 0)} fail={result.get('failed', 0)} "
                f"elapsed={elapsed:.2f}s",
                flush=True,
            )
            return {
                "status": cfg["last_status"],
                "slot": slot,
                "date": date_key,
                "elapsed_seconds": elapsed,
                "result": result,
            }
        except Exception as exc:
            cfg = _load_turnover_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_slot"] = slot
            cfg["last_run_date"] = date_key
            cfg["last_status"] = "failed"
            cfg["last_duration_seconds"] = round((datetime.now() - started).total_seconds(), 3)
            cfg["last_error"] = str(exc)
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + 1
            _save_turnover_job_config(cfg)
            print(f"[TurnoverRefreshScheduler] slot={slot} failed: {exc}", flush=True)
            return {"status": "failed", "slot": slot, "error": str(exc)}
        finally:
            with self._lock:
                self._inflight = False


# ---------------------------------------------------------------------------
# 单例 + 启停 API
# ---------------------------------------------------------------------------


_singleton: TurnoverRefreshScheduler | None = None
_singleton_lock = threading.Lock()


def get_turnover_scheduler() -> TurnoverRefreshScheduler:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = TurnoverRefreshScheduler()
        return _singleton


def start_turnover_scheduler() -> None:
    get_turnover_scheduler().start()


def stop_turnover_scheduler() -> None:
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()


def is_turnover_scheduler_enabled() -> bool:
    return os.getenv("MINIMAX_TURNOVER_SCHEDULER_ENABLED", "1") not in {"0", "false", "False", "no"}


def get_turnover_scheduler_status() -> dict[str, Any]:
    return get_turnover_scheduler().status()
