import os
import sys
import uuid
import subprocess
import imageio_ffmpeg
import json
import time
import mimetypes
import requests
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

app = Flask(__name__, static_folder='static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).parent / 'uploads'
OUTPUT_FOLDER = Path(__file__).parent / 'outputs'
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2)

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": "https://www.bilibili.com/",
}
STOCK_EASTMONEY_HEADERS = {
    "User-Agent": DOWNLOAD_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": DOWNLOAD_HEADERS["Accept-Language"],
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
}
STOCK_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
STOCK_EASTMONEY_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
STOCK_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
STOCK_SINA_MINUTE_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
_tasks = {}

REFERENCE_FOLDER = Path(__file__).parent / 'reference'
REFERENCE_INDEX_FILE = REFERENCE_FOLDER / 'index.json'
MP4_REFERENCE_FOLDER = REFERENCE_FOLDER / 'parse'
MP4_REFERENCE_DATA_FOLDER = MP4_REFERENCE_FOLDER / 'data'
MP4_REFERENCE_INDEX_FOLDER = MP4_REFERENCE_FOLDER / 'index'
MP4_REFERENCE_TYPE_INDEX = MP4_REFERENCE_INDEX_FOLDER / 'index.json'
STOCK_REFERENCE_FOLDER = REFERENCE_FOLDER / 'stock'
STOCK_REFERENCE_INDEX_FOLDER = STOCK_REFERENCE_FOLDER / 'index'
STOCK_REFERENCE_DATA_FOLDER = STOCK_REFERENCE_FOLDER / 'data'
STOCK_REFERENCE_CACHE_FOLDER = STOCK_REFERENCE_FOLDER / 'cache'
STOCK_REFERENCE_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'index.json'
STOCK_REFERENCE_ANNOTATION_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'annotations.json'
STOCK_REFERENCE_WORKSPACE_INDEX_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'workspaces.json'
STOCK_CHART_CONFIG_FILE = STOCK_REFERENCE_INDEX_FOLDER / 'stock_chart_config.json'

REFERENCE_FOLDER.mkdir(exist_ok=True)
MP4_REFERENCE_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
MP4_REFERENCE_INDEX_FOLDER.mkdir(parents=True, exist_ok=True)
STOCK_REFERENCE_INDEX_FOLDER.mkdir(parents=True, exist_ok=True)
(STOCK_REFERENCE_DATA_FOLDER / 'annotations').mkdir(parents=True, exist_ok=True)
(STOCK_REFERENCE_DATA_FOLDER / 'snapshots').mkdir(parents=True, exist_ok=True)
(STOCK_REFERENCE_CACHE_FOLDER / 'klines').mkdir(parents=True, exist_ok=True)
(STOCK_REFERENCE_CACHE_FOLDER / 'auction').mkdir(parents=True, exist_ok=True)
(STOCK_REFERENCE_CACHE_FOLDER / 'indicators').mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("MINIMAX_API_KEY")
GROUP_ID = os.getenv("MINIMAX_GROUP_ID")

from transcribe import Transcriber
from polisher import TextPolisher

_transcriber = None
_polisher = None


def read_json_file(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except Exception:
        return default


def write_json_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def get_stock_chart_config() -> dict:
    default = {
        "version": 1,
        "kline": {
            "minute_provider": "mootdx",
            "daily_provider": "tencent",
            "weekly_provider": "tencent",
            "fallbacks": {
                "minute": ["mootdx", "sina", "eastmoney"],
                "daily": ["tencent", "eastmoney"],
                "weekly": ["tencent", "eastmoney"],
            },
            "mootdx": {
                "servers": [
                    ["110.41.147.114", 7709],
                    ["8.129.13.54", 7709],
                    ["124.70.176.52", 7709],
                ],
                "timeout": 10,
                "minute_adjust_mode": "none_only",
            },
        },
    }
    config_data = read_json_file(STOCK_CHART_CONFIG_FILE, default)
    if not STOCK_CHART_CONFIG_FILE.exists():
        write_json_file(STOCK_CHART_CONFIG_FILE, config_data)
    return config_data


def ensure_reference_index_files():
    if not REFERENCE_INDEX_FILE.exists() or REFERENCE_INDEX_FILE.stat().st_size == 0:
        write_json_file(REFERENCE_INDEX_FILE, {
            "version": 1,
            "updated_at": None,
            "types": {
                "mp4_parse": {
                    "title": "MP4 Parse History",
                    "index_file": str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "data_dir": str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "count": 0,
                },
                "stock_chart": {
                    "title": "Stock Chart Workspace",
                    "index_file": str(STOCK_REFERENCE_INDEX_FILE.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "data_dir": str(STOCK_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "count": 0,
                }
            }
        })

    if not MP4_REFERENCE_TYPE_INDEX.exists() or MP4_REFERENCE_TYPE_INDEX.stat().st_size == 0:
        write_json_file(MP4_REFERENCE_TYPE_INDEX, {
            "type": "mp4_parse",
            "version": 1,
            "updated_at": None,
            "items": []
        })

    if not STOCK_REFERENCE_INDEX_FILE.exists() or STOCK_REFERENCE_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_INDEX_FILE, {
            "type": "stock_chart",
            "version": 1,
            "updated_at": None,
            "items": []
        })

    if not STOCK_REFERENCE_ANNOTATION_INDEX_FILE.exists() or STOCK_REFERENCE_ANNOTATION_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, {
            "type": "stock_chart_annotations",
            "version": 1,
            "updated_at": None,
            "items": []
        })

    if not STOCK_REFERENCE_WORKSPACE_INDEX_FILE.exists() or STOCK_REFERENCE_WORKSPACE_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_WORKSPACE_INDEX_FILE, {
            "type": "stock_chart_workspaces",
            "version": 1,
            "updated_at": None,
            "items": []
        })


def build_task_snapshot(task_id: str, task: dict) -> dict:
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "transcript": task.get("transcript", ""),
        "polished": task.get("polished", ""),
        "summary": task.get("summary", ""),
        "metadata": task.get("metadata", {}),
        "file_name": task.get("file_name", ""),
        "error": task.get("error"),
        "download_progress": task.get("download_progress", {}),
        "intake_progress": task.get("intake_progress", {}),
        "qa_items": task.get("qa_items", []),
    }


def export_task_to_reference(task_id: str) -> dict:
    task = _tasks.get(task_id)
    if not task:
        raise ValueError("Task not found")
    if task.get("status") != "done":
        raise ValueError("Task is not completed yet")

    ensure_reference_index_files()

    snapshot = build_task_snapshot(task_id, task)
    metadata = snapshot.get("metadata") or {}
    title = str(metadata.get("title") or snapshot.get("file_name") or task_id).strip() or task_id
    created_at = datetime.now().isoformat()
    history_id = f"mp4-{task_id}"
    record_file = MP4_REFERENCE_DATA_FOLDER / f"{history_id}.json"

    record_payload = {
        "id": history_id,
        "type": "mp4_parse",
        "version": 1,
        "created_at": created_at,
        "updated_at": created_at,
        "title": title,
        "task": snapshot,
    }
    write_json_file(record_file, record_payload)

    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    items = [item for item in type_index.get("items", []) if item.get("id") != history_id]
    items.insert(0, {
        "id": history_id,
        "title": title,
        "created_at": created_at,
        "task_id": task_id,
        "status": snapshot.get("status"),
        "file_name": snapshot.get("file_name"),
        "data_file": str(record_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
    })
    type_index["items"] = items
    type_index["updated_at"] = created_at
    write_json_file(MP4_REFERENCE_TYPE_INDEX, type_index)

    root_index = read_json_file(REFERENCE_INDEX_FILE, {
        "version": 1,
        "updated_at": None,
        "types": {}
    })
    root_index.setdefault("types", {})["mp4_parse"] = {
        "title": "MP4 Parse History",
        "index_file": str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "data_dir": str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "count": len(items),
    }
    root_index["updated_at"] = created_at
    write_json_file(REFERENCE_INDEX_FILE, root_index)

    return {
        "id": history_id,
        "title": title,
        "created_at": created_at,
        "data_file": str(record_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
    }


def load_reference_history_list() -> list[dict]:
    ensure_reference_index_files()
    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    return type_index.get("items", [])


def load_reference_history_detail(history_id: str) -> dict | None:
    items = load_reference_history_list()
    item = next((entry for entry in items if entry.get("id") == history_id), None)
    if not item:
        return None
    data_file = item.get("data_file")
    if not data_file:
        return None
    record_file = REFERENCE_FOLDER / data_file
    return read_json_file(record_file, None)


def stock_workspace_id(target_type: str, symbol: str) -> str:
    safe_target = (target_type or 'stock').strip().lower()
    safe_symbol = (symbol or '').strip().lower()
    return f"{safe_target}-{safe_symbol}"


def stock_annotation_file(target_type: str, symbol: str, period: str) -> Path:
    return STOCK_REFERENCE_DATA_FOLDER / 'annotations' / f"{stock_workspace_id(target_type, symbol)}-{period}.json"


def stock_workspace_file(target_type: str, symbol: str) -> Path:
    return STOCK_REFERENCE_DATA_FOLDER / 'snapshots' / f"{stock_workspace_id(target_type, symbol)}.json"


def ensure_stock_workspace_entry(target_type: str, symbol: str, name: str | None = None) -> dict:
    ensure_reference_index_files()
    workspace_id = stock_workspace_id(target_type, symbol)
    workspace_file = stock_workspace_file(target_type, symbol)
    annotation_file = stock_annotation_file(target_type, symbol, '1d')
    index_data = read_json_file(STOCK_REFERENCE_INDEX_FILE, {
        "type": "stock_chart",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    items = index_data.get('items', [])
    existing = next((item for item in items if item.get('id') == workspace_id), None)
    now = datetime.now().isoformat()
    payload = {
        "id": workspace_id,
        "target_type": target_type,
        "symbol": symbol,
        "name": name or symbol,
        "workspace_file": str(workspace_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "annotation_file": str(annotation_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "updated_at": now,
    }
    if existing:
        existing.update(payload)
    else:
        items.insert(0, payload)
    index_data['items'] = items
    index_data['updated_at'] = now
    write_json_file(STOCK_REFERENCE_INDEX_FILE, index_data)

    root_index = read_json_file(REFERENCE_INDEX_FILE, {"version": 1, "updated_at": None, "types": {}})
    root_index.setdefault('types', {})['stock_chart'] = {
        "title": "Stock Chart Workspace",
        "index_file": str(STOCK_REFERENCE_INDEX_FILE.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "data_dir": str(STOCK_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "count": len(items),
    }
    root_index['updated_at'] = now
    write_json_file(REFERENCE_INDEX_FILE, root_index)
    return payload


def sample_stock_klines(symbol: str, period: str) -> list[dict]:
    base = 10.0 if symbol != '000300' else 3500.0
    today = datetime.now()
    period_minutes_map = {
        '1m': 1,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '60m': 60,
        '120m': 120,
    }
    minute_span = period_minutes_map.get(period)
    bars = []
    if minute_span is not None:
        start = today.replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(minutes=minute_span * 119)
        for index in range(120):
            trade_time = start + timedelta(minutes=index * minute_span)
            drift = index * (0.03 if symbol != '000300' else 1.1)
            open_price = round(base + drift + ((index % 5) - 2) * 0.08, 2)
            close_price = round(open_price + ((index % 7) - 3) * 0.05, 2)
            high_price = round(max(open_price, close_price) + 0.09, 2)
            low_price = round(min(open_price, close_price) - 0.07, 2)
            volume = float(50000 + index * 1200)
            turnover = float(volume * max(close_price, 1))
            bars.append({
                "timestamp": int(trade_time.timestamp() * 1000),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "turnover": turnover,
                "volume_ratio": round(1 + (index % 10) * 0.08, 2),
            })
        return bars

    interval = 7 if period == '1w' else 1
    today_date = today.date()
    for index in range(120):
        trade_date = today_date - timedelta(days=(119 - index) * interval)
        drift = index * (0.08 if symbol != '000300' else 3.2)
        open_price = round(base + drift + ((index % 5) - 2) * 0.12, 2)
        close_price = round(open_price + ((index % 7) - 3) * 0.09, 2)
        high_price = round(max(open_price, close_price) + 0.18, 2)
        low_price = round(min(open_price, close_price) - 0.16, 2)
        volume = float(800000 + index * 6000)
        turnover = float(volume * max(close_price, 1))
        bars.append({
            "timestamp": int(datetime.combine(trade_date, datetime.min.time()).timestamp() * 1000),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "turnover": turnover,
            "volume_ratio": round(1 + (index % 10) * 0.14, 2),
        })
    return bars


def stock_kline_cache_file(target_type: str, symbol: str, period: str, adjust: str) -> Path:
    return STOCK_REFERENCE_CACHE_FOLDER / 'klines' / f"{stock_workspace_id(target_type, symbol)}-{period}-{adjust}.json"


def stock_period_to_eastmoney_klt(period: str) -> str:
    period_map = {
        '1m': '1',
        '5m': '5',
        '15m': '15',
        '30m': '30',
        '60m': '60',
        '120m': '120',
        '1d': '101',
        '1w': '102',
    }
    return period_map.get(period, '101')


def stock_adjust_to_eastmoney_fqt(adjust: str) -> str:
    if adjust == 'hfq':
        return '2'
    if adjust == 'none':
        return '0'
    return '1'


def eastmoney_secid_candidates(target_type: str, symbol: str) -> list[str]:
    value = (symbol or '').strip().lower()
    if target_type == 'sector':
        return []
    if target_type == 'index':
        if value.startswith(('000', '880')):
            return [f'1.{symbol}', f'0.{symbol}']
        if value.startswith('399'):
            return [f'0.{symbol}', f'1.{symbol}']
        return [f'1.{symbol}', f'0.{symbol}']
    if symbol.startswith(('5', '6', '9')):
        return [f'1.{symbol}', f'0.{symbol}']
    return [f'0.{symbol}', f'1.{symbol}']


def parse_stock_trade_timestamp(value: str) -> datetime:
    normalized = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f'Unsupported trade timestamp: {value}')


def parse_eastmoney_kline_rows(rows: list[str]) -> list[dict]:
    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    for row in rows:
        parts = row.split(',')
        if len(parts) < 7:
            continue
        try:
            trade_time = parse_stock_trade_timestamp(parts[0])
            volume = float(parts[5] or 0)
            turnover = float(parts[6] or 0)
            turnover_rate = float(parts[10] or 0) if len(parts) > 10 and parts[10] else 0
            volumes_window.append(volume)
            recent_window = volumes_window[-5:]
            base_avg = sum(recent_window[:-1]) / max(len(recent_window) - 1, 1) if len(recent_window) > 1 else 0
            if base_avg > 0:
                volume_ratio = round(volume / base_avg, 2)
            elif previous_volume and previous_volume > 0:
                volume_ratio = round(volume / previous_volume, 2)
            else:
                volume_ratio = 1.0
            previous_volume = volume
            items.append({
                "timestamp": int(trade_time.timestamp() * 1000),
                "open": float(parts[1] or 0),
                "close": float(parts[2] or 0),
                "high": float(parts[3] or 0),
                "low": float(parts[4] or 0),
                "volume": volume,
                "turnover": turnover,
                "volume_ratio": volume_ratio,
                "turnover_rate": turnover_rate,
            })
        except ValueError:
            continue
    return items


def stock_symbol_to_tencent_code(target_type: str, symbol: str) -> str:
    if target_type == 'index':
        if symbol.startswith('399'):
            return f'sz{symbol}'
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def stock_symbol_to_sina_code(target_type: str, symbol: str) -> str:
    if target_type == 'index':
        if symbol.startswith('399'):
            return f'sz{symbol}'
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def stock_period_to_tencent_unit(period: str) -> str:
    period_map = {
        '1m': 'm1',
        '5m': 'm5',
        '15m': 'm15',
        '30m': 'm30',
        '60m': 'm60',
        '120m': 'm120',
        '1d': 'day',
        '1w': 'week',
    }
    return period_map.get(period, 'day')


def stock_adjust_to_tencent_prefix(adjust: str) -> str:
    if adjust == 'qfq':
        return 'qfq'
    if adjust == 'hfq':
        return 'hfq'
    return ''


def parse_tencent_kline_rows(rows: list[list[str]], target_type: str) -> list[dict]:
    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    is_index = target_type == 'index'
    for row in rows:
        if len(row) < 6:
            continue
        try:
            trade_time = parse_stock_trade_timestamp(str(row[0]))
            open_price = float(row[1] or 0)
            close_price = float(row[2] or 0)
            high_price = float(row[3] or 0)
            low_price = float(row[4] or 0)
            volume = float(row[5] or 0)
            turnover = float(row[36] or 0) if len(row) > 36 and row[36] else 0
            turnover_rate = float(row[37] or 0) if len(row) > 37 and row[37] else 0
            if is_index and turnover <= 0 and len(row) > 37 and row[37]:
                turnover = float(row[37] or 0)
            volumes_window.append(volume)
            recent_window = volumes_window[-5:]
            base_avg = sum(recent_window[:-1]) / max(len(recent_window) - 1, 1) if len(recent_window) > 1 else 0
            if base_avg > 0:
                volume_ratio = round(volume / base_avg, 2)
            elif previous_volume and previous_volume > 0:
                volume_ratio = round(volume / previous_volume, 2)
            else:
                volume_ratio = 1.0
            previous_volume = volume
            items.append({
                "timestamp": int(trade_time.timestamp() * 1000),
                "open": open_price,
                "close": close_price,
                "high": high_price,
                "low": low_price,
                "volume": volume,
                "turnover": turnover,
                "volume_ratio": volume_ratio,
                "turnover_rate": turnover_rate,
            })
        except ValueError:
            continue
    return items


def fetch_stock_klines_from_tencent(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    code = stock_symbol_to_tencent_code(target_type, symbol)
    unit = stock_period_to_tencent_unit(period)
    adjust_prefix = stock_adjust_to_tencent_prefix(adjust)
    params = {'param': f'{code},{unit},,,500,{adjust_prefix}'}
    response = requests.get(
        STOCK_TENCENT_KLINE_URL,
        params=params,
        headers={"User-Agent": DOWNLOAD_HEADERS["User-Agent"]},
        timeout=(5, 12),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') or {}
    target_data = data.get(code) or {}
    candidates = []
    if adjust_prefix:
        candidates.append(f'{adjust_prefix}{unit}')
    candidates.append(unit)
    rows = []
    for key in candidates:
        value = target_data.get(key)
        if isinstance(value, list) and value:
            rows = value
            break
    items = parse_tencent_kline_rows(rows, target_type)
    if items:
        return items
    raise ValueError('腾讯K线接口未返回有效数据')


def fetch_stock_klines_from_sina(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    if period not in {'5m', '15m', '30m', '60m'}:
        raise ValueError('新浪分钟K线仅支持 5/15/30/60 分钟')
    code = stock_symbol_to_sina_code(target_type, symbol)
    scale = int(period.replace('m', ''))
    response = requests.get(
        STOCK_SINA_MINUTE_KLINE_URL,
        params={
            'symbol': code,
            'scale': scale,
            'ma': 'no',
            'datalen': 500,
        },
        headers={"User-Agent": DOWNLOAD_HEADERS["User-Agent"], "Referer": "https://finance.sina.com.cn/"},
        timeout=(5, 12),
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise ValueError('新浪分钟K线接口未返回有效数据')

    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            trade_time = parse_stock_trade_timestamp(str(row.get('day') or ''))
            open_price = float(row.get('open') or 0)
            high_price = float(row.get('high') or 0)
            low_price = float(row.get('low') or 0)
            close_price = float(row.get('close') or 0)
            volume = float(row.get('volume') or 0)
            volumes_window.append(volume)
            recent_window = volumes_window[-5:]
            base_avg = sum(recent_window[:-1]) / max(len(recent_window) - 1, 1) if len(recent_window) > 1 else 0
            if base_avg > 0:
                volume_ratio = round(volume / base_avg, 2)
            elif previous_volume and previous_volume > 0:
                volume_ratio = round(volume / previous_volume, 2)
            else:
                volume_ratio = 1.0
            previous_volume = volume
            items.append({
                'timestamp': int(trade_time.timestamp() * 1000),
                'open': open_price,
                'close': close_price,
                'high': high_price,
                'low': low_price,
                'volume': volume,
                'turnover': float(row.get('amount') or 0),
                'volume_ratio': volume_ratio,
            })
        except ValueError:
            continue
    if items:
        return items
    raise ValueError('新浪分钟K线解析失败')


def fetch_stock_klines_from_mootdx(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    if target_type == 'sector':
        raise ValueError('mootdx 不支持板块分钟K线')
    config_data = get_stock_chart_config().get('kline', {})
    mootdx_config = config_data.get('mootdx', {}) if isinstance(config_data, dict) else {}
    minute_adjust_mode = str(mootdx_config.get('minute_adjust_mode', 'none_only'))
    if is_minute_stock_period(period) and minute_adjust_mode == 'none_only' and adjust != 'none':
        raise ValueError('当前 mootdx 分钟K线仅支持不复权')

    from mootdx.quotes import StdQuotes

    frequency_map = {
        '1m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '60m': '1h',
        '1d': 'day',
        '1w': 'week',
    }
    frequency = frequency_map.get(period)
    if not frequency:
        raise ValueError(f'mootdx 暂不支持周期: {period}')

    servers = mootdx_config.get('servers') or []
    timeout = int(mootdx_config.get('timeout', 10) or 10)
    last_error = None
    for server in servers:
        try:
            client = StdQuotes(server=tuple(server), timeout=timeout, raise_exception=True)
            fetch_kwargs = {'symbol': symbol, 'frequency': frequency, 'offset': 500}
            if adjust in {'qfq', 'hfq'} and not is_minute_stock_period(period):
                fetch_kwargs['adjust'] = adjust
            data = client.index(symbol=symbol, frequency=frequency, offset=500) if target_type == 'index' else client.bars(**fetch_kwargs)
            if data is None or len(data) == 0:
                continue
            items: list[dict] = []
            previous_volume = None
            volumes_window: list[float] = []
            for _, row in data.iterrows():
                volume = float(row.get('volume') or row.get('vol') or 0)
                turnover = float(row.get('amount') or 0)
                volumes_window.append(volume)
                recent_window = volumes_window[-5:]
                base_avg = sum(recent_window[:-1]) / max(len(recent_window) - 1, 1) if len(recent_window) > 1 else 0
                if base_avg > 0:
                    volume_ratio = round(volume / base_avg, 2)
                elif previous_volume and previous_volume > 0:
                    volume_ratio = round(volume / previous_volume, 2)
                else:
                    volume_ratio = 1.0
                previous_volume = volume
                trade_time = parse_stock_trade_timestamp(str(row.get('datetime') or ''))
                items.append({
                    'timestamp': int(trade_time.timestamp() * 1000),
                    'open': float(row.get('open') or 0),
                    'close': float(row.get('close') or 0),
                    'high': float(row.get('high') or 0),
                    'low': float(row.get('low') or 0),
                    'volume': volume,
                    'turnover': turnover,
                    'volume_ratio': volume_ratio,
                })
            if items:
                return items
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise ValueError(f'mootdx K线请求失败: {last_error}')
    raise ValueError('mootdx K线接口未返回有效数据')


def fetch_stock_klines_from_eastmoney(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    candidates = eastmoney_secid_candidates(target_type, symbol)
    if not candidates:
        return []

    params = {
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        'klt': stock_period_to_eastmoney_klt(period),
        'fqt': stock_adjust_to_eastmoney_fqt(adjust),
        'beg': '20180101',
        'end': '20500101',
        'lmt': '500',
    }

    session = requests.Session()
    session.trust_env = False

    last_error = None
    for secid in candidates:
        try:
            response = session.get(
                STOCK_EASTMONEY_KLINE_URL,
                params={**params, 'secid': secid},
                headers=STOCK_EASTMONEY_HEADERS,
                timeout=(5, 12),
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data') or {}
            rows = data.get('klines') or []
            items = parse_eastmoney_kline_rows(rows)
            if items:
                return items
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            continue

    if last_error:
        raise ValueError(f'东方财富K线请求失败: {last_error}')
    raise ValueError('东方财富K线接口未返回有效数据')


def read_cached_stock_klines(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    cache_data = read_json_file(stock_kline_cache_file(target_type, symbol, period, adjust), {})
    items = cache_data.get('items') if isinstance(cache_data, dict) else None
    return items if isinstance(items, list) else []


def is_minute_stock_period(period: str) -> bool:
    return period in {'1m', '5m', '15m', '30m', '60m', '120m'}


def get_stock_kline_provider_plan(period: str) -> list[str]:
    kline_config = get_stock_chart_config().get('kline', {})
    if period == '1w':
        primary = str(kline_config.get('weekly_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('weekly', [])
    elif is_minute_stock_period(period):
        primary = str(kline_config.get('minute_provider', 'mootdx'))
        fallbacks = kline_config.get('fallbacks', {}).get('minute', [])
    else:
        primary = str(kline_config.get('daily_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('daily', [])
    plan: list[str] = []
    for item in [primary, *(fallbacks if isinstance(fallbacks, list) else [])]:
        key = str(item).strip()
        if key and key not in plan:
            plan.append(key)
    return plan


def resolve_stock_klines(target_type: str, symbol: str, period: str, adjust: str) -> tuple[list[dict], str]:
    providers = {
        'mootdx': fetch_stock_klines_from_mootdx,
        'sina': fetch_stock_klines_from_sina,
        'tencent': fetch_stock_klines_from_tencent,
        'eastmoney': fetch_stock_klines_from_eastmoney,
    }
    for provider_name in get_stock_kline_provider_plan(period):
        provider = providers.get(provider_name)
        if not provider:
            continue
        try:
            items = provider(target_type, symbol, period, adjust)
            if items:
                return items, provider_name
        except Exception:
            continue

    cached_items = read_cached_stock_klines(target_type, symbol, period, adjust)
    if cached_items:
        return cached_items, 'cache'

    if is_minute_stock_period(period):
        raise ValueError('分钟K线真实数据暂不可用')

    return sample_stock_klines(symbol, period), 'sample'


def load_stock_annotations(target_type: str, symbol: str, period: str) -> list[dict]:
    data = read_json_file(stock_annotation_file(target_type, symbol, period), {"items": []})
    return data.get('items', [])


def reorder_reference_history_items(ordered_ids: list[str]) -> list[dict]:
    ensure_reference_index_files()
    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    items = type_index.get("items", [])
    item_map = {item.get("id"): item for item in items}
    reordered = [item_map[item_id] for item_id in ordered_ids if item_id in item_map]
    remaining = [item for item in items if item.get("id") not in ordered_ids]
    final_items = reordered + remaining
    type_index["items"] = final_items
    type_index["updated_at"] = datetime.now().isoformat()
    write_json_file(MP4_REFERENCE_TYPE_INDEX, type_index)
    return final_items


def sanitize_filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isprintable() and ch not in ('<', '>', ':', '"', '/', '\\', '|', '?', '*')).strip()
    safe = safe.replace(" ", "-")
    return safe[:80] or "untitled"


def build_export_filename(task: dict, task_id: str) -> str:
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or "").strip()
    original_name = Path(str(task.get("file_name") or "")).stem

    base_name = sanitize_filename(title)
    if not base_name or base_name == "untitled":
        base_name = sanitize_filename(original_name)

    if not base_name or base_name == "untitled":
        base_name = "untitled"

    return f"{base_name}.md"


def build_markdown_document(task: dict) -> str:
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or "Untitled Note").strip()
    categories = metadata.get("categories") or ["Uncategorized"]
    tags = metadata.get("tags") or ["待整理"]
    polished = (task.get("polished") or "").strip()
    summary = (task.get("summary") or "").strip()
    date_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    frontmatter = "\n".join([
        "---",
        f"title: {title}",
        "",
        f"categories: {','.join(categories)}",
        "",
        f"tags: {','.join(tags)}",
        "",
        f"date: {date_str}",
        "---",
    ])

    sections = [frontmatter, polished, summary]
    return "\n\n".join(section for section in sections if section)


def guess_extension_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'}:
        return suffix
    return '.mp4'


def build_download_filename(source_url: str, title: str | None, content_type: str | None) -> str:
    ext = guess_extension_from_url(source_url)
    guessed_ext = mimetypes.guess_extension((content_type or '').split(';')[0].strip()) if content_type else None
    if guessed_ext in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'}:
        ext = guessed_ext

    base = sanitize_filename(title or Path(urlparse(source_url).path).stem or 'downloaded-video')
    return f"{base}{ext}"


def create_task_record(task_id: str, file_name: str, source_url: str | None = None) -> dict:
    now = time.time()
    task = {
        "status": "transcribing",
        "transcript": "",
        "polished": "",
        "summary": "",
        "metadata": {},
        "file_name": file_name,
        "polish_progress": 0,
        "summary_progress": 0,
        "error": None,
        "created_at": now,
        "download_progress": {
            "phase": "pending",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
            "speed_bytes_per_sec": 0,
        },
        "intake_progress": {
            "phase": "pending",
            "progress": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
        },
    }
    if source_url:
        task["source_url"] = source_url
    _tasks[task_id] = task
    return task


def start_transcription_task(task_id: str, file_path: Path, display_name: str):
    wav_path = UPLOAD_FOLDER / f"{task_id}_audio.wav"
    filename_lower = display_name.lower()
    is_audio = any(filename_lower.endswith(ext) for ext in ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'))

    try:
        source_size = file_path.stat().st_size
    except OSError:
        source_size = 0

    task = _tasks.get(task_id)
    if task:
        task["intake_progress"] = {
            "phase": "preparing",
            "progress": 8,
            "processed_bytes": 0,
            "total_bytes": source_size,
            "eta_seconds": None,
        }

    if is_audio:
        audio_path = str(file_path)
        if task:
            task["intake_progress"] = {
                "phase": "ready",
                "progress": 100,
                "processed_bytes": source_size,
                "total_bytes": source_size,
                "eta_seconds": 0,
            }
    else:
        audio_path = str(wav_path)
        if task:
            task["intake_progress"] = {
                "phase": "preparing",
                "progress": 22,
                "processed_bytes": 0,
                "total_bytes": source_size,
                "eta_seconds": None,
            }
        ffmpeg_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y", "-i", str(file_path),
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(wav_path)
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError("ffmpeg 转换失败")
        if task:
            try:
                prepared_size = wav_path.stat().st_size
            except OSError:
                prepared_size = source_size
            task["intake_progress"] = {
                "phase": "ready",
                "progress": 100,
                "processed_bytes": prepared_size,
                "total_bytes": prepared_size,
                "eta_seconds": 0,
            }

    def on_chunk(chunk_idx, text, is_final):
        _tasks[task_id]["transcript"] = text

    def run():
        try:
            print(f"[run] 开始转写 task_id={task_id}, audio={audio_path}")
            transcriber = get_transcriber()
            transcriber.transcribe_streaming(audio_path, chunk_duration=30, callback=on_chunk)
            print(f"[run] 转写完成")

            text = _tasks[task_id]["transcript"]
            print(f"[run] 转写结果长度={len(text)}")
            if not text:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "转写结果为空"
                return

            _tasks[task_id]["status"] = "polishing"
            polisher = get_polisher()

            def on_polish_chunk(current_text):
                _tasks[task_id]["polished"] = current_text

            polished = polisher.polish(text, on_chunk=on_polish_chunk)
            _tasks[task_id]["polished"] = polished
            _tasks[task_id]["polish_progress"] = 100

            _tasks[task_id]["status"] = "summarizing"

            def on_summary_chunk(current_text):
                _tasks[task_id]["summary"] = current_text

            summary = polisher.summarize(polished, on_chunk=on_summary_chunk)
            _tasks[task_id]["summary"] = summary
            _tasks[task_id]["summary_progress"] = 100
            _tasks[task_id]["metadata"] = polisher.generate_post_metadata(polished, summary)
            _tasks[task_id]["status"] = "done"

        except Exception as e:
            import traceback
            traceback.print_exc()
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)

    _executor.submit(run)


def get_transcriber():
    global _transcriber
    if _transcriber is None:
        print("[App] 初始化 Whisper 模型")
        sys.stdout.flush()
        _transcriber = Transcriber()
    return _transcriber


def get_polisher():
    global _polisher
    if _polisher is None:
        print("[App] 初始化 MiniMax AI")
        sys.stdout.flush()
        _polisher = TextPolisher()
    return _polisher

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({
        "api_configured": bool(API_KEY and GROUP_ID),
        "gpu_available": False,
        "model_loaded": _transcriber is not None,
        "status": "running"
    })

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "文件名为空"}), 400

    task_id = str(uuid.uuid4())
    file_path = UPLOAD_FOLDER / f"{task_id}_{secure_filename(file.filename)}"

    try:
        file.save(str(file_path))
    except Exception as e:
        return jsonify({"error": f"文件保存失败: {e}"}), 500

    create_task_record(task_id, file.filename)

    try:
        start_transcription_task(task_id, file_path, file.filename)
    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = str(e)
        return jsonify({"error": f"转换音频失败: {e}"}), 500

    return jsonify({"task_id": task_id})

@app.route('/api/parse-video', methods=['POST'])
def parse_video_from_downloader():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    source_url = str(data.get('download_url') or '').strip()
    title = str(data.get('title') or '').strip()
    source_page_url = str(data.get('source_url') or '').strip()
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}

    if not source_url:
        return jsonify({"error": "download_url is required"}), 400

    task_id = str(uuid.uuid4())

    try:
        session = requests.Session()
        head_response = session.head(source_url, allow_redirects=True, timeout=(5, 15), headers=DOWNLOAD_HEADERS)
        file_name = build_download_filename(
            source_url,
            title,
            head_response.headers.get('Content-Type') if head_response.ok else None,
        )
        create_task_record(task_id, file_name, source_page_url or source_url)
        _tasks[task_id]["metadata"] = {
            **metadata,
            "title": title or metadata.get("title") or Path(file_name).stem,
            "source_url": source_page_url or source_url,
            "download_url": source_url,
        }
        _tasks[task_id]["status"] = "downloading"
        _tasks[task_id]["download_progress"] = {
            "phase": "queued",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": int(head_response.headers.get('Content-Length') or 0),
            "eta_seconds": None,
            "speed_bytes_per_sec": 0,
        }
        _tasks[task_id]["intake_progress"] = {
            "phase": "pending",
            "progress": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
        }

        def run_download_and_parse():
            try:
                request_headers = {
                    **DOWNLOAD_HEADERS,
                    "Referer": source_page_url or DOWNLOAD_HEADERS["Referer"],
                }
                with session.get(source_url, stream=True, timeout=(10, 300), headers=request_headers) as response:
                    response.raise_for_status()
                    resolved_file_name = build_download_filename(source_url, title, response.headers.get('Content-Type'))
                    file_path = UPLOAD_FOLDER / f"{task_id}_{secure_filename(resolved_file_name)}"
                    _tasks[task_id]["file_name"] = resolved_file_name
                    _tasks[task_id]["metadata"]["title"] = title or metadata.get("title") or Path(resolved_file_name).stem

                    total_size = int(response.headers.get('Content-Length') or 0)
                    downloaded = 0
                    started_at = time.time()
                    _tasks[task_id]["download_progress"] = {
                        "phase": "running",
                        "progress": 1,
                        "downloaded_bytes": 0,
                        "total_bytes": total_size,
                        "eta_seconds": None,
                        "speed_bytes_per_sec": 0,
                    }
                    with open(file_path, 'wb', buffering=8 * 1024 * 1024) as target:
                        for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                            if not chunk:
                                continue
                            target.write(chunk)
                            downloaded += len(chunk)
                            elapsed = max(time.time() - started_at, 0.001)
                            speed = downloaded / elapsed
                            eta_seconds = int((total_size - downloaded) / speed) if total_size and speed > 0 else None
                            progress = int(downloaded * 100 / total_size) if total_size else min(95, max(5, downloaded // (4 * 1024 * 1024)))
                            _tasks[task_id]["download_progress"] = {
                                "phase": "running",
                                "progress": min(progress, 99 if total_size else progress),
                                "downloaded_bytes": downloaded,
                                "total_bytes": total_size,
                                "eta_seconds": eta_seconds,
                                "speed_bytes_per_sec": int(speed),
                            }

                    if total_size and downloaded != total_size:
                        raise RuntimeError("下载文件不完整")

                _tasks[task_id]["download_progress"] = {
                    "phase": "done",
                    "progress": 100,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total_size,
                    "eta_seconds": 0,
                    "speed_bytes_per_sec": _tasks[task_id]["download_progress"].get("speed_bytes_per_sec", 0),
                }
                _tasks[task_id]["status"] = "transcribing"
                start_transcription_task(task_id, file_path, resolved_file_name)
            except requests.exceptions.RequestException as e:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"下载失败: {e}"
            except Exception as e:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"工作流启动失败: {e}"
            finally:
                session.close()

        _executor.submit(run_download_and_parse)
        return jsonify({"task_id": task_id, "file_name": file_name})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"预检失败: {e}"}), 502
    except Exception as e:
        task = _tasks.get(task_id)
        if task:
            task["status"] = "error"
            task["error"] = f"工作流启动失败: {e}"
        return jsonify({"error": f"工作流启动失败: {e}"}), 500

@app.route('/api/task/<task_id>')
def task_detail(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "task_id": task_id,
        "status": task.get("status"),
        "transcript": task.get("transcript", ""),
        "polished": task.get("polished", ""),
        "summary": task.get("summary", ""),
        "metadata": task.get("metadata", {}),
        "file_name": task.get("file_name", ""),
        "error": task.get("error"),
        "download_progress": task.get("download_progress", {}),
        "intake_progress": task.get("intake_progress", {}),
    })

@app.route('/api/stream/<task_id>')
def stream(task_id):
    def generate():
        if task_id not in _tasks:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Task not found'})}\n\n"
            return

        last_status = ""
        last_transcript = ""
        last_polished = ""
        last_summary = ""
        last_poll = time.time()

        while True:
            task = _tasks.get(task_id)
            if not task:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Task disappeared'})}\n\n"
                break

            status = task["status"]
            transcript = task.get("transcript", "")
            polished = task.get("polished", "")
            summary = task.get("summary", "")
            metadata = task.get("metadata", {})
            error = task.get("error")
            download_progress = task.get("download_progress") or {}
            intake_progress = task.get("intake_progress") or {}

            if last_status == "" and status == "downloading":
                yield f"data: {json.dumps({'type': 'download_start', 'task_id': task_id, 'metadata': metadata, 'file_name': task.get('file_name'), 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0)})}\n\n"

            if status == "downloading":
                yield f"data: {json.dumps({'type': 'download_progress', 'task_id': task_id, 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0), 'phase': download_progress.get('phase', 'running')})}\n\n"

            if intake_progress and intake_progress.get('progress', 0) > 0:
                yield f"data: {json.dumps({'type': 'ingest_progress', 'task_id': task_id, 'progress': intake_progress.get('progress', 0), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0), 'eta_seconds': intake_progress.get('eta_seconds'), 'phase': intake_progress.get('phase', 'preparing')})}\n\n"

            if last_status == "downloading" and status == "transcribing":
                yield f"data: {json.dumps({'type': 'download_done', 'task_id': task_id, 'progress': 100, 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'metadata': metadata})}\n\n"
                yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            if last_status == "" and status == "transcribing":
                if intake_progress:
                    yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            if transcript and transcript != last_transcript:
                yield f"data: {json.dumps({'type': 'chunk', 'text': transcript})}\n\n"
                last_transcript = transcript

            if last_status == "transcribing" and status in ("polishing", "summarizing", "done"):
                yield f"data: {json.dumps({'type': 'transcribe_done'})}\n\n"

            if last_status != "polishing" and status == "polishing":
                yield f"data: {json.dumps({'type': 'polish_start'})}\n\n"

            if polished and polished != last_polished:
                yield f"data: {json.dumps({'type': 'polish_char', 'text': polished})}\n\n"
                last_polished = polished

            if last_status in ("polishing", "transcribing") and status in ("summarizing", "done") and polished:
                yield f"data: {json.dumps({'type': 'polish_done', 'polished_text': polished})}\n\n"

            if last_status != "summarizing" and status == "summarizing":
                yield f"data: {json.dumps({'type': 'summary_start'})}\n\n"

            if summary and summary != last_summary:
                yield f"data: {json.dumps({'type': 'summary_char', 'text': summary})}\n\n"
                last_summary = summary

            if status == "done":
                if summary:
                    yield f"data: {json.dumps({'type': 'summary_done', 'summary_text': summary})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'raw_text': transcript, 'polished_text': polished, 'summary_text': summary, 'char_count': len(polished), 'metadata': metadata, 'task_id': task_id})}\n\n"
                break

            if status == "error":
                yield f"data: {json.dumps({'type': 'error', 'error': error or 'Unknown error'})}\n\n"
                break

            if time.time() - last_poll > 300:
                yield f"data: {json.dumps({'type': 'error', 'error': '处理超时'})}\n\n"
                break

            last_status = status
            last_poll = time.time()
            time.sleep(0.3)

    response = Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })
    return response

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/outputs/<path:filename>')
def output_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)


@app.route('/api/reference/mp4-history', methods=['POST'])
def save_mp4_history():
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"error": "Task ID is required"}), 400

    try:
        result = export_task_to_reference(task_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"保存历史记录失败: {e}"}), 500


@app.route('/api/reference/mp4-history')
def list_mp4_history():
    return jsonify({"items": load_reference_history_list()})


@app.route('/api/reference/mp4-history/reorder', methods=['POST'])
def reorder_mp4_history():
    data = request.get_json() or {}
    ordered_ids = data.get("ordered_ids") or []
    if not isinstance(ordered_ids, list):
        return jsonify({"error": "ordered_ids must be a list"}), 400
    items = reorder_reference_history_items([str(item_id) for item_id in ordered_ids])
    return jsonify({"items": items})


@app.route('/api/reference/mp4-history/<history_id>')
def get_mp4_history(history_id):
    detail = load_reference_history_detail(history_id)
    if not detail:
        return jsonify({"error": "History record not found"}), 404
    return jsonify(detail)


@app.route('/api/reference/mp4-history/<history_id>/ask', methods=['POST'])
def ask_mp4_history(history_id):
    detail = load_reference_history_detail(history_id)
    if not detail:
        return jsonify({"error": "History record not found"}), 404

    data = request.get_json() or {}
    question = str(data.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    task = detail.get("task") or {}
    polished = str(task.get("polished") or "").strip()
    summary = str(task.get("summary") or "").strip()
    if not polished and not summary:
        return jsonify({"error": "No content available for Q&A"}), 400

    polisher = get_polisher()
    answer = polisher.ask_about_content(question, polished, summary)
    qa_item = {
        "id": f"qa-{int(time.time() * 1000)}",
        "question": question,
        "answer": answer,
        "created_at": datetime.now().isoformat(),
    }
    task.setdefault("qa_items", []).insert(0, qa_item)
    detail["task"] = task
    detail["updated_at"] = datetime.now().isoformat()

    record_file = MP4_REFERENCE_DATA_FOLDER / f"{history_id}.json"
    write_json_file(record_file, detail)
    return jsonify({"item": qa_item})


def eastmoney_search_to_target_type(item: dict) -> str | None:
    classify = str(item.get('Classify', '')).strip()
    security_type_name = str(item.get('SecurityTypeName', '')).strip()
    if classify == 'AStock' or security_type_name in {'深A', '沪A', '京A', '科创板', '创业板'}:
        return 'stock'
    if classify == 'Index' or '指数' in security_type_name:
        return 'index'
    if classify == 'Board':
        return 'sector'
    return None


def search_stock_chart_from_eastmoney(query: str) -> list[dict]:
    if not query:
        return []
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        STOCK_EASTMONEY_SEARCH_URL,
        params={
            'input': query,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '20',
        },
        headers=STOCK_EASTMONEY_HEADERS,
        timeout=(5, 12),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    payload = response.json()
    data = (((payload.get('QuotationCodeTable') or {}).get('Data')) or [])
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in data:
        if not isinstance(raw, dict):
            continue
        target_type = eastmoney_search_to_target_type(raw)
        symbol = str(raw.get('Code', '')).strip()
        name = str(raw.get('Name', symbol)).strip() or symbol
        if not target_type or not symbol or not name:
            continue
        key = (target_type, symbol)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            'target_type': target_type,
            'symbol': symbol,
            'name': name,
        })
    return items


@app.route('/api/stock-chart/search')
def stock_chart_search():
    query = str(request.args.get('q', '')).strip()
    try:
        return jsonify({'items': search_stock_chart_from_eastmoney(query)})
    except Exception as exc:
        return jsonify({'items': [], 'error': str(exc)}), 502


@app.route('/api/stock-chart/klines')
def stock_chart_klines():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    adjust = str(request.args.get('adjust', 'qfq')).strip() or 'qfq'
    name = str(request.args.get('name', symbol)).strip() or symbol

    ensure_stock_workspace_entry(target_type, symbol, name)
    items, source = resolve_stock_klines(target_type, symbol, period, adjust)
    cache_file = stock_kline_cache_file(target_type, symbol, period, adjust)
    payload = {
        "symbol": symbol,
        "target_type": target_type,
        "period": period,
        "adjust": adjust,
        "updated_at": datetime.now().isoformat(),
        "source": source,
        "items": items,
    }
    write_json_file(cache_file, payload)
    return jsonify(payload)


@app.route('/api/stock-chart/workspace')
def stock_chart_workspace():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    name = str(request.args.get('name', symbol)).strip() or symbol
    entry = ensure_stock_workspace_entry(target_type, symbol, name)
    workspace_file = stock_workspace_file(target_type, symbol)
    workspace = read_json_file(workspace_file, {
        "id": entry['id'],
        "symbol": symbol,
        "target_type": target_type,
        "period": '1d',
        "adjust": 'qfq',
        "indicators": ['MA', 'EMA', 'BOLL', 'MACD', 'VOL', 'AMOUNT', 'VOLUME_RATIO'],
        "drawing_tool": None,
        "show_auction_panel": True,
        "updated_at": None,
    })
    write_json_file(workspace_file, workspace)
    return jsonify(workspace)


@app.route('/api/stock-chart/workspace', methods=['PUT'])
def save_stock_chart_workspace():
    data = request.get_json() or {}
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    name = str(data.get('name', symbol)).strip() or symbol
    entry = ensure_stock_workspace_entry(target_type, symbol, name)
    payload = {
        "id": entry['id'],
        "symbol": symbol,
        "target_type": target_type,
        "period": str(data.get('period', '1d')),
        "adjust": str(data.get('adjust', 'qfq')),
        "indicators": data.get('indicators') or [],
        "drawing_tool": data.get('drawing_tool'),
        "show_auction_panel": bool(data.get('show_auction_panel', True)),
        "updated_at": datetime.now().isoformat(),
    }
    write_json_file(stock_workspace_file(target_type, symbol), payload)
    return jsonify(payload)


@app.route('/api/stock-chart/annotations')
def stock_chart_annotations():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    return jsonify({"items": load_stock_annotations(target_type, symbol, period)})


@app.route('/api/stock-chart/annotations', methods=['POST'])
def create_stock_chart_annotation():
    data = request.get_json() or {}
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    period = str(data.get('period', '1d')).strip() or '1d'
    annotation_file = stock_annotation_file(target_type, symbol, period)
    annotation_data = read_json_file(annotation_file, {"items": []})
    item = {
        "id": data.get('id') or f"anno-{int(time.time() * 1000)}",
        "overlay_type": data.get('overlay_type') or 'segment',
        "points": data.get('points') or [],
        "styles": data.get('styles') or {},
        "text": data.get('text') or '',
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    annotation_data.setdefault('items', []).insert(0, item)
    write_json_file(annotation_file, annotation_data)
    return jsonify(item)


@app.route('/api/stock-chart/annotations/<annotation_id>', methods=['PUT'])
def update_stock_chart_annotation(annotation_id):
    data = request.get_json() or {}
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    period = str(data.get('period', '1d')).strip() or '1d'
    annotation_file = stock_annotation_file(target_type, symbol, period)
    annotation_data = read_json_file(annotation_file, {"items": []})
    for item in annotation_data.get('items', []):
        if item.get('id') == annotation_id:
            item['points'] = data.get('points') or item.get('points') or []
            item['styles'] = data.get('styles') or item.get('styles') or {}
            item['text'] = data.get('text', item.get('text', ''))
            item['updated_at'] = datetime.now().isoformat()
            write_json_file(annotation_file, annotation_data)
            return jsonify(item)
    return jsonify({"error": "Annotation not found"}), 404


@app.route('/api/stock-chart/annotations/<annotation_id>', methods=['DELETE'])
def delete_stock_chart_annotation(annotation_id):
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    annotation_file = stock_annotation_file(target_type, symbol, period)
    annotation_data = read_json_file(annotation_file, {"items": []})
    items = [item for item in annotation_data.get('items', []) if item.get('id') != annotation_id]
    annotation_data['items'] = items
    write_json_file(annotation_file, annotation_data)
    return jsonify({"ok": True})


def build_stock_auction_phase_snapshot(*, price: float | None, volume: int | None, amount: float | None, match_price: float | None, unmatched_buy_volume: int | None, unmatched_sell_volume: int | None, time_text: str | None, prev_close: float | None, total_volume: int | None) -> dict:
    gap_rate = None
    if price is not None and prev_close not in (None, 0):
        gap_rate = round((price - prev_close) / prev_close * 100, 2)

    auction_volume_ratio = None
    if volume is not None and total_volume not in (None, 0):
        auction_volume_ratio = round(volume / total_volume, 4)

    unmatched_delta = None
    if unmatched_buy_volume is not None and unmatched_sell_volume is not None:
        unmatched_delta = unmatched_buy_volume - unmatched_sell_volume

    strength_label = '中性'
    if gap_rate is not None and unmatched_delta is not None:
        if gap_rate >= 2 and unmatched_delta > 0:
            strength_label = '强势高开'
        elif gap_rate > 0 and unmatched_delta > 0:
            strength_label = '偏强高开'
        elif gap_rate <= -2 and unmatched_delta < 0:
            strength_label = '弱势低开'
        elif gap_rate < 0 and unmatched_delta < 0:
            strength_label = '偏弱低开'

    return {
        'time': time_text,
        'price': price,
        'volume': volume,
        'amount': amount,
        'matchPrice': match_price,
        'unmatchedBuyVolume': unmatched_buy_volume,
        'unmatchedSellVolume': unmatched_sell_volume,
        'gapRate': gap_rate,
        'auctionVolumeRatio': auction_volume_ratio,
        'unmatchedDelta': unmatched_delta,
        'strengthLabel': strength_label,
    }


def fetch_stock_auction_from_tencent(symbol: str) -> dict:
    code = f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'
    response = requests.get(
        f'https://qt.gtimg.cn/q={code}',
        headers={"User-Agent": DOWNLOAD_HEADERS["User-Agent"], "Referer": "https://gu.qq.com/"},
        timeout=(5, 12),
    )
    response.raise_for_status()
    text = response.text
    if '="' not in text:
        raise ValueError('腾讯竞价接口返回异常')
    payload = text.split('="', 1)[1].rsplit('";', 1)[0]
    parts = payload.split('~')
    if len(parts) < 50:
        raise ValueError('腾讯竞价接口字段不足')

    def to_price(index: int) -> float | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return float(value)
        except ValueError:
            return None

    def to_volume(index: int) -> int | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return int(float(value))
        except ValueError:
            return None

    def to_amount(index: int) -> float | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return float(value)
        except ValueError:
            return None

    quote_time = parts[30] if len(parts) > 30 else ''
    trade_date = f"{quote_time[0:4]}-{quote_time[4:6]}-{quote_time[6:8]}" if len(quote_time) >= 8 else datetime.now().strftime('%Y-%m-%d')
    trade_clock = f"{quote_time[8:10]}:{quote_time[10:12]}:{quote_time[12:14]}" if len(quote_time) >= 14 else None
    prev_close = to_price(4)
    total_volume = to_volume(36)
    total_amount = to_amount(37)
    unmatched_buy_volume = to_volume(10)
    unmatched_sell_volume = to_volume(20)

    opening = build_stock_auction_phase_snapshot(
        time_text='09:25:00',
        price=to_price(5),
        volume=total_volume,
        amount=total_amount,
        match_price=to_price(3),
        unmatched_buy_volume=unmatched_buy_volume,
        unmatched_sell_volume=unmatched_sell_volume,
        prev_close=prev_close,
        total_volume=total_volume,
    )
    closing = build_stock_auction_phase_snapshot(
        time_text=trade_clock or '15:00:00',
        price=to_price(3),
        volume=total_volume,
        amount=total_amount,
        match_price=to_price(3),
        unmatched_buy_volume=unmatched_buy_volume,
        unmatched_sell_volume=unmatched_sell_volume,
        prev_close=prev_close,
        total_volume=total_volume,
    )
    return {
        'symbol': symbol,
        'trade_date': trade_date,
        'opening': opening,
        'closing': closing,
    }


@app.route('/api/stock-chart/auction')
def stock_chart_auction():
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    payload = fetch_stock_auction_from_tencent(symbol)
    cache_file = STOCK_REFERENCE_CACHE_FOLDER / 'auction' / f"{symbol}.json"
    write_json_file(cache_file, payload)
    return jsonify(payload)


@app.route('/api/export-markdown/<task_id>')
def export_markdown(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if task.get("status") != "done":
        return jsonify({"error": "任务尚未完成，暂时不能导出 Markdown"}), 400

    markdown = build_markdown_document(task)
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or task.get("file_name") or "untitled").strip()
    filename = build_export_filename(task, task_id)
    ascii_filename = filename.encode('ascii', 'replace').decode('ascii')
    utf8_filename = quote(filename)

    return Response(
        markdown,
        mimetype='text/markdown; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename}",
        }
    )


@app.route('/api/ask', methods=['POST'])
def ask_about_content():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    task_id = data.get("task_id")
    question = data.get("question", "").strip()

    if not task_id:
        return jsonify({"error": "Task ID is required"}), 400
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if task.get("status") != "done":
        return jsonify({"error": "Task is not completed yet"}), 400

    polished = (task.get("polished") or "").strip()
    summary = (task.get("summary") or "").strip()

    if not polished and not summary:
        return jsonify({"error": "No content available for Q&A"}), 400

    polisher = get_polisher()
    answer = polisher.ask_about_content(question, polished, summary)
    task.setdefault("qa_items", []).insert(0, {
        "id": f"qa-{int(time.time() * 1000)}",
        "question": question,
        "answer": answer,
        "created_at": datetime.now().isoformat(),
    })
    return jsonify({"answer": answer})

if __name__ == '__main__':
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 5000))
    if result == 0:
        print("[启动] 端口 5000 已被占用，尝试接管...")
        import subprocess
        try:
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if ':5000' in line and 'LISTENING' in line:
                    pid = int(line.split()[-1])
                    print(f"[启动] 杀掉残留进程 PID={pid}")
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
                    break
        except:
            pass
    sock.close()
    print("[启动] 启动 Flask on 0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
