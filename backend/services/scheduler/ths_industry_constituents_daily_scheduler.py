"""同花顺 90 行业成分股 **每日 17:00** 收盘后快照调度器 (hexin-v 破解).

跟 :mod:`backend.services.scheduler.ths_industry_constituents_scheduler` (每周六 18:00 周度全量)
的差异:

  - **每日 17:00** (每个交易日跑, 周末/节假日跳过)
  - 落盘位置一样: ``reference/ths-industry/constituents/{code}.json``
  - API 默认从磁盘读 → 非交易时间 drawer 自动拿到 17:00 那次最新落盘, 不会反复爬

启停:
  - :mod:`backend.bootstrap` 调 :func:`start_ths_industry_constituents_daily_scheduler`
  - 关: 环境变量 ``MINIMAX_THS_INDUSTRY_CONSTITUENTS_DAILY_SCHEDULER_ENABLED=0``

Job 配置 + 状态: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\ths_industry_constituents_daily_job.json``
Jobs 注册表:     ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import os
import random
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.stock.trading_calendar import is_trading_day


# ---------------------------------------------------------------------------
# 时间窗工具 (naive 北京时间)
# ---------------------------------------------------------------------------


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


# ---------------------------------------------------------------------------
# Job 状态 / 配置
# ---------------------------------------------------------------------------


DEFAULT_JOB_CONFIG: dict[str, Any] = {
    "job_name": "ths_industry_constituents_daily",
    "description": (
        "每个交易日 17:00 (北京时间) 跑 90 行业全量成分股 (hexin-v 破解), "
        "落盘 reference/ths-industry/constituents/{code}.json, "
        "API 默认从磁盘读 → 非交易时间 drawer 自动拿到 17:00 那次最新落盘数据"
    ),
    "enabled": True,
    "schedule": {
        "run_time": "17:00",        # 北京时间, A 股收盘后
        "trading_day_only": True,   # True=只在交易日跑, 周末/节假日跳过
    },
    "timezone_offset_hours": 8,
    "tick_seconds": 60,
    "inter_industry_sleep_seconds": 1.5,
    "inter_industry_sleep_jitter": 0.5,
    # last run 状态
    "last_run_at": None,
    "last_run_date": None,        # ISO date "2026-06-10"
    "last_status": "idle",        # idle / running / success / partial_failed / failed / skipped_non_trading_day
    "last_industry_count": 0,
    "last_total_rows": 0,
    "last_failed_codes": [],
    "last_duration_seconds": None,
    "last_error": None,
    "total_runs": 0,
    "total_trading_day_runs": 0,
    "total_industries_crawled": 0,
    "total_failures": 0,
    "total_skipped_non_trading_day": 0,
}


def _load_job_config() -> dict[str, Any]:
    cfg = load_status("ths_industry_constituents_daily")
    if not cfg:
        cfg = dict(DEFAULT_JOB_CONFIG)
    for key, value in DEFAULT_JOB_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def _save_job_config(cfg: dict[str, Any]) -> None:
    save_status("ths_industry_constituents_daily", cfg)


def _register_job() -> None:
    """把 ths_industry_constituents_daily job 注册到 DB. 幂等."""
    register_job(
        code="ths_industry_constituents_daily",
        name="同花顺 90 行业成分股 (每个交易日 17:00 收盘后 hexin-v 抓快照)",
        description="每个交易日 17:00 全量重爬 90 行业成分股 (hexin-v 破解), "
        "落盘 reference/ths-industry/constituents/{code}.json, "
        "API 默认从磁盘读, 非交易时间 drawer 自动拿到 17:00 那次最新落盘数据",
        service_module="backend.services.scheduler.ths_industry_constituents_daily_scheduler",
        service_class="ThsIndustryConstituentsDailyScheduler",
        config_file="ths_industry_constituents_daily_job.json",
        default_config=dict(DEFAULT_JOB_CONFIG),
    )


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


class ThsIndustryConstituentsDailyScheduler:
    """同花顺 90 行业成分股每日 17:00 收盘后快照 (每 60s tick 一次)."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._inflight: bool = False
        self._lock = threading.Lock()
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
                "[ThsIndustryConstituentsDailyScheduler] disabled by config, not started",
                flush=True,
            )
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ThsIndustryConstituentsDailyScheduler",
            daemon=True,
        )
        self._thread.start()
        self._started_at = datetime.now()
        _save_job_config(cfg)
        print("[ThsIndustryConstituentsDailyScheduler] started", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._started_at = None
        print("[ThsIndustryConstituentsDailyScheduler] stopped", flush=True)

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
        """手动触发一次全量重爬 (绕开时间窗 + 交易日检查)."""
        with self._lock:
            if self._inflight:
                return {"status": "skipped", "reason": "inflight"}
        return self._run_once(force=True)

    # -------- 主循环 --------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(
                    f"[ThsIndustryConstituentsDailyScheduler] tick error: {exc}",
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
        target_time = str(sched.get("run_time", "17:00"))
        hh, mm = (int(x) for x in target_time.split(":"))
        if not (now_beijing.hour == hh and now_beijing.minute == mm):
            return
        today = now_beijing.date()
        # 周末 / 节假日: 改按最近一个交易日 (target_date) 跑, 避免 cron 漏跑
        # (e.g. 周五 cron 没触发 / 周一 17:00 节假日, 一并按上一个交易日补齐)
        target_date = today
        if sched.get("trading_day_only", True) and not is_trading_day(today):
            from backend.services.stock.trading_day_resolver import resolve_target_trading_day
            target_date = resolve_target_trading_day(today)
            print(
                f"[ThsIndustryConstituentsDailyScheduler] {today.isoformat()} 非交易日, "
                f"改按 {target_date.isoformat()} 跑",
                flush=True,
            )
        # 同日(以上一次 target_date 计)只跑一次
        target_iso = target_date.isoformat()
        if cfg.get("last_run_date") == target_iso:
            return
        self._run_once(target_date=target_date)

    def _run_once(self, *, force: bool = False, target_date: date | None = None) -> dict[str, Any]:
        # 包裹: 跑完后写一条 history entry. 跨 try/finally 跨返回点.
        from backend.services.scheduler.job_history import get_trigger_type
        start_at_iso = datetime.now().isoformat(timespec="seconds")
        start_dt = datetime.now()
        _hist_status = "failed"
        _hist_error: str | None = None
        try:
            return self._run_once_inner(force=force, target_date=target_date)
        except Exception as exc:
            _hist_error = f"{type(exc).__name__}: {exc}"[:300]
            raise
        finally:
            # 读 cfg 取最终 status
            try:
                cfg = _load_job_config()
                # last_status: success | partial_failed | failed | skipped_non_trading_day
                ls = str(cfg.get("last_status") or "")
                if "success" in ls and "partial" not in ls:
                    _hist_status = "success"
                elif ls:
                    _hist_status = "failed"
            except Exception:
                pass
            from backend.services.scheduler.job_history import record_run
            record_run(
                "ths_industry_constituents_daily",
                status=_hist_status,
                duration_seconds=(datetime.now() - start_dt).total_seconds(),
                start_at=start_at_iso,
                end_at=datetime.now().isoformat(timespec="seconds"),
                error=_hist_error,
                trigger_type=get_trigger_type(),
            )

    def _run_once_inner(self, *, force: bool = False, target_date: date | None = None) -> dict[str, Any]:
        with self._lock:
            if self._inflight:
                print(
                    "[ThsIndustryConstituentsDailyScheduler] previous run still inflight, skip",
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
            from backend.services.stock.f10.ths_industry_constituents_service import (
                refresh_industry_constituents,
            )
            from backend.services.stock.f10.ths_industry_service import get_industry_list

            items = get_industry_list()
            codes = list(items.keys())
            with self._lock:
                self._current_progress["total_count"] = len(codes)

            print(
                f"[ThsIndustryConstituentsDailyScheduler] started "
                f"(force={force}) industries={len(codes)}",
                flush=True,
            )

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
                        f"[ThsIndustryConstituentsDailyScheduler] {code} failed: {exc}",
                        flush=True,
                    )
                    failed_codes.append(code)
                    with self._lock:
                        self._current_progress["failed_codes"] = list(failed_codes)
                if self._stop_event.is_set():
                    print(
                        "[ThsIndustryConstituentsDailyScheduler] stop requested, abort loop",
                        flush=True,
                    )
                    break
                if sleep_sec > 0 and idx < len(codes):
                    jitter = 1.0 + random.uniform(-sleep_jit, sleep_jit)
                    time.sleep(sleep_sec * jitter)

            elapsed = (datetime.now() - started).total_seconds()
            status = (
                "success" if not failed_codes
                else ("partial_failed" if ok_codes else "failed")
            )

            cfg = _load_job_config()
            now_beijing = _beijing_now()
            cfg["last_run_at"] = datetime.now().isoformat()
            # last_run_date 记录"这次跑覆盖了哪个交易日":
            # - 正常交易日跑 → 用 today
            # - 周末/节假日 cron 触发, 走 resolver 改跑 target_date → 用 target_date
            cfg["last_run_date"] = (target_date or now_beijing.date()).isoformat()
            cfg["last_status"] = status
            cfg["last_industry_count"] = len(ok_codes)
            cfg["last_total_rows"] = total_rows
            cfg["last_failed_codes"] = failed_codes
            cfg["last_duration_seconds"] = round(elapsed, 3)
            cfg["last_error"] = None
            cfg["total_runs"] = int(cfg.get("total_runs", 0)) + 1
            if not force:
                cfg["total_trading_day_runs"] = (
                    int(cfg.get("total_trading_day_runs", 0)) + 1
                )
            cfg["total_industries_crawled"] = (
                int(cfg.get("total_industries_crawled", 0)) + len(ok_codes)
            )
            cfg["total_failures"] = int(cfg.get("total_failures", 0)) + len(failed_codes)
            _save_job_config(cfg)

            print(
                f"[ThsIndustryConstituentsDailyScheduler] done "
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
                f"[ThsIndustryConstituentsDailyScheduler] failed: {exc}",
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


_singleton: ThsIndustryConstituentsDailyScheduler | None = None
_singleton_lock = threading.Lock()


def get_ths_industry_constituents_daily_scheduler() -> ThsIndustryConstituentsDailyScheduler:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ThsIndustryConstituentsDailyScheduler()
        return _singleton


def start_ths_industry_constituents_daily_scheduler() -> None:
    get_ths_industry_constituents_daily_scheduler().start()


def stop_ths_industry_constituents_daily_scheduler() -> None:
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()


def is_ths_industry_constituents_daily_scheduler_enabled() -> bool:
    return os.getenv(
        "MINIMAX_THS_INDUSTRY_CONSTITUENTS_DAILY_SCHEDULER_ENABLED", "1"
    ) not in {"0", "false", "False", "no"}


def get_ths_industry_constituents_daily_scheduler_status() -> dict[str, Any]:
    return get_ths_industry_constituents_daily_scheduler().status()
