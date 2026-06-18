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

import logging
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
from backend.services.scheduler.stock_universe_scheduler import (
    get_stock_universe_scheduler,
    get_stock_universe_scheduler_status,
    start_stock_universe_scheduler,
    stop_stock_universe_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_scheduler import (
    get_ths_industry_constituents_scheduler,
    get_ths_industry_constituents_scheduler_status,
    start_ths_industry_constituents_scheduler,
    stop_ths_industry_constituents_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_daily_scheduler import (
    get_ths_industry_constituents_daily_scheduler,
    get_ths_industry_constituents_daily_scheduler_status,
    start_ths_industry_constituents_daily_scheduler,
    stop_ths_industry_constituents_daily_scheduler,
)
from backend.services.stock.application_analysis_scheduler import (
    get_application_analysis_scheduler_status,
    scheduler as application_analysis_scheduler,
    start_application_analysis_scheduler,
    stop_application_analysis_scheduler,
)
from backend.services.scheduler.market_overview_scheduler import (
    get_market_overview_scheduler_status,
    run_market_overview_snapshot_now,
    start_market_overview_scheduler,
    stop_market_overview_scheduler,
)
from backend.services.scheduler.market_pulse_scheduler import (
    get_market_pulse_scheduler_status,
    start_market_pulse_scheduler,
    stop_market_pulse_scheduler,
    trigger_market_pulse_constituents_now,
    trigger_market_pulse_close_snapshot_now,
    trigger_market_pulse_snapshot_now,
)
from backend.services.scheduler.daily_eod_incremental_scheduler import (
    get_daily_eod_incremental_scheduler_status,
    run_daily_eod_incremental_now,
    start_daily_eod_incremental_scheduler,
    stop_daily_eod_incremental_scheduler,
)
from backend.services.scheduler.tdx_hsjday_download_scheduler import (
    get_tdx_hsjday_download_scheduler_status,
    run_tdx_hsjday_download_now,
    start_tdx_hsjday_download_scheduler,
    stop_tdx_hsjday_download_scheduler,
)
from backend.services.scheduler.market_overview_daily_scheduler import (
    get_market_overview_daily_scheduler_status,
    run_market_overview_daily_now,
    start_market_overview_daily_scheduler,
    stop_market_overview_daily_scheduler,
)
from backend.services.scheduler.ths_industry_fund_flow_daily_scheduler import (
    get_ths_industry_fund_flow_daily_scheduler_status,
    run_ths_industry_fund_flow_daily_now,
    start_ths_industry_fund_flow_daily_scheduler,
    stop_ths_industry_fund_flow_daily_scheduler,
)
from backend.services.stock.market_overview_eltdx_service import capture_overview
from backend.utils.json_io import read_json_file, write_json_file

scheduler_bp = Blueprint('scheduler_mgmt', __name__)

logger = logging.getLogger(__name__)

# 三个内置 job 的 id 集合，用于校验路径。
_KNOWN_JOB_IDS = {
    'turnover_refresh', 'auction_ai_analysis', 'application_analysis',
    'stock_universe_refresh', 'ths_industry_constituents_weekly', 'ths_industry_constituents_daily',
    # market_pulse (行业轮动 + 90 行业成分股): 由 market_pulse_scheduler 管理
    'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents',
    # market_overview (eastmoney fund flow): 由 market_overview_scheduler 管理
    'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
    # eltdx overview (全A成交额/涨跌家数): 由同一个 market_overview_scheduler 管理
    'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    # 每日 EOD 17:00 增量入 duckdb (daily_raw + limit_emotion_summary)
    'daily_eod_incremental',
    # 工作日 16:30 下载 TDX hsjday.zip 并覆盖 reference/tdx/day/hsjday
    'tdx_hsjday_download',
    # 工作日 17:10 把大盘成交额 / 主力净流入 / 90 行业 回填 duckdb (market_overview_daily + market_pulse_sector_daily)
    'market_overview_daily',
    # 工作日 17:15 把同花顺 90 行业资金流回填 duckdb (ths_industry_fund_flow_daily)
    'ths_industry_fund_flow_daily',
    # 测试用 job: 无对应 scheduler 模块, 用来演示"删除后重启不自动恢复"
    'test_scheduler_demo',
}

# application_analysis 的 enabled 写入 ``scheduler.json``（状态文件），其余两个走
# ``scheduler/<id>.json``。这里集中处理。
_application_analysis_status_lock = threading.Lock()


def _jobs_registry_path() -> Path:
    return BASE_DIR / 'scheduler' / 'jobs.json'


def _load_jobs_registry() -> dict[str, Any]:
    p = _jobs_registry_path()
    if not p.exists():
        return {'version': 1, 'jobs': []}
    data = read_json_file(p, {'version': 1, 'jobs': []})
    # 兼容旧版 / 某些 writer 落盘为顶层 list 的情况
    if isinstance(data, list):
        return {'version': 1, 'jobs': data}
    if not isinstance(data, dict):
        return {'version': 1, 'jobs': []}
    return data


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
    """application_analysis 没有全局 enabled（靠 per-target enabled），所以不暴露。

    market_pulse_* / market_overview_* / eltdx_overview_* 共用同一份 status 文件里的
    enabled 字段，整组共用同一个开关；UI 上"禁用"对应整组停掉。
    """
    return job_id in {
        'turnover_refresh', 'auction_ai_analysis', 'stock_universe_refresh',
        'ths_industry_constituents_weekly', 'ths_industry_constituents_daily',
        'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents',
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
        'daily_eod_incremental',
        'tdx_hsjday_download',
        'market_overview_daily',
        'ths_industry_fund_flow_daily',
        'test_scheduler_demo',
    }


def _get_live_status(job_id: str) -> dict[str, Any]:
    if job_id == 'turnover_refresh':
        return get_turnover_scheduler_status()
    if job_id == 'auction_ai_analysis':
        return get_auction_analysis_scheduler_status()
    if job_id == 'application_analysis':
        return get_application_analysis_scheduler_status()
    if job_id == 'stock_universe_refresh':
        return get_stock_universe_scheduler_status()
    if job_id == 'ths_industry_constituents_weekly':
        return get_ths_industry_constituents_scheduler_status()
    if job_id == 'ths_industry_constituents_daily':
        return get_ths_industry_constituents_daily_scheduler_status()
    # market_pulse: 共用 market_pulse_scheduler 的状态
    if job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        return get_market_pulse_scheduler_status()
    # market_overview / eltdx overview: 共用 market_overview_scheduler 的状态
    if job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        return get_market_overview_scheduler_status()
    if job_id == 'daily_eod_incremental':
        return get_daily_eod_incremental_scheduler_status()
    if job_id == 'tdx_hsjday_download':
        return get_tdx_hsjday_download_scheduler_status()
    if job_id == 'market_overview_daily':
        return get_market_overview_daily_scheduler_status()
    if job_id == 'ths_industry_fund_flow_daily':
        return get_ths_industry_fund_flow_daily_scheduler_status()
    return {}


def _start_scheduler(job_id: str) -> None:
    if job_id == 'turnover_refresh':
        start_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        start_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        start_application_analysis_scheduler()
    elif job_id == 'stock_universe_refresh':
        start_stock_universe_scheduler()
    elif job_id == 'ths_industry_constituents_weekly':
        start_ths_industry_constituents_scheduler()
    elif job_id == 'ths_industry_constituents_daily':
        start_ths_industry_constituents_daily_scheduler()
    elif job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        start_market_pulse_scheduler()
    elif job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        # market_overview scheduler 是一个整体, 启动/停止作用于所有 6 个 job
        # (start_market_overview_scheduler 是幂等的, 多次调用安全)
        start_market_overview_scheduler()
    elif job_id == 'daily_eod_incremental':
        start_daily_eod_incremental_scheduler()
    elif job_id == 'tdx_hsjday_download':
        start_tdx_hsjday_download_scheduler()
    elif job_id == 'market_overview_daily':
        start_market_overview_daily_scheduler()
    elif job_id == 'ths_industry_fund_flow_daily':
        start_ths_industry_fund_flow_daily_scheduler()


def _stop_scheduler(job_id: str) -> None:
    if job_id == 'turnover_refresh':
        stop_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        stop_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        stop_application_analysis_scheduler()
    elif job_id == 'stock_universe_refresh':
        stop_stock_universe_scheduler()
    elif job_id == 'ths_industry_constituents_weekly':
        stop_ths_industry_constituents_scheduler()
    elif job_id == 'ths_industry_constituents_daily':
        stop_ths_industry_constituents_daily_scheduler()
    elif job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        stop_market_pulse_scheduler()
    elif job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        # 整体停掉 market_overview_scheduler (会暂停 APScheduler)
        stop_market_overview_scheduler()
    elif job_id == 'daily_eod_incremental':
        stop_daily_eod_incremental_scheduler()
    elif job_id == 'tdx_hsjday_download':
        stop_tdx_hsjday_download_scheduler()
    elif job_id == 'market_overview_daily':
        stop_market_overview_daily_scheduler()
    elif job_id == 'ths_industry_fund_flow_daily':
        stop_ths_industry_fund_flow_daily_scheduler()


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
    if job_id == 'stock_universe_refresh':
        sched = get_stock_universe_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'application_analysis':
        targets = application_analysis_scheduler.trigger_all(source='settings_manual')
        if not targets:
            msg = '当前没有启用的标的，请在 application-analysis 页添加并启用至少一个标的'
            print(f'[scheduler] application_analysis trigger skipped: {msg}', flush=True)
            return {
                'ok': False,
                'items': [],
                'count': 0,
                'error': msg,
                'error_code': 'no_enabled_targets',
            }
        ok = all((r.get('ok') for r in targets))
        failed = [r for r in targets if not r.get('ok')]
        if failed:
            print(
                f'[scheduler] application_analysis trigger partial: '
                f'{len(failed)}/{len(targets)} failed, errors='
                f'{[r.get("error") for r in failed]}',
                flush=True,
            )
        return {
            'ok': ok,
            'items': targets,
            'count': len(targets),
            'failed_count': len(failed),
        }
    if job_id == 'ths_industry_constituents_weekly':
        sched = get_ths_industry_constituents_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'ths_industry_constituents_daily':
        sched = get_ths_industry_constituents_daily_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    # market_pulse_*: 三个 job 走同一 scheduler, trigger 时分别对应不同刷新动作
    if job_id == 'market_pulse_inside':
        return trigger_market_pulse_snapshot_now()
    if job_id == 'market_pulse_close':
        return trigger_market_pulse_close_snapshot_now()
    if job_id == 'market_pulse_constituents':
        return trigger_market_pulse_constituents_now()
    # market_overview_*  (fund-flow, eastmoney 数据源)
    if job_id in {'market_overview_inside', 'market_overview_close', 'market_overview_warmup'}:
        snap = run_market_overview_snapshot_now(force=True)
        if snap is None:
            return {'ok': False, 'error': 'fund-flow fetch failed (eastmoney unreachable?)'}
        return {
            'ok': True,
            'items': [snap],
            'count': 1,
            'failed_count': 0,
        }
    # eltdx_overview_*  (全A成交额/涨跌家数, eltdx 数据源)
    if job_id in {'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup'}:
        snap = capture_overview(force=True)
        if snap is None:
            return {'ok': False, 'error': 'eltdx fetch failed (TCP/TDX gateway unreachable?)'}
        return {
            'ok': True,
            'items': [snap],
            'count': 1,
            'failed_count': 0,
        }
    if job_id == 'daily_eod_incremental':
        return run_daily_eod_incremental_now()
    if job_id == 'tdx_hsjday_download':
        return run_tdx_hsjday_download_now()
    if job_id == 'market_overview_daily':
        return run_market_overview_daily_now()
    if job_id == 'ths_industry_fund_flow_daily':
        return run_ths_industry_fund_flow_daily_now()
    # test_scheduler_demo: 测试 entry, 没有对应 scheduler, trigger / start / stop 都返回错误
    if job_id == 'test_scheduler_demo':
        return {'ok': False, 'error': 'test_scheduler_demo 是测试 entry, 没有对应 scheduler 模块; 用来演示 jobs.json 注册表 CRUD'}
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

    enabled_bool = bool(enabled)

    # test_scheduler_demo 没有对应 config 文件, 写到 jobs.json 注册表里的 enabled 字段
    if job_id == 'test_scheduler_demo':
        entry['enabled'] = enabled_bool
        registry.setdefault('jobs', [])
        # 写回
        p = _jobs_registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(p, registry)
        return {'ok': True, 'job_id': job_id, 'enabled': enabled_bool, 'config': {'enabled': enabled_bool}}

    config_file = entry.get('config_file') or ''
    if not config_file:
        return {'ok': False, 'error': f'job {job_id} has no config_file'}

    config = _load_job_config(config_file) or {}
    config['enabled'] = enabled_bool
    config['job_name'] = config.get('job_name') or job_id
    _save_job_config(config_file, config)
    return {'ok': True, 'job_id': job_id, 'enabled': enabled_bool, 'config': config}


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
        # 兼容前端 notification 组件: 把 count/failed_count 提升到顶层.
        # application_analysis 的 result 自带 count/failed_count;
        # stock_universe / turnover / auction 的 result 是 status 形态, 这里兜底算 1.
        if "count" in result:
            top_count = result["count"]
            top_failed = result.get("failed_count", 0)
        else:
            top_count = 1
            top_failed = 0 if result.get("status") == "success" else 1
        return jsonify({
            "ok": result.get("ok", True),
            "job_id": job_id,
            "count": top_count,
            "failed_count": top_failed,
            "result": result,
        })
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


@scheduler_bp.route('/api/scheduler/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id: str):
    """从 jobs.json 注册表里删除一个 job (同时停掉运行中的调度器线程).

    前端 /settings/scheduler 页面 "删除" 按钮用.
    """
    # 1) 先尝试停掉运行中的调度器 (不抛错, 失败也不影响删除注册表)
    try:
        _stop_scheduler(job_id)
    except Exception as exc:
        traceback.print_exc()
        logger.warning("delete_job: stop scheduler for %s failed: %s", job_id, exc)

    # 2) 从 jobs.json 移除该 job
    p = _jobs_registry_path()
    data = _load_jobs_registry()
    before_count = len(data.get("jobs", []))
    data["jobs"] = [j for j in data.get("jobs", []) if j.get("id") != job_id]
    after_count = len(data["jobs"])

    if before_count == after_count:
        return jsonify({'ok': False, 'error': f'job {job_id} not found in registry'}), 404

    p.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(p, data)
    logger.info("delete_job: removed %s from jobs.json (count: %d -> %d)", job_id, before_count, after_count)
    return jsonify({'ok': True, 'job_id': job_id, 'removed': before_count - after_count})
