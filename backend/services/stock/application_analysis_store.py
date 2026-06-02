from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.settings import (
    APPLICATION_ANALYSIS_HISTORY_FOLDER,
    APPLICATION_ANALYSIS_RESULTS_FOLDER,
    APPLICATION_ANALYSIS_SCHEDULER_FILE,
    APPLICATION_ANALYSIS_TARGETS_FILE,
)
from backend.utils.json_io import read_json_file

DEFAULT_HORIZON = {'days': 120, 'segments': 4, 'monthly_keep': 12, 'weekly_keep': 26}

_lock_targets = threading.Lock()
_lock_results = threading.Lock()
_lock_scheduler = threading.Lock()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _normalize_item(raw: dict[str, Any], index: int) -> dict[str, Any]:
    target_type = str(raw.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(raw.get('symbol') or '').strip() or f'item-{index + 1}'
    name = str(raw.get('name') or symbol).strip() or symbol
    interval = raw.get('interval_minutes')
    try:
        interval_value = int(interval)
    except (TypeError, ValueError):
        interval_value = 60
    interval_value = max(5, interval_value)
    item_id = str(raw.get('id') or f'{target_type}-{symbol}').strip() or f'{target_type}-{symbol}'
    tags = raw.get('tags') if isinstance(raw.get('tags'), list) else []
    return {
        'id': item_id,
        'target_type': target_type,
        'symbol': symbol,
        'name': name,
        'adjust': str(raw.get('adjust') or 'qfq').strip() or 'qfq',
        'enabled': bool(raw.get('enabled', True)),
        'interval_minutes': interval_value,
        'tags': [str(t) for t in tags if str(t).strip()],
    }


def _normalize_targets(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    horizon = data.get('horizon') if isinstance(data.get('horizon'), dict) else {}
    horizon_out = {**DEFAULT_HORIZON, **horizon}
    try:
        days = int(horizon_out.get('days') or DEFAULT_HORIZON['days'])
    except (TypeError, ValueError):
        days = DEFAULT_HORIZON['days']
    try:
        segments = int(horizon_out.get('segments') or DEFAULT_HORIZON['segments'])
    except (TypeError, ValueError):
        segments = DEFAULT_HORIZON['segments']
    try:
        monthly_keep = int(horizon_out.get('monthly_keep') or DEFAULT_HORIZON['monthly_keep'])
    except (TypeError, ValueError):
        monthly_keep = DEFAULT_HORIZON['monthly_keep']
    try:
        weekly_keep = int(horizon_out.get('weekly_keep') or DEFAULT_HORIZON['weekly_keep'])
    except (TypeError, ValueError):
        weekly_keep = DEFAULT_HORIZON['weekly_keep']
    horizon_out = {
        'days': max(30, days),
        'segments': max(1, segments),
        'monthly_keep': max(1, monthly_keep),
        'weekly_keep': max(1, weekly_keep),
    }
    items_raw = data.get('items') if isinstance(data.get('items'), list) else []
    items = [_normalize_item(item, index) for index, item in enumerate(items_raw) if isinstance(item, dict)]
    return {
        'version': 1,
        'updated_at': data.get('updated_at') or None,
        'horizon': horizon_out,
        'items': items,
    }


def load_targets() -> dict[str, Any]:
    with _lock_targets:
        raw = read_json_file(APPLICATION_ANALYSIS_TARGETS_FILE, None)
        if raw is None:
            seed = {
                'version': 1,
                'updated_at': None,
                'horizon': dict(DEFAULT_HORIZON),
                'items': [],
            }
            _atomic_write_json(APPLICATION_ANALYSIS_TARGETS_FILE, seed)
            return seed
        normalized = _normalize_targets(raw)
        if normalized != raw:
            _atomic_write_json(APPLICATION_ANALYSIS_TARGETS_FILE, normalized)
        return normalized


def save_targets(payload: dict[str, Any]) -> dict[str, Any]:
    with _lock_targets:
        normalized = _normalize_targets(payload)
        normalized['updated_at'] = datetime.now().isoformat()
        _atomic_write_json(APPLICATION_ANALYSIS_TARGETS_FILE, normalized)
        return normalized


def result_filename(item: dict[str, Any]) -> str:
    target_type = str(item.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(item.get('symbol') or '').strip() or 'unknown'
    return f'{target_type}-{symbol}.json'


def result_path(item: dict[str, Any]) -> Path:
    return APPLICATION_ANALYSIS_RESULTS_FOLDER / result_filename(item)


def history_dir(item: dict[str, Any]) -> Path:
    target_type = str(item.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(item.get('symbol') or '').strip() or 'unknown'
    return APPLICATION_ANALYSIS_HISTORY_FOLDER / f'{target_type}-{symbol}'


def write_result(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    target_path = result_path(item)
    history_directory = history_dir(item)
    history_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    snapshot_path = history_directory / f'{timestamp}.json'
    serialized = {
        'target': {
            'id': item.get('id'),
            'target_type': item.get('target_type'),
            'symbol': item.get('symbol'),
            'name': item.get('name'),
            'adjust': item.get('adjust'),
            'tags': item.get('tags') or [],
        },
        'updated_at': datetime.now().isoformat(),
        'analysis_input': payload.get('analysis_input'),
        'analysis_result': payload.get('analysis_result'),
        'raw_result': payload.get('raw_result'),
        'raw_root_keys': payload.get('raw_root_keys'),
        'dump_paths': payload.get('dump_paths'),
        'segments': payload.get('segments'),
        'horizon': payload.get('horizon'),
        'elapsed_seconds': payload.get('elapsed_seconds'),
    }
    with _lock_results:
        _atomic_write_json(target_path, serialized)
        try:
            _atomic_write_json(snapshot_path, serialized)
        except Exception:
            pass
    return {'result_path': str(target_path), 'history_path': str(snapshot_path)}


def read_result(item: dict[str, Any]) -> dict[str, Any] | None:
    target_path = result_path(item)
    if not target_path.exists():
        return None
    return read_json_file(target_path, None)


def list_result_files() -> list[dict[str, Any]]:
    if not APPLICATION_ANALYSIS_RESULTS_FOLDER.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(APPLICATION_ANALYSIS_RESULTS_FOLDER.glob('*.json')):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({
            'filename': path.name,
            'path': str(path),
            'size_bytes': stat.st_size,
            'updated_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return out


def load_scheduler_status() -> dict[str, Any]:
    with _lock_scheduler:
        raw = read_json_file(APPLICATION_ANALYSIS_SCHEDULER_FILE, None)
    if not raw:
        return {
            'running': False,
            'started_at': None,
            'last_tick_at': None,
            'last_run': None,
            'runs': 0,
        }
    return raw


def save_scheduler_status(status: dict[str, Any]) -> None:
    with _lock_scheduler:
        _atomic_write_json(APPLICATION_ANALYSIS_SCHEDULER_FILE, status)


def list_history(item: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    directory = history_dir(item)
    if not directory.exists():
        return []
    files = sorted(directory.glob('*.json'), key=lambda p: p.name, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[: max(1, limit)]:
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({
            'filename': path.name,
            'path': str(path),
            'updated_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return out


def touch_updated_marker() -> None:
    if not APPLICATION_ANALYSIS_TARGETS_FILE.exists():
        return
    try:
        mtime = time.time()
        os.utime(APPLICATION_ANALYSIS_TARGETS_FILE, (mtime, mtime))
    except OSError:
        pass
