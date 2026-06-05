"""Scheduler 管理 API。

给前端 ``/settings/scheduler`` 页用：列出 ``scheduler/jobs.json`` 中所有注册的 job，
展示每个 job 的实时调度器状态、配置 + 上次运行情况，并提供 enable / disable / trigger /
start / stop 五个动作。

约定：
- ``scheduler/jobs.json`` 是 job 注册表（id / name / config_file / service_module / ...）
- 每个 job 的 config_file 是相对仓库根的路径，例如：
    * ``scheduler/turnover_job.json`` —— turnover_refresh
    * ``scheduler/auction_analysis_job.json`` —— auction_ai_analysis
    * ``reference/application-analysis/scheduler.json`` —— application_analysis
- enable / disable 通过改写对应 config_file 的 ``enabled`` 字段实现
  （application_analysis 没有全局开关，disable 改其 scheduler 状态文件里的 ``enabled`` 字段）
- start / stop / trigger 走各 scheduler service 暴露的方法
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from backend.config.settings import BASE_DIR
from backend.services.scheduler.auction_analysis_scheduler import (
    get_auction_analysis_scheduler,
    get_auction_analysis_scheduler_status,
    start_auction_analysis_scheduler,
    stop_auction_analysis_scheduler,
)
from backend.services.scheduler.turnover_scheduler import (
    get_turnover_scheduler,
    get_turnover_scheduler_status,
    start_turnover_scheduler,
    stop_turnover_scheduler,
)
from backend.services.stock.application_analysis_scheduler import (
    get_application_analysis_scheduler_status,
    scheduler as application_analysis_scheduler,
    start_application_analysis_scheduler,
    stop_application_analysis_scheduler,
)
from backend.utils.json_io import read_json_file, write_json_file

scheduler_bp = Blueprint('scheduler_mgmt', __name__)

# 三个内置 job 的 id 集合，用于校验路径。
_KNOWN_JOB_IDS = {'turnover_refresh', 'auction_ai_analysis', 'application_analysis'}

# application_analysis 的 enabled 写入 ``scheduler.json``（状态文件），其余两个走
# ``scheduler/<id>.json``。这里集中处理。
_application_analysis_status_lock = threading.Lock()


def _jobs_registry_path() -> Path:
    return BASE_DIR / 'scheduler' / 'jobs.json'


def _load_jobs_registry() -> dict[str, Any]:
    p = _jobs_registry_path()
    if not p.exists():
        return {'version': 1, 'jobs': []}
    return read_json_file(p, {'version': 1, 'jobs': []})


def _resolve_config_path(config_file: str) -> Path:
    """``config_file`` 是相对仓库根的路径，转绝对路径。

    为了兼容旧的 jobs.json（``config_file`` 当时是相对 ``scheduler/`` 的），如果
    在 ``BASE_DIR`` 下找不到，则尝试 ``BASE_DIR/scheduler/<basename>``。
    """
    if not config_file:
        return (BASE_DIR / '__missing__').resolve()
    primary = (BASE_DIR / config_file).resolve()
    if primary.exists():
        return primary
    fallback = (BASE_DIR / 'scheduler' / Path(config_file).name).resolve()
    if fallback.exists():
        return fallback
    # 最后回退到 primary，让上层 read_json_file 抛错
    return primary


def _load_job_config(config_file: str) -> dict[str, Any]:
    p = _resolve_config_path(config_file)
    if not p.exists():
        return {}
    return read_json_file(p, {}) or {}


def _save_job_config(config_file: str, payload: dict[str, Any]) -> None:
    p = _resolve_config_path(config_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload['_saved_at'] = datetime.now().isoformat()
    write_json_file(p, payload)


def _supports_enable(job_id: str) -> bool:
    """application_analysis 没有全局 enabled（靠 per-target enabled），所以不暴露。"""
    return job_id in {'turnover_refresh', 'auction_ai_analysis'}


def _get_live_status(job_id: str) -> dict[str, Any]:
    if job_id == 'turnover_refresh':
        return get_turnover_scheduler_status()
    if job_id == 'auction_ai_analysis':
        return get_auction_analysis_scheduler_status()
    if job_id == 'application_analysis':
        return get_application_analysis_scheduler_status()
    return {}


def _start_scheduler(job_id: str) -> None:
    if job_id == 'turnover_refresh':
        start_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        start_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        start_application_analysis_scheduler()


def _stop_scheduler(job_id: str) -> None:
    if job_id == 'turnover_refresh':
        stop_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        stop_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        stop_application_analysis_scheduler()


def _trigger_scheduler(job_id: str) -> dict[str, Any]:
    """手动触发一次。返回 dict 给前端展示。"""
    if job_id == 'turnover_refresh':
        sched = get_turnover_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'auction_ai_analysis':
        sched = get_auction_analysis_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'application_analysis':
        results = application_analysis_scheduler.trigger_all(source='settings_manual')
        ok = all((r.get('ok') for r in results)) if results else False
        return {'ok': ok, 'items': results, 'count': len(results)}
    return {'ok': False, 'error': f'unknown job_id {job_id}'}


def _set_application_analysis_enabled(enabled: bool) -> None:
    """application_analysis 没有独立 config 文件，enabled 状态写到 ``scheduler.json``。"""
    with _application_analysis_status_lock:
        p = _resolve_config_path('reference/application-analysis/scheduler.json')
        if p.exists():
            payload = read_json_file(p, {}) or {}
        else:
            payload = {}
        payload['enabled'] = bool(enabled)
        payload['_saved_at'] = datetime.now().isoformat()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(p, payload)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@scheduler_bp.route('/api/scheduler/jobs', methods=['GET'])
def list_jobs():
    """列出所有 job + 各自 config + 实时 status。

    Response shape::

        {
            "ok": true,
            "items": [
                {
                    "id": "...",
                    "name": "...",
                    "description": "...",
                    "config_file": "...",
                    "service_module": "...",
                    "service_class": "...",
                    "registered_at": "...",
                    "supports_enable": true|false,
                    "enabled": true|false,            // 注册表里的开关
                    "config_enabled": true|false,     // 配置文件里的 enabled（控制调度器是否启动）
                    "config": { ... },                // 整个 config 文件内容
                    "live": { ... },                  // scheduler.status() 的实时返回值
                },
                ...
            ]
        }
    """
    try:
        registry = _load_jobs_registry()
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'load registry failed: {exc}'}), 500

    items: list[dict[str, Any]] = []
    for entry in registry.get('jobs', []):
        job_id = entry.get('id')
        if not job_id:
            continue
        config_file = entry.get('config_file') or ''
        try:
            config = _load_job_config(config_file) if config_file else {}
        except Exception as exc:
            config = {'_error': f'load config failed: {exc}'}
        try:
            live = _get_live_status(job_id)
        except Exception as exc:
            live = {'error': f'get live status failed: {exc}'}

        enabled_in_registry = bool(entry.get('enabled', True))
        config_enabled = config.get('enabled')
        # 对于 application_analysis 来说，没有独立 config；显示 live.running 即可
        if job_id == 'application_analysis':
            config_enabled = enabled_in_registry

        items.append({
            **entry,
            'supports_enable': _supports_enable(job_id),
            'enabled': enabled_in_registry,
            'config_enabled': bool(config_enabled) if config_enabled is not None else True,
            'config': config,
            'live': live,
        })

    return jsonify({'ok': True, 'items': items, 'count': len(items)})


@scheduler_bp.route('/api/scheduler/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404

    registry = _load_jobs_registry()
    entry = next(
        (item for item in registry.get('jobs', []) if item.get('id') == job_id),
        None,
    )
    if entry is None:
        return jsonify({'ok': False, 'error': f'job {job_id} not registered'}), 404

    config_file = entry.get('config_file') or ''
    config = _load_job_config(config_file) if config_file else {}
    live = _get_live_status(job_id)
    return jsonify({
        'ok': True,
        'item': {
            **entry,
            'supports_enable': _supports_enable(job_id),
            'enabled': bool(entry.get('enabled', True)),
            'config_enabled': bool(config.get('enabled', True)) if job_id != 'application_analysis' else True,
            'config': config,
            'live': live,
        },
    })


def _flip_enabled(job_id: str, enabled: bool) -> dict[str, Any]:
    if not _supports_enable(job_id):
        return {'ok': False, 'error': f'job {job_id} does not support enable/disable toggle'}

    registry = _load_jobs_registry()
    entry = next(
        (item for item in registry.get('jobs', []) if item.get('id') == job_id),
        None,
    )
    if entry is None:
        return {'ok': False, 'error': f'job {job_id} not registered'}

    config_file = entry.get('config_file') or ''
    if not config_file:
        return {'ok': False, 'error': f'job {job_id} has no config_file'}

    config = _load_job_config(config_file) or {}
    config['enabled'] = bool(enabled)
    config['job_name'] = config.get('job_name') or job_id
    _save_job_config(config_file, config)
    return {'ok': True, 'job_id': job_id, 'enabled': bool(enabled), 'config': config}


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/enable', methods=['POST'])
def enable_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    if not _supports_enable(job_id):
        return jsonify({'ok': False, 'error': f'job {job_id} does not support enable/disable toggle'}), 400
    try:
        return jsonify(_flip_enabled(job_id, True))
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/disable', methods=['POST'])
def disable_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    if not _supports_enable(job_id):
        return jsonify({'ok': False, 'error': f'job {job_id} does not support enable/disable toggle'}), 400
    try:
        return jsonify(_flip_enabled(job_id, False))
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/trigger', methods=['POST'])
def trigger_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    try:
        result = _trigger_scheduler(job_id)
        # 兼容 trigger_all 把 results 放在 items 字段的情况：把整体也回传
        return jsonify({'ok': result.get('ok', True), 'job_id': job_id, 'result': result})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/start', methods=['POST'])
def start_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    try:
        _start_scheduler(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/stop', methods=['POST'])
def stop_job(job_id: str):
    if job_id not in _KNOWN_JOB_IDS:
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    try:
        _stop_scheduler(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500
