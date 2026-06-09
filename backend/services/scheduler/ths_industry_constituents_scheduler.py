"""同花顺 90 行业成分股刷新调度器 (每周六 18:00, hexin-v 破解).

启动方式：
    在 :mod:`backend.bootstrap` 里调 :func:`start_ths_industry_constituents_scheduler`.
    也可通过环境变量 ``MINIMAX_THS_INDUSTRY_CONSTITUENTS_SCHEDULER_ENABLED=0`` 关闭.

Job 配置 + 状态文件：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\ths_industry_constituents_job.json``
Jobs 注册表：``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``

时间窗：
    - 周六 (weekday=5) 18:00
    - 90 行业全量串行, 每个行业间 sleep 1.5s (随机抖动) 避免触发 q.10jqka 风控
    - 整轮预计 90 * (1.5 + 单行业 ~5-15s) = 10-25 分钟
    - 同一周 (ISO week) 只跑一次, 避免重启后短时间内重复跑

落盘：
    - ``reference/ths-industry/constituents/{code}.json`` 每行业一份
    - API 默认从磁盘读, 磁盘没有才爬网络; 周末后所有 lookups 都返最新落盘数据
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
    SCHEDULER_DIR,
    SCHEDULER_JOBS_FILE,
    SCHEDULER_THS_INDUSTRY_CONSTITUENTS_JOB_FILE,
)
from backend.utils.json_io import read_json_file, write_json_file


# ---------------------------------------------------------------------------
# 时间窗工具 (跟 turnover_scheduler 一样, naive 北京时间)
# ---------------------------------------------------------------------------


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _iso_week_key(now: datetime) -> str:
    """返回 ``YYYY-Www`` (ISO week), 用于同周只跑一次判定."""
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ---------------------------------------------------------------------------
# Job 状态 / 配置
# ---------------------------------------------------------------------------


DEFAULT_JOB_CONFIG: dict[str, Any] = {
    "job_name": "ths_industry_constituents_weekly",
    "description": (
        "每周六 18:00 跑 90 行业全量成分股 (hexin-v 破解), 落盘 reference/ths-industry/constituents/{code}.json, "
        "API 默认从磁盘读, 周末后所有 lookups 都返最新落盘数据"
    ),
    "enabled": True,
    "schedule": {
        "weekday": 5,        # 5=Saturday
        "run_time": "18:00",
        "run_once_per_week": True,
    },
    "timezone_offset_hours": 8,
    "tick_seconds": 60,
    # last run 状态
    "last_run_at": None,
    "last_run_week": None,        # ISO week key, e.g. "2026-W23"
    "last_run_weekday": None,     # 5=Sat
    "last_status": "idle",        # idle / running / success / partial_failed / failed
    "last_industry_count": 0,     # 这次跑了几个行业
    "last_total_rows": 0,         # 这次总共多少只成分股
    "last_failed_codes": [],      # 失败的行业 6 位 code
    "last_duration_seconds": None,
    "last_error": None,
    "total_runs": 0,
    "total_industries_crawled": 0,
    "total_failures": 0,
}


def _load_job_config() -> dict[str, Any]:
    cfg = read_json_file(SCHEDULER_THS_INDUSTRY_CONSTITUENTS_JOB_FILE, None)
    if not isinstance(cfg, dict):
        cfg = dict(DEFAULT_JOB_CONFIG)
    for key, value in DEFAULT_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def _save_job_config(cfg: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    cfg["_saved_at"] = datetime.now().isoformat()
    write_json_file(SCHEDULER_THS_INDUSTRY_CONSTITUENTS_JOB_FILE, cfg)


def _load_jobs_registry() -> dict[str, Any]:
    if not SCHEDULER_JOBS_FILE.exists():
        return {"version": 1, "jobs": []}
    return read_json_file(SCHEDULER_JOBS_FILE, {"version": 1, "jobs": []})


def _register_job() -> None:
    """把 ths_industry_constituents_weekly job 注册到 jobs.json. 幂等."""
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    registry = _load_jobs_registry()
    existing = next(
        (item for item in registry.get("jobs", []) if item.get("id") == "ths_industry_constituents_weekly"),
        None,
    )
    if existing is not None:
        return
    registry.setdefault("jobs", []).append({
        "id": "ths_industry_constituents_weekly",
        "name": "同花顺 90 行业成分股 (每周六 hexin-v 重爬)",
        "description": (
            "每周六 18:00 全量重爬 90 行业成分股 (hexin-v 破解), "
            "落盘 reference/ths-industry/constituents/{code}.json, "
            "API 默认从磁盘读, 周末后所有 lookups 都返最新落盘数据"
        ),
        "config_file": "ths_industry_constituents_job.json",
        "service_module": "backend.services.scheduler.ths_industry_constituents_scheduler",
        "service_class": "ThsIndustryConstituentsScheduler",
        "enabled": True,
        "registered_at": datetime.now().isoformat(),
    })
    write_json_file(SCHEDULER_JOBS_FILE, registry)


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


class ThsIndustryConstituentsScheduler:
    """同花顺 90 行业成分股周度刷新调度器 (每 60s tick 一次)."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._inflight: bool = False
        self._lock = threading.Lock()
        # 当前正在运行的进度 (供 API 实时拉)
        self._current_progress: dict[str, Any] = {
            "running": False,
            "started_at": None,
            "current_code": None,
            "current_index": 0,
            "total_count": 0,
            "last_completed_code": None,
            "last_completed_rows": 0,
            "failed_codes": [],
        }

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        _register_job()
        cfg = _load_job_config()
        if not cfg.get("enabled", True):
            print(
                "[ThsIndustryConstituentsScheduler] disabled by config, not started",
                flush=True,
            )
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ThsIndustryConstituentsScheduler",
            daemon=True,
        )
        self._thread.start()
        self._started_at = datetime.now()
        _save_job_config(cfg)
        print("[ThsIndustryConstituentsScheduler] started", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        print("[ThsIndustryConstituentsScheduler] stopped", flush=True)

    def status(self) -> dict[str, Any]:
        cfg = _load_job_config()
        with self._lock:
            inflight = self._inflight
            progress = dict(self._current_progress)
        return {
            "running": self.is_running(),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "tick_count": self._tick_count,
            "inflight": inflight,
            "config": cfg,
            "progress": progress,
        }

    def trigger_now(self) -> dict[str, Any]:
        """手动触发一次全量重爬 (绕开时间窗)."""
        with self._lock:
            if self._inflight:
                return {"status": "skipped", "reason": "inflight"}
        return self._run_once()

    # -------- 主循环 --------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(
                    f"[ThsIndustryConstituentsScheduler] tick error: {exc}",
                    flush=True,
                )
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
        sched = cfg.get("schedule", {})
        target_weekday = int(sched.get("weekday", 5))
        target_time = str(sched.get("run_time", "18:00"))
        if now_beijing.weekday() != target_weekday:
            return
        hh, mm = (int(x) for x in target_time.split(":"))
        if not (now_beijing.hour == hh and now_beijing.minute == mm):
            return
        # 同周只跑一次
        week_key = _iso_week_key(now_beijing)
        if sched.get("run_once_per_week", True) and cfg.get("last_run_week") == week_key:
            return
        self._run_once()

    def _run_once(self) -> dict[str, Any]:
        with self._lock:
            if self._inflight:
                print(
                    "[ThsIndustryConstituentsScheduler] previous run still inflight, skip",
                    flush=True,
                )
                return {"status": "skipped", "reason": "inflight"}
            self._inflight = True
            self._current_progress = {
                "running": True,
                "started_at": datetime.now().isoformat(),
                "current_code": None,
                "current_index": 0,
                "total_count": 0,
                "last_completed_code": None,
                "last_completed_rows": 0,
                "failed_codes": [],
            }

        started = datetime.now()
        try:
            # 动态 import 避免循环
            from backend.services.stock.f10.ths_industry_constituents_service import (
                refresh_industry_constituents,
            )
            from backend.services.stock.f10.ths_industry_service import (
                get_industry_list,
            )

            items = get_industry_list()
            codes = list(items.keys())
            with self._lock:
                self._current_progress["total_count"] = len(codes)

            print(
                f"[ThsIndustryConstituentsScheduler] started, industries={len(codes)}",
                flush=True,
            )

            import random
            cfg = _load_job_config()
            sleep_sec = float(cfg.get("inter_industry_sleep_seconds", 1.5))
            sleep_jit = float(cfg.get("inter_industry_sleep_jitter", 0.5))

            ok_codes: list[str] = []
            failed_codes: list[str] = []
            total_rows = 0

            for idx, code in enumerate(codes, start=1):
                with self._lock:
                    self._current_progress["current_code"] = code
                    self._current_progress["current_index"] = idx
                try:
                    payload = refresh_industry_constituents(code)
                    rows = payload.get("rows") or []
                    total_rows += len(rows)
                    with self._lock:
                        self._current_progress["last_completed_code"] = code
                        self._current_progress["last_completed_rows"] = len(rows)
                    ok_codes.append(code)
                except Exception as exc:
                    print(
                        f"[ThsIndustryConstituentsScheduler] {code} failed: {exc}",
                        flush=True,
                    )
                    failed_codes.append(code)
                    with self._lock:
                        self._current_progress["failed_codes"] = list(failed_codes)
                if self._stop_event.is_set():
                    print(
                        "[ThsIndustryConstituentsScheduler] stop requested, abort loop",
                        flush=True,
                    )
                    break
                if sleep_sec > 0 and idx < len(codes):
                    jitter = 1.0 + random.uniform(-sleep_jit, sleep_jit)
                    time.sleep(sleep_sec * jitter)

            elapsed = (datetime.now() - started).total_seconds()
            week_key = _iso_week_key(_beijing_now())
            status = (
                "success" if not failed_codes
                else ("partial_failed" if ok_codes else "failed")
            )

            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_run_week"] = week_key
            cfg["last_run_weekday"] = _beijing_now().weekday()
            cfg["last_status"] = status
            cfg["last_industry_count"] = len(ok_codes)
            cfg["last_total_rows"] = total_rows
            cfg["last_failed_codes"] = failed_codes
            cfg["last_duration_seconds"] = round(elapsed, 3)
            cfg["last_error"] = None
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_industries_crawled"] = (
                int(cfg.get("total_industries_crawled", 0)) + len(ok_codes)
            )
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + len(failed_codes)
            _save_job_config(cfg)

            print(
                f"[ThsIndustryConstituentsScheduler] done "
                f"ok={len(ok_codes)}/{len(codes)} rows={total_rows} "
                f"failed={len(failed_codes)} elapsed={elapsed:.1f}s",
                flush=True,
            )
            return {
                "status": status,
                "ok_codes": ok_codes,
                "failed_codes": failed_codes,
                "total_rows": total_rows,
                "elapsed_seconds": elapsed,
            }
        except Exception as exc:
            cfg = _load_job_config()
            cfg["last_run_at"] = datetime.now().isoformat()
            cfg["last_status"] = "failed"
            cfg["last_duration_seconds"] = round(
                (datetime.now() - started).total_seconds(), 3
            )
            cfg["last_error"] = str(exc)
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + 1
            _save_job_config(cfg)
            print(
                f"[ThsIndustryConstituentsScheduler] failed: {exc}",
                flush=True,
            )
            return {"status": "failed", "error": str(exc)}
        finally:
            with self._lock:
                self._inflight = False
                self._current_progress["running"] = False


# ---------------------------------------------------------------------------
# 单例 + 启停 API
# ---------------------------------------------------------------------------


_singleton: ThsIndustryConstituentsScheduler | None = None
_singleton_lock = threading.Lock()


def get_ths_industry_constituents_scheduler() -> ThsIndustryConstituentsScheduler:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ThsIndustryConstituentsScheduler()
        return _singleton


def start_ths_industry_constituents_scheduler() -> None:
    get_ths_industry_constituents_scheduler().start()


def stop_ths_industry_constituents_scheduler() -> None:
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()


def is_ths_industry_constituents_scheduler_enabled() -> bool:
    return os.getenv(
        "MINIMAX_THS_INDUSTRY_CONSTITUENTS_SCHEDULER_ENABLED", "1"
    ) not in {"0", "false", "False", "no"}


def get_ths_industry_constituents_scheduler_status() -> dict[str, Any]:
    return get_ths_industry_constituents_scheduler().status()
