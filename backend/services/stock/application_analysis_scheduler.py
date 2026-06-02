from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime
from typing import Any

from backend.services.stock.application_analysis_service import run_application_analysis_target
from backend.services.stock.application_analysis_store import (
    list_result_files,
    load_scheduler_status,
    load_targets,
    read_result,
    save_scheduler_status,
    touch_updated_marker,
    write_result,
)


class ApplicationAnalysisScheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_lock = threading.Lock()
        self._inflight: dict[str, datetime] = {}
        self._inflight_lock = threading.Lock()
        self._last_run: dict[str, dict[str, Any]] = {}
        self._last_run_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._runs_count = 0

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name='ApplicationAnalysisScheduler', daemon=True)
        self._thread.start()
        with self._status_lock:
            self._started_at = datetime.now()
        self._persist_status()
        print('[ApplicationAnalysisScheduler] started', flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        with self._status_lock:
            self._started_at = None
        self._persist_status()
        print('[ApplicationAnalysisScheduler] stopped', flush=True)

    def status(self) -> dict[str, Any]:
        targets = load_targets().get('items', [])
        enabled_count = sum(1 for item in targets if item.get('enabled'))
        with self._status_lock:
            started_at = self._started_at.isoformat() if self._started_at else None
        with self._inflight_lock:
            inflight = {key: value.isoformat() for key, value in self._inflight.items()}
        with self._last_run_lock:
            last_run_copy = {key: dict(value) for key, value in self._last_run.items()}
        return {
            'running': self.is_running(),
            'started_at': started_at,
            'tick_count': self._tick_count,
            'runs_count': self._runs_count,
            'enabled_target_count': enabled_count,
            'total_target_count': len(targets),
            'inflight': inflight,
            'last_run': last_run_copy,
        }

    def trigger_target(self, target_id: str, source: str = 'manual') -> dict[str, Any]:
        targets = {item['id']: item for item in load_targets().get('items', []) if item.get('id')}
        target = targets.get(target_id)
        if not target:
            return {'ok': False, 'error': f'target {target_id} not found'}
        with self._run_lock:
            with self._inflight_lock:
                if target_id in self._inflight:
                    return {'ok': False, 'error': f'target {target_id} already running', 'started_at': self._inflight[target_id].isoformat()}
                self._inflight[target_id] = datetime.now()
            try:
                print(f'[ApplicationAnalysisScheduler] trigger target={target_id} source={source}', flush=True)
                started = time.monotonic()
                payload = run_application_analysis_target(target)
                paths = write_result(target, payload)
                elapsed = int(time.monotonic() - started)
                last_run = {
                    'status': 'success',
                    'elapsed_seconds': elapsed,
                    'source': source,
                    'finished_at': datetime.now().isoformat(),
                    'result_path': paths.get('result_path'),
                    'history_path': paths.get('history_path'),
                    'overlay_count': len((payload.get('analysis_result') or {}).get('overlay_annotations') or []),
                    'segments': (payload.get('segments') or {}).get('count'),
                    'horizon': payload.get('horizon'),
                }
                with self._last_run_lock:
                    self._last_run[target_id] = last_run
                self._persist_status()
                return {'ok': True, 'target_id': target_id, 'result_path': paths.get('result_path'), 'history_path': paths.get('history_path'), 'elapsed_seconds': elapsed}
            except Exception as exc:
                tb = traceback.format_exc()
                print(f'[ApplicationAnalysisScheduler] trigger target={target_id} failed: {exc}\n{tb}', flush=True)
                last_run = {
                    'status': 'failed',
                    'error': str(exc),
                    'source': source,
                    'finished_at': datetime.now().isoformat(),
                }
                with self._last_run_lock:
                    self._last_run[target_id] = last_run
                self._persist_status()
                return {'ok': False, 'target_id': target_id, 'error': str(exc)}
            finally:
                with self._inflight_lock:
                    self._inflight.pop(target_id, None)

    def trigger_all(self, source: str = 'manual_all') -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in load_targets().get('items', []):
            if not item.get('enabled'):
                continue
            results.append(self.trigger_target(item.get('id'), source=source))
        return results

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick_count += 1
            try:
                self._tick()
            except Exception as exc:
                print(f'[ApplicationAnalysisScheduler] tick error: {exc}', flush=True)
            self._persist_status()
            sleep_seconds = 30
            self._stop_event.wait(sleep_seconds)

    def _tick(self) -> None:
        targets = load_targets().get('items', [])
        now = datetime.now()
        for target in targets:
            if not target.get('enabled'):
                continue
            target_id = target.get('id')
            interval_minutes = max(5, int(target.get('interval_minutes') or 60))
            with self._last_run_lock:
                last = self._last_run.get(target_id)
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.get('finished_at'))
                except (TypeError, ValueError):
                    last_dt = None
                if last_dt and (now - last_dt).total_seconds() < interval_minutes * 60:
                    continue
            with self._inflight_lock:
                if target_id in self._inflight:
                    continue
            with self._run_lock:
                with self._inflight_lock:
                    self._inflight[target_id] = now
                try:
                    started = time.monotonic()
                    payload = run_application_analysis_target(target)
                    paths = write_result(target, payload)
                    elapsed = int(time.monotonic() - started)
                    self._runs_count += 1
                    with self._last_run_lock:
                        self._last_run[target_id] = {
                            'status': 'success',
                            'elapsed_seconds': elapsed,
                            'source': 'scheduler',
                            'finished_at': datetime.now().isoformat(),
                            'result_path': paths.get('result_path'),
                            'history_path': paths.get('history_path'),
                            'overlay_count': len((payload.get('analysis_result') or {}).get('overlay_annotations') or []),
                            'segments': (payload.get('segments') or {}).get('count'),
                            'horizon': payload.get('horizon'),
                        }
                    print(f'[ApplicationAnalysisScheduler] tick target={target_id} elapsed={elapsed}s overlays={self._last_run[target_id]["overlay_count"]}', flush=True)
                except Exception as exc:
                    print(f'[ApplicationAnalysisScheduler] tick target={target_id} failed: {exc}', flush=True)
                    with self._last_run_lock:
                        self._last_run[target_id] = {
                            'status': 'failed',
                            'error': str(exc),
                            'source': 'scheduler',
                            'finished_at': datetime.now().isoformat(),
                        }
                finally:
                    with self._inflight_lock:
                        self._inflight.pop(target_id, None)

    def _persist_status(self) -> None:
        try:
            payload = {
                'running': self.is_running(),
                'started_at': self._started_at.isoformat() if self._started_at else None,
                'tick_count': self._tick_count,
                'runs_count': self._runs_count,
                'last_tick_at': datetime.now().isoformat(),
                'last_run': dict(self._last_run),
                'targets_total': len(load_targets().get('items', [])),
            }
            save_scheduler_status(payload)
        except Exception as exc:
            print(f'[ApplicationAnalysisScheduler] persist status error: {exc}', flush=True)


scheduler = ApplicationAnalysisScheduler()


def is_application_analysis_scheduler_enabled() -> bool:
    import os

    flag = os.getenv('MINIMAX_APPLICATION_ANALYSIS_SCHEDULER_ENABLED')
    if flag is None:
        return True
    return flag.lower() in {'1', 'true', 'yes', 'on'}


def start_application_analysis_scheduler() -> None:
    touch_updated_marker()
    scheduler.start()


def stop_application_analysis_scheduler() -> None:
    scheduler.stop()


def get_application_analysis_scheduler_status() -> dict[str, Any]:
    return scheduler.status()


def list_application_analysis_targets() -> list[dict[str, Any]]:
    items = load_targets().get('items', [])
    out: list[dict[str, Any]] = []
    for item in items:
        result = read_result(item)
        out.append({
            **item,
            'last_result_path': (result or {}).get('_meta_result_path') or None,
            'last_updated_at': (result or {}).get('updated_at') if result else None,
        })
    return out


def list_application_analysis_results() -> list[dict[str, Any]]:
    return list_result_files()


def trigger_application_analysis(target_id: str | None, source: str = 'manual') -> dict[str, Any]:
    if target_id:
        return scheduler.trigger_target(target_id, source=source)
    return {'ok': True, 'items': scheduler.trigger_all(source=source)}
