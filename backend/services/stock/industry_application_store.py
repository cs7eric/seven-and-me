"""行业 / 概念 应用面分析 的独立持久化。

与 :mod:`application_analysis_store` 完全解耦：

- targets:    ``reference/industry-application/targets.json``
- results:    ``reference/industry-application/results/``
- history:    ``reference/industry-application/history/<target-id>/<timestamp>.json``
- scheduler:  ``reference/industry-application/scheduler.json``

target_type 只支持 ``industry`` / ``concept``，对应 eltdx
``sh8803XX`` (申万行业) / ``sh8804XX`` (概念主题) 指数代码。

K 线数据来源是 eltdx ``client.bars.get(kind="index")``，
跟 :data:`~backend.services.stock.f10.index_codes.INDUSTRY_INDEX_CODES`
和 :data:`~backend.services.stock.f10.index_codes.CONCEPT_INDEX_CODES` 一一对应。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.settings import (
    INDUSTRY_APPLICATION_HISTORY_FOLDER,
    INDUSTRY_APPLICATION_RESULTS_FOLDER,
    INDUSTRY_APPLICATION_SCHEDULER_FILE,
    INDUSTRY_APPLICATION_TARGETS_FILE,
)
from backend.utils.json_io import read_json_file

DEFAULT_HORIZON = {'days': 120, 'segments': 4}

VALID_KINDS = {'industry', 'concept'}

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


# ---------------------------------------------------------------------------
# target 标准化
# ---------------------------------------------------------------------------


def _normalize_item(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """target_type 只接受 industry / concept，symbol 必须是 sh8803xx / sh8804xx。"""
    target_type = str(raw.get('target_type') or '').strip().lower()
    if target_type not in VALID_KINDS:
        # 默认按 symbol 前缀猜
        symbol = str(raw.get('symbol') or '').strip().lower()
        if symbol.startswith('sh8803') or symbol.startswith('sz8803'):
            target_type = 'industry'
        elif symbol.startswith('sh8804') or symbol.startswith('sz8804'):
            target_type = 'concept'
        else:
            target_type = 'industry'
    symbol = str(raw.get('symbol') or '').strip().lower()
    if not symbol:
        raise ValueError(f'item #{index + 1} 缺少 symbol')
    name = str(raw.get('name') or symbol).strip() or symbol
    interval = raw.get('interval_minutes')
    try:
        interval_value = int(interval)
    except (TypeError, ValueError):
        interval_value = 60
    interval_value = max(5, interval_value)
    item_id = (
        str(raw.get('id') or f'{target_type}-{symbol}').strip()
        or f'{target_type}-{symbol}'
    )
    tags = raw.get('tags') if isinstance(raw.get('tags'), list) else []
    return {
        'id': item_id,
        'target_type': target_type,
        'symbol': symbol,
        'name': name,
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
    horizon_out = {
        'days': max(30, days),
        'segments': max(1, segments),
    }
    items_raw = data.get('items') if isinstance(data.get('items'), list) else []
    items = []
    for index, item in enumerate(items_raw):
        if not isinstance(item, dict):
            continue
        try:
            items.append(_normalize_item(item, index))
        except ValueError:
            continue
    return {
        'version': 1,
        'updated_at': data.get('updated_at') or None,
        'horizon': horizon_out,
        'items': items,
    }


# ---------------------------------------------------------------------------
# target CRUD
# ---------------------------------------------------------------------------


def load_targets() -> dict[str, Any]:
    with _lock_targets:
        raw = read_json_file(INDUSTRY_APPLICATION_TARGETS_FILE, None)
        if raw is None:
            seed = {
                'version': 1,
                'updated_at': None,
                'horizon': dict(DEFAULT_HORIZON),
                'items': [],
            }
            _atomic_write_json(INDUSTRY_APPLICATION_TARGETS_FILE, seed)
            return seed
        normalized = _normalize_targets(raw)
        if normalized != raw:
            _atomic_write_json(INDUSTRY_APPLICATION_TARGETS_FILE, normalized)
        return normalized


def save_targets(payload: dict[str, Any]) -> dict[str, Any]:
    with _lock_targets:
        normalized = _normalize_targets(payload)
        normalized['updated_at'] = datetime.now().isoformat()
        _atomic_write_json(INDUSTRY_APPLICATION_TARGETS_FILE, normalized)
        return normalized


# ---------------------------------------------------------------------------
# result (K 线 + 简单技术指标) 持久化
# ---------------------------------------------------------------------------


def result_filename(item: dict[str, Any]) -> str:
    target_type = str(item.get('target_type') or 'industry').strip().lower()
    symbol = str(item.get('symbol') or '').strip().lower() or 'unknown'
    return f'{target_type}-{symbol}.json'


def result_path(item: dict[str, Any]) -> Path:
    return INDUSTRY_APPLICATION_RESULTS_FOLDER / result_filename(item)


def history_dir(item: dict[str, Any]) -> Path:
    target_type = str(item.get('target_type') or 'industry').strip().lower()
    symbol = str(item.get('symbol') or '').strip().lower() or 'unknown'
    return INDUSTRY_APPLICATION_HISTORY_FOLDER / f'{target_type}-{symbol}'


def write_result(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
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
            'tags': item.get('tags') or [],
        },
        'updated_at': datetime.now().isoformat(),
        'kline': payload.get('kline'),
        'indicators': payload.get('indicators'),
        'meta': payload.get('meta'),
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
    if not INDUSTRY_APPLICATION_RESULTS_FOLDER.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(INDUSTRY_APPLICATION_RESULTS_FOLDER.glob('*.json')):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append(
            {
                'filename': path.name,
                'path': str(path),
                'size_bytes': stat.st_size,
                'updated_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return out


# ---------------------------------------------------------------------------
# scheduler 状态
# ---------------------------------------------------------------------------


def load_scheduler_status() -> dict[str, Any]:
    with _lock_scheduler:
        raw = read_json_file(INDUSTRY_APPLICATION_SCHEDULER_FILE, None)
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
        _atomic_write_json(INDUSTRY_APPLICATION_SCHEDULER_FILE, status)
