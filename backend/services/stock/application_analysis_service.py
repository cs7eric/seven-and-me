from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from backend.config.settings import (
    APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER,
    BASE_DIR,
    STOCK_REFERENCE_CACHE_FOLDER,
)
from backend.services.ai_provider_service import ai_provider_registry
from backend.services.stock.kline_service import resolve_stock_klines
from backend.services.stock.sample_data_service import sample_stock_klines
from backend.utils.json_io import read_json_file

BENCHMARKS = {
    '000001': '上证指数',
    '399001': '深证成指',
    '000688': '科创50',
    '000300': '沪深300',
}

PROMPT_FILE = BASE_DIR / 'prompt' / 'annotation.md'
SHORT_TERM_DAILY_PROMPT_FILE = BASE_DIR / 'prompt' / 'short_term_daily.md'
BREADTH_SERIES_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'series.json'
APPLICATION_ANALYSIS_DUMP_DIR = Path(BASE_DIR) / 'runtime' / 'application-analysis-dumps'
APPLICATION_ANALYSIS_DAILY_SNAPSHOT_DIR = APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER
APPLICATION_ANALYSIS_DAILY_DEFAULT_HOUR = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_DAILY_HOUR') or '16')
APPLICATION_ANALYSIS_DAILY_DEFAULT_MINUTE = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_DAILY_MINUTE') or '0')
APPLICATION_ANALYSIS_DAILY_TIMEZONE_OFFSET_HOURS = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_DAILY_TZ_OFFSET_HOURS') or '8')
APPLICATION_ANALYSIS_MODEL = os.getenv('MINIMAX_APPLICATION_ANALYSIS_MODEL') or os.getenv('MINIMAX_MODEL') or 'MiniMax-M2.7'
APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS') or '120000')
APPLICATION_ANALYSIS_TIMEOUT = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_TIMEOUT') or '600')
TARGET_DAILY_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_TARGET_DAILY') or '30')
TARGET_WEEKLY_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_TARGET_WEEKLY') or '10')
TARGET_MONTHLY_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_TARGET_MONTHLY') or '6')
TARGET_HORIZON_DAYS = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_HORIZON_DAYS') or '120')
TARGET_HORIZON_SEGMENTS = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_HORIZON_SEGMENTS') or '4')
APPLICATION_ANALYSIS_RECENT30_DAYS = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_RECENT30_DAYS') or '30')
BENCHMARK_DAILY_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_BENCHMARK_DAILY') or '10')
BENCHMARK_WEEKLY_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_BENCHMARK_WEEKLY') or '5')
BREADTH_KEEP = int(os.getenv('MINIMAX_APPLICATION_ANALYSIS_BREADTH') or '10')


def _prompt_text() -> str:
    raw = Path(PROMPT_FILE).read_text(encoding='utf-8').strip()
    enforcement = (
        "\n\n【输出硬约束】\n"
        "- 你只能输出一个 JSON 对象，且该对象必须以字符 `{` 开头并以 `}` 结束。\n"
        "- 严禁输出 <think>、<analysis>、```、Markdown、解释、问候、总结。\n"
        "- 严禁使用 reasoning_content、reasoning_details、audio_content 等非 JSON 文本。\n"
        "- 严禁在 analysis_result 之外再写任何根字段（symbol、name、target_type 等必须放在 analysis_result.target 内部）。\n"
        "- 只允许使用本 prompt 中已经定义过的字段；不要新增键。\n"
        "- analysis_result.overlay_annotations 字段是必填项，类型必须是非空数组。\n"
        "- 数组中每个元素必须包含 overlay_type、points、text、styles、period 字段；"
        "points 中每个点必须包含 timestamp 与 value；"
        "timestamp 必须从 analysis_input 中真实存在的 timestamp 中取（单位毫秒），"
        "value 必须等于该 timestamp 对应 K 线的 close 价格，"
        "period 只能是 '1d' 或 '1w'。\n"
        "- 不允许输出 points 为空数组、不允许 points 中的 timestamp 在 analysis_input 中找不到。\n"
        "- overlay_type 只能是以下 7 种之一："
        "price_zone（支撑/阻力/水平带）、trend_line（趋势线/趋势段）、"
        "pattern_polyline（形态折线）、event_marker（事件/突破/单点标记）、"
        "gap_zone（跳空/缺口）、ma_marker（均线参考点）、"
        "sentiment_marker（情绪/背离/单点标记）。\n"
        "- 推荐语义映射：支撑/阻力/区间 → price_zone；趋势/趋势线 → trend_line；"
        "K 线形态/突破/单点信号 → event_marker；"
        "量价背离/情绪拐点 → sentiment_marker。\n"
    )
    return raw + enforcement


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_timestamp(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _bar_item(item: dict) -> dict:
    return {
        'timestamp': _int_timestamp(item.get('timestamp')),
        'open': _number(item.get('open')),
        'high': _number(item.get('high')),
        'low': _number(item.get('low')),
        'close': _number(item.get('close')),
        'volume': _number(item.get('volume')),
        'turnover': _number(item.get('turnover')),
        'turnover_rate': _number(item.get('turnover_rate')),
        'volume_ratio': _number(item.get('volume_ratio')),
    }


def _load_bars(target_type: str, symbol: str, period: str, adjust: str) -> tuple[list[dict], str]:
    items, source = resolve_stock_klines(target_type, symbol, period, adjust, sample_stock_klines)
    normalized = [_bar_item(item) for item in items]
    normalized.sort(key=lambda item: item['timestamp'])
    return normalized, source


def _breadth_item(item: dict) -> dict:
    timestamp = _int_timestamp(item.get('timestamp'))
    date = str(item.get('date') or '')
    if not timestamp and date:
        from datetime import datetime
        try:
            timestamp = int(datetime.strptime(date, '%Y-%m-%d').timestamp() * 1000)
        except ValueError:
            timestamp = 0
    return {
        'date': date,
        'timestamp': timestamp,
        'upCount': _number(item.get('upCount')),
        'downCount': _number(item.get('downCount')),
        'limitUpCount': _number(item.get('limitUpCount')),
        'limitDownCount': _number(item.get('limitDownCount')),
        'failedLimitUpCount': _number(item.get('failedLimitUpCount')),
        'breakRate': _number(item.get('breakRate')),
        'maxLianBan': _number(item.get('maxLianBan')),
        'yesterdayLimitUpReturn': _number(item.get('yesterdayLimitUpReturn')),
        'totalTurnover': _number(item.get('totalTurnover')),
        'downOver5Count': _number(item.get('downOver5Count')),
        'new20HighCount': _number(item.get('new20HighCount')),
        'new20LowCount': _number(item.get('new20LowCount')),
    }


def _load_breadth_series() -> list[dict]:
    series = read_json_file(BREADTH_SERIES_FILE, [])
    if not isinstance(series, list):
        return []
    return [_breadth_item(item) for item in series if isinstance(item, dict)][-180:]



def _keep_tail(items: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return []
    return items[-limit:]


def _aggregate_to_period(daily: list[dict], period: str) -> list[dict]:
    if not daily:
        return []
    from datetime import datetime
    if period == 'weekly':
        fmt = '%Y-%W'
    elif period == 'monthly':
        fmt = '%Y-%m'
    else:
        return list(daily)
    by_bucket: dict[str, list[dict]] = {}
    for bar in daily:
        ts = _int_timestamp(bar.get('timestamp'))
        if not ts:
            continue
        try:
            d = datetime.utcfromtimestamp(ts / 1000)
        except (OSError, ValueError, OverflowError):
            continue
        key = d.strftime(fmt)
        by_bucket.setdefault(key, []).append(bar)
    out: list[dict] = []
    for key in sorted(by_bucket.keys()):
        group = by_bucket[key]
        if not group:
            continue
        first = group[0]
        last = group[-1]
        highs: list[float] = []
        lows: list[float] = []
        volume = 0.0
        turnover = 0.0
        for bar in group:
            high_value = float(bar.get('high') or 0)
            low_value = float(bar.get('low') or 0)
            if high_value:
                highs.append(high_value)
            if low_value:
                lows.append(low_value)
            volume += float(bar.get('volume') or 0)
            turnover += float(bar.get('turnover') or 0)
        out.append({
            'timestamp': _int_timestamp(last.get('timestamp')),
            'open': float(first.get('open') or 0),
            'high': max(highs) if highs else 0,
            'low': min(lows) if lows else 0,
            'close': float(last.get('close') or 0),
            'volume': volume,
            'turnover': turnover,
        })
    return out


def _split_daily_into_segments(daily: list[dict], segments: int) -> list[list[dict]]:
    if segments <= 1 or len(daily) <= segments:
        return [daily]
    total = len(daily)
    chunk_size = total // segments
    remainder = total - chunk_size * segments
    out: list[list[dict]] = []
    cursor = 0
    for index in range(segments):
        extra = 1 if index < remainder else 0
        size = chunk_size + extra
        out.append(daily[cursor:cursor + size])
        cursor += size
    return out


def _filter_by_timestamp_range(items: list[dict], start_ts: int, end_ts: int) -> list[dict]:
    if not items:
        return []
    return [item for item in items if start_ts <= _int_timestamp(item.get('timestamp')) <= end_ts]


def build_horizon_analysis_input(
    target_type: str,
    symbol: str,
    name: str,
    adjust: str = 'qfq',
    days: int = TARGET_HORIZON_DAYS,
    segments: int = TARGET_HORIZON_SEGMENTS,
    monthly_keep: int = TARGET_MONTHLY_KEEP,
    weekly_keep: int = TARGET_WEEKLY_KEEP,
) -> dict:
    segments = max(1, segments)
    days = max(segments, days)
    daily, daily_source = _load_bars(target_type, symbol, '1d', adjust)
    weekly, weekly_source = _load_bars(target_type, symbol, '1w', adjust)
    monthly = _aggregate_to_period(daily, 'monthly')
    daily_window = _keep_tail(daily, days)
    weekly_for_ai = _keep_tail(weekly, weekly_keep)
    monthly_for_ai = _keep_tail(monthly, monthly_keep)
    daily_segments = _split_daily_into_segments(daily_window, segments)
    benchmark_segments: dict[str, dict] = {}
    benchmark_sources: dict[str, dict] = {}
    for benchmark_symbol, benchmark_name in BENCHMARKS.items():
        benchmark_daily, benchmark_daily_source = _load_bars('index', benchmark_symbol, '1d', adjust)
        benchmark_weekly, benchmark_weekly_source = _load_bars('index', benchmark_symbol, '1w', adjust)
        benchmark_monthly = _aggregate_to_period(benchmark_daily, 'monthly')
        benchmark_segments[benchmark_symbol] = {
            'name': benchmark_name,
            'daily_segments': _split_daily_into_segments(_keep_tail(benchmark_daily, days), segments),
            'weekly': _keep_tail(benchmark_weekly, max(weekly_keep, 12)),
            'monthly': _keep_tail(benchmark_monthly, max(monthly_keep, 6)),
        }
        benchmark_sources[benchmark_symbol] = {
            'daily': benchmark_daily_source,
            'daily_total': len(benchmark_daily),
            'weekly': benchmark_weekly_source,
            'weekly_total': len(benchmark_weekly),
            'monthly': 'aggregated',
            'monthly_total': len(benchmark_monthly),
        }
    breadth_window = _keep_tail(_load_breadth_series(), max(60, days))
    return {
        'horizon': {
            'days': days,
            'segments': segments,
            'monthly_keep': monthly_keep,
            'weekly_keep': weekly_keep,
        },
        'target': {
            'target_type': target_type,
            'symbol': symbol,
            'name': name,
        },
        'daily_segments': [
            {
                'segment_index': index,
                'period': '1d',
                'item_count': len(segment_items),
                'first_timestamp': _int_timestamp(segment_items[0].get('timestamp')) if segment_items else 0,
                'last_timestamp': _int_timestamp(segment_items[-1].get('timestamp')) if segment_items else 0,
                'items': segment_items,
            }
            for index, segment_items in enumerate(daily_segments)
        ],
        'weekly_bars': {
            'period': '1w',
            'total_count': len(weekly),
            'items': weekly_for_ai,
        },
        'monthly_bars': {
            'period': '1m',
            'total_count': len(monthly),
            'items': monthly_for_ai,
        },
        'benchmark_bars': benchmark_segments,
        'market_breadth_series': breadth_window,
        'analysis_windows': [5, 10, 20, 30, 60, 120],
        'enabled_features': {
            'support_resistance': True,
            'trend_detection': True,
            'volume_price_analysis': True,
            'turnover_analysis': True,
            'pattern_candidates': True,
            'multi_index_resonance': True,
            'market_sentiment_overlay': True,
        },
        '_sources': {
            'daily': daily_source,
            'daily_total': len(daily),
            'daily_window': len(daily_window),
            'weekly': weekly_source,
            'weekly_total': len(weekly),
            'weekly_kept': len(weekly_for_ai),
            'monthly': 'aggregated',
            'monthly_total': len(monthly),
            'monthly_kept': len(monthly_for_ai),
            'benchmarks': benchmark_sources,
            'market_breadth_series_kept': len(breadth_window),
            'prompt': str(PROMPT_FILE),
        },
    }


def build_application_analysis_input(target_type: str, symbol: str, name: str, adjust: str = 'qfq') -> dict:
    daily, daily_source = _load_bars(target_type, symbol, '1d', adjust)
    weekly, weekly_source = _load_bars(target_type, symbol, '1w', adjust)
    daily_for_ai = _keep_tail(daily, TARGET_DAILY_KEEP)
    weekly_for_ai = _keep_tail(weekly, TARGET_WEEKLY_KEEP)
    benchmark_bars = {}
    benchmark_sources = {}
    for benchmark_symbol, benchmark_name in BENCHMARKS.items():
        daily_items, daily_benchmark_source = _load_bars('index', benchmark_symbol, '1d', adjust)
        weekly_items, weekly_benchmark_source = _load_bars('index', benchmark_symbol, '1w', adjust)
        benchmark_bars[benchmark_symbol] = {
            'name': benchmark_name,
            'daily': _keep_tail(daily_items, BENCHMARK_DAILY_KEEP),
            'weekly': _keep_tail(weekly_items, BENCHMARK_WEEKLY_KEEP),
        }
        benchmark_sources[benchmark_symbol] = {
            'daily': daily_benchmark_source,
            'daily_count': len(daily_items),
            'daily_kept': len(benchmark_bars[benchmark_symbol]['daily']),
            'weekly': weekly_benchmark_source,
            'weekly_count': len(weekly_items),
            'weekly_kept': len(benchmark_bars[benchmark_symbol]['weekly']),
        }
    breadth_series = _keep_tail(_load_breadth_series(), BREADTH_KEEP)

    return {
        'target': {
            'target_type': target_type,
            'symbol': symbol,
            'name': name,
        },
        'bars': {
            'daily': {
                'period': '1d',
                'adjust': adjust,
                'total_count': len(daily),
                'items': daily_for_ai,
            },
            'weekly': {
                'period': '1w',
                'adjust': adjust,
                'total_count': len(weekly),
                'items': weekly_for_ai,
            },
        },
        'benchmark_bars': benchmark_bars,
        'market_breadth_series': breadth_series,
        'analysis_windows': [5, 10, 20, 30, 60],
        'enabled_features': {
            'support_resistance': True,
            'trend_detection': True,
            'volume_price_analysis': True,
            'turnover_analysis': True,
            'pattern_candidates': True,
            'multi_index_resonance': True,
            'market_sentiment_overlay': True,
        },
        '_sources': {
            'daily': daily_source,
            'daily_total_count': len(daily),
            'daily_kept': len(daily_for_ai),
            'weekly': weekly_source,
            'weekly_total_count': len(weekly),
            'weekly_kept': len(weekly_for_ai),
            'benchmarks': benchmark_sources,
            'market_breadth_series': 'cache' if breadth_series else 'none',
            'market_breadth_series_kept': len(breadth_series),
            'prompt': str(PROMPT_FILE),
        },
    }


def _strip_think_blocks(text: str) -> str:
    if '<think>' not in text and '</think>' not in text:
        return text
    import re
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text)
    return cleaned.strip()


def _first_balanced_json(text: str) -> str:
    if not text:
        return ''
    start = text.find('{')
    if start < 0:
        return ''
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ''


def _extract_ai_content(payload: dict) -> str:
    candidates: list[str] = []

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 6 or value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text.startswith('{') or text.startswith('```'):
                candidates.append(text)
            return
        if isinstance(value, dict):
            for key in ['content', 'text', 'reply', 'output', 'answer']:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip())
            for key in ['message', 'messages', 'delta', 'choices', 'data']:
                if key in value:
                    collect(value.get(key), depth + 1)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)

    collect(payload)
    json_like = [item for item in candidates if item.lstrip().startswith(('{', '```'))]
    if json_like:
        raw = max(json_like, key=len)
    elif candidates:
        raw = max(candidates, key=len)
    else:
        return ''
    raw = _strip_think_blocks(raw)
    if raw.startswith('```'):
        raw = raw.strip('`')
        raw = raw.replace('json\n', '', 1).replace('JSON\n', '', 1)
        raw = raw.strip()
    balanced = _first_balanced_json(raw)
    return balanced or raw


def _minimax_error_preview(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ''
    safe_payload = {}
    for key in ['base_resp', 'id', 'model', 'created', 'usage']:
        if key in payload:
            safe_payload[key] = payload.get(key)
    if not safe_payload:
        safe_payload = {key: payload.get(key) for key in list(payload.keys())[:8]}
    return json.dumps(safe_payload, ensure_ascii=False)[:800]


def _write_analysis_input_file(analysis_input: dict) -> tuple[Path, str, str]:
    base_handle = tempfile.NamedTemporaryFile('w', prefix='application-analysis-', encoding='utf-8', delete=False)
    path = Path(base_handle.name)
    try:
        json.dump({'analysis_input': analysis_input}, base_handle, ensure_ascii=False, separators=(',', ':'))
        base_handle.flush()
    finally:
        base_handle.close()
    return path, path.name, path.with_suffix('.txt').name


def _write_text_chunk_file(index: int, total: int, payload: str) -> tuple[Path, str]:
    base_handle = tempfile.NamedTemporaryFile('w', prefix=f'application-analysis-chunk-{index + 1}-', suffix='.txt', encoding='utf-8', delete=False)
    path = Path(base_handle.name)
    try:
        base_handle.write(f'# chunk {index + 1}/{total}\n# purpose: application-analysis\n')
        base_handle.write(payload)
        base_handle.flush()
    finally:
        base_handle.close()
    return path, path.name


def _chunk_analysis_input_text(analysis_input: dict) -> list[str]:
    serialized = json.dumps({'analysis_input': analysis_input}, ensure_ascii=False, separators=(',', ':'))
    if len(serialized) <= APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS:
        return [serialized]
    header = {
        'chunk_warnings': [
            f'analysis_input split into multiple user messages because the per-message char limit was {APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS}.',
            f'original total chars: {len(serialized)}.',
            'Concatenate all chunks in order to reconstruct the original JSON object.',
        ],
    }
    chunks: list[str] = [json.dumps(header, ensure_ascii=False, separators=(',', ':'))]
    remaining = serialized
    while len(remaining) > APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS:
        chunks.append(remaining[:APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS])
        remaining = remaining[APPLICATION_ANALYSIS_TEXT_CHUNK_CHARS:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _extract_file_id(payload: dict) -> str:
    file_obj = payload.get('file') if isinstance(payload, dict) else None
    if isinstance(file_obj, dict) and file_obj.get('file_id'):
        return str(file_obj.get('file_id'))
    if isinstance(payload, dict) and payload.get('file_id'):
        return str(payload.get('file_id'))
    return ''


def _call_minimax_json(system_prompt: str, analysis_input: dict, target_type: str, symbol: str, name: str) -> tuple[dict, dict]:
    import time

    polisher = ai_provider_registry.get_polisher()
    log_prefix = '[ApplicationAnalysis]'
    print(f'{log_prefix} start model={APPLICATION_ANALYSIS_MODEL} timeout={APPLICATION_ANALYSIS_TIMEOUT}s', flush=True)
    chunks = _chunk_analysis_input_text(analysis_input)
    print(f'{log_prefix} chunks={len(chunks)} chars={[len(c) for c in chunks]} system_prompt_chars={len(system_prompt)}', flush=True)
    url = f'{polisher.BASE_URL}/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {polisher.api_key}',
        'Content-Type': 'application/json',
    }
    user_messages: list[dict] = []
    for index, payload in enumerate(chunks):
        label = f'分析输入片段 {index + 1}/{len(chunks)}，请按顺序拼接：' if len(chunks) > 1 else '分析输入 JSON：'
        user_messages.append({'role': 'user', 'name': 'User', 'content': f'{label}\n{payload}'})
    summary = (
        f'请阅读上面的 {len(chunks)} 条 user 消息，把它们按顺序拼成完整 JSON 字符串后，'
        '按照系统 prompt 字段说明输出唯一 JSON 对象。'
        '禁止输出 <think>、<analysis>、```、Markdown、解释、总结、reasoning_content。'
        '输出必须以 `{` 开头并以 `}` 结束；根字段只能出现 analysis_result。'
    )
    user_messages.append({'role': 'user', 'name': 'User', 'content': summary})
    payload_body = {
        'model': APPLICATION_ANALYSIS_MODEL,
        'messages': [{'role': 'system', 'content': system_prompt, 'name': 'MiniMax AI'}, *user_messages],
        'temperature': 0.2,
        'stream': False,
    }
    body_size = sum(len(json.dumps(m, ensure_ascii=False)) for m in payload_body['messages'])
    print(f'{log_prefix} request url={url} total_message_chars={body_size}', flush=True)
    started = time.monotonic()
    try:
        response = requests.post(url, headers=headers, json=payload_body, timeout=APPLICATION_ANALYSIS_TIMEOUT)
    except requests.exceptions.Timeout as exc:
        elapsed = int(time.monotonic() - started)
        print(f'{log_prefix} timeout after {elapsed}s url={url}', flush=True)
        raise ValueError(f'Application Analysis AI 请求超时 ({elapsed}s)，timeout={APPLICATION_ANALYSIS_TIMEOUT}s') from exc
    except requests.exceptions.ConnectionError as exc:
        elapsed = int(time.monotonic() - started)
        print(f'{log_prefix} connection error after {elapsed}s url={url} error={exc}', flush=True)
        raise ValueError(f'Application Analysis AI 网络连接失败: {exc}') from exc
    elapsed = int(time.monotonic() - started)
    print(f'{log_prefix} response status={response.status_code} elapsed={elapsed}s', flush=True)
    if response.status_code != 200:
        snippet = response.text[:800]
        print(f'{log_prefix} non-200 body snippet: {snippet}', flush=True)
        raise ValueError(f'Application Analysis AI 请求失败: {response.status_code} {snippet}')
    raw = response.json()
    raw_path: Path | None = None
    content_path: Path | None = None
    try:
        APPLICATION_ANALYSIS_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        safe_target = f'{target_type or "na"}-{symbol or "na"}-{name or "na"}'.replace('/', '_').replace('\\', '_')
        raw_path = APPLICATION_ANALYSIS_DUMP_DIR / f'{timestamp}-{safe_target}-raw.json'
        content_path = APPLICATION_ANALYSIS_DUMP_DIR / f'{timestamp}-{safe_target}-content.txt'
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        extracted = _extract_ai_content(raw)
        content_path.write_text(extracted or '', encoding='utf-8')
        print(f'{log_prefix} dumped raw={raw_path} content={content_path} content_chars={len(extracted)}', flush=True)
    except Exception as dump_exc:
        print(f'{log_prefix} dump failed: {dump_exc}', flush=True)
    content = _extract_ai_content(raw).strip()
    print(f'{log_prefix} content_chars={len(content)} base_resp={raw.get("base_resp") if isinstance(raw, dict) else None}', flush=True)
    if not content:
        preview = _minimax_error_preview(raw)
        raise ValueError(f'Application Analysis AI 返回为空，响应摘要: {preview}')
    try:
        parsed = polisher._parse_json_object(content)
        print(f'{log_prefix} json parsed ok keys={list(parsed.keys()) if isinstance(parsed, dict) else "non-dict"}', flush=True)
        return parsed, {'raw': str(raw_path) if raw_path else '', 'content': str(content_path) if content_path else ''}
    except Exception as exc:
        raise ValueError(f'Application Analysis AI JSON 解析失败: {exc}; 内容预览: {content[:800]}') from exc


def _valid_point(point: Any) -> bool:
    return isinstance(point, dict) and isinstance(point.get('timestamp'), (int, float)) and isinstance(point.get('value'), (int, float))


def _locate_analysis_result(parsed: Any) -> dict:
    if isinstance(parsed, dict) and isinstance(parsed.get('analysis_result'), dict):
        return parsed
    candidate_keys = ['analysis_result', 'result', 'data', 'analysis', 'output', 'payload']
    if isinstance(parsed, dict):
        for key in candidate_keys:
            value = parsed.get(key)
            if isinstance(value, dict) and (
                'target' in value
                or 'overlay_annotations' in value
                or 'summary' in value
                or 'trend_state' in value
            ):
                parsed['analysis_result'] = value
                return parsed
        if 'symbol' in parsed and 'name' in parsed and 'target_type' in parsed:
            rebuilt = {
                'target': {
                    'target_type': parsed.get('target_type'),
                    'symbol': parsed.get('symbol'),
                    'name': parsed.get('name'),
                }
            }
            for extra_key in ['trend_state', 'rolling_metrics', 'support_resistance_zones', 'pattern_candidates', 'market_sentiment', 'multi_index_resonance', 'summary', 'data_quality', 'overlay_annotations']:
                if extra_key in parsed:
                    rebuilt[extra_key] = parsed[extra_key]
            parsed['analysis_result'] = rebuilt
            return parsed
    raise ValueError('AI 结果缺少 analysis_result')


def _sanitize_annotations(result: dict) -> dict:
    result = _locate_analysis_result(result)
    analysis_result = result.get('analysis_result')
    if not isinstance(analysis_result, dict):
        raise ValueError('AI 结果缺少 analysis_result')
    overlays = analysis_result.get('overlay_annotations')
    if not isinstance(overlays, list) or not overlays:
        analysis_result['overlay_annotations'] = []
        data_quality = analysis_result.get('data_quality')
        if not isinstance(data_quality, dict):
            data_quality = {}
            analysis_result['data_quality'] = data_quality
        warnings = data_quality.get('warnings')
        if not isinstance(warnings, list):
            warnings = []
            data_quality['warnings'] = warnings
        warnings.append('AI 未返回 overlay_annotations；图上无 AI 标注。')
        return result
    valid_types = {'price_zone', 'trend_line', 'pattern_polyline', 'event_marker', 'gap_zone', 'ma_marker', 'sentiment_marker'}
    overlay_type_aliases = {
        'support': 'price_zone',
        'resistance': 'price_zone',
        'support_zone': 'price_zone',
        'resistance_zone': 'price_zone',
        'supply_zone': 'price_zone',
        'demand_zone': 'price_zone',
        'zone': 'price_zone',
        'price_zone': 'price_zone',
        'gap_zone': 'gap_zone',
        'gap': 'gap_zone',
        'trend': 'trend_line',
        'trendline': 'trend_line',
        'trend_line': 'trend_line',
        'downtrend': 'trend_line',
        'uptrend': 'trend_line',
        'pattern': 'pattern_polyline',
        'pattern_polyline': 'pattern_polyline',
        'candlestick_pattern': 'event_marker',
        'volume_divergence': 'sentiment_marker',
        'divergence': 'sentiment_marker',
        'sentiment': 'sentiment_marker',
        'sentiment_marker': 'sentiment_marker',
        'event': 'event_marker',
        'event_marker': 'event_marker',
        'signal': 'event_marker',
        'marker': 'event_marker',
        'breakout': 'event_marker',
        'ma': 'ma_marker',
        'moving_average': 'ma_marker',
        'ma_marker': 'ma_marker',
    }
    limits = {
        'price_zone': 8,
        'trend_line': 4,
        'pattern_polyline': 3,
        'event_marker': 8,
        'sentiment_marker': 5,
        'gap_zone': 5,
        'ma_marker': 8,
    }
    counts: dict[str, int] = {}
    clean = []
    for item in overlays:
        if not isinstance(item, dict):
            continue
        raw_type = str(item.get('overlay_type') or '').strip().lower()
        overlay_type = overlay_type_aliases.get(raw_type, raw_type)
        if overlay_type not in valid_types:
            continue
        points = item.get('points') or []
        if not isinstance(points, list) or not points or not all(_valid_point(point) for point in points):
            continue
        if overlay_type in {'price_zone', 'gap_zone', 'trend_line', 'pattern_polyline'} and len(points) < 2:
            continue
        if counts.get(overlay_type, 0) >= limits.get(overlay_type, 99):
            continue
        counts[overlay_type] = counts.get(overlay_type, 0) + 1
        clean.append({
            'target_type': str(item.get('target_type') or analysis_result.get('target', {}).get('target_type') or 'stock'),
            'symbol': str(item.get('symbol') or analysis_result.get('target', {}).get('symbol') or ''),
            'period': str(item.get('period') or '1d'),
            'overlay_type': overlay_type,
            'points': [{'timestamp': _int_timestamp(point.get('timestamp')), 'value': _number(point.get('value'))} for point in points],
            'text': str(item.get('text') or ''),
            'styles': item.get('styles') if isinstance(item.get('styles'), dict) else {},
        })
    analysis_result['overlay_annotations'] = clean
    return result


def run_application_analysis(target_type: str, symbol: str, name: str, adjust: str = 'qfq') -> dict:
    analysis_input = build_application_analysis_input(target_type, symbol, name, adjust)
    prompt = _prompt_text()
    print(f'[ApplicationAnalysis] prompt chars={len(prompt)} preview={prompt[:200]!r}', flush=True)
    raw_response, dump_paths = _call_minimax_json(prompt, analysis_input, target_type, symbol, name)
    raw_keys = list(raw_response.keys()) if isinstance(raw_response, dict) else None
    print(f'[ApplicationAnalysis] raw keys={raw_keys}', flush=True)
    sanitized = _sanitize_annotations(raw_response)
    return {
        'analysis_input': analysis_input,
        'analysis_result': sanitized.get('analysis_result'),
        'raw_result': sanitized,
        'raw_root_keys': raw_keys,
        'dump_paths': dump_paths,
    }


def _build_segment_input(horizon_input: dict, segment_index: int) -> dict:
    segments = horizon_input.get('daily_segments') or []
    target_segment = segments[segment_index] if 0 <= segment_index < len(segments) else None
    benchmark_segments_filtered: dict[str, dict] = {}
    for symbol, data in (horizon_input.get('benchmark_bars') or {}).items():
        benchmark_daily_segments = data.get('daily_segments') or []
        segment = benchmark_daily_segments[segment_index] if 0 <= segment_index < len(benchmark_daily_segments) else None
        benchmark_segments_filtered[symbol] = {
            **data,
            'daily_segments': [segment] if segment else [],
        }
    start_ts = target_segment.get('first_timestamp') if target_segment else 0
    end_ts = target_segment.get('last_timestamp') if target_segment else 0
    breadth_filtered: list = []
    if start_ts and end_ts:
        breadth_filtered = _filter_by_timestamp_range(horizon_input.get('market_breadth_series') or [], start_ts, end_ts)
        if not breadth_filtered:
            breadth_filtered = _keep_tail(horizon_input.get('market_breadth_series') or [], 5)
    return {
        'target': horizon_input.get('target'),
        'horizon': horizon_input.get('horizon'),
        'bars': {
            'daily': {
                'period': '1d',
                'segment_index': segment_index,
                'items': (target_segment or {}).get('items') or [],
            },
            'weekly': {
                'period': '1w',
                'items': horizon_input.get('weekly_bars', {}).get('items') or [],
            },
            'monthly': {
                'period': '1m',
                'items': horizon_input.get('monthly_bars', {}).get('items') or [],
            },
        },
        'benchmark_bars': benchmark_segments_filtered,
        'market_breadth_series': breadth_filtered,
        'analysis_windows': horizon_input.get('analysis_windows') or [5, 10, 20, 30, 60, 120],
        'enabled_features': horizon_input.get('enabled_features') or {},
    }


def _merge_segment_results(segment_results: list[dict]) -> dict:
    merged: dict = {}
    trend_state: dict = {}
    rolling_metrics: dict = {}
    support_zones: list = []
    pattern_candidates: list = []
    overlay_annotations: list = []
    multi_index_resonance: dict = {}
    market_sentiment: dict = {}
    data_quality_warnings: list = []
    last_summary: dict = {}
    total_segments = len(segment_results)
    for index, segment in enumerate(segment_results):
        if not isinstance(segment, dict):
            continue
        if isinstance(segment.get('trend_state'), dict):
            trend_state[f'segment_{index}'] = segment['trend_state']
        if isinstance(segment.get('rolling_metrics'), dict):
            rolling_metrics[f'segment_{index}'] = segment['rolling_metrics']
        if isinstance(segment.get('support_resistance_zones'), list):
            support_zones.extend([item for item in segment['support_resistance_zones'] if isinstance(item, dict)])
        if isinstance(segment.get('pattern_candidates'), list):
            pattern_candidates.extend([item for item in segment['pattern_candidates'] if isinstance(item, dict)])
        if isinstance(segment.get('overlay_annotations'), list):
            for item in segment['overlay_annotations']:
                if isinstance(item, dict):
                    item['_segment'] = index
                    overlay_annotations.append(item)
        if isinstance(segment.get('multi_index_resonance'), dict) and index == total_segments - 1:
            multi_index_resonance = segment['multi_index_resonance']
        if isinstance(segment.get('market_sentiment'), dict) and index == total_segments - 1:
            market_sentiment = segment['market_sentiment']
        if isinstance(segment.get('data_quality'), dict):
            warnings = segment['data_quality'].get('warnings') if isinstance(segment['data_quality'].get('warnings'), list) else []
            data_quality_warnings.extend([f'segment_{index}:{w}' for w in warnings if isinstance(w, str)])
        if isinstance(segment.get('summary'), dict) and index == total_segments - 1:
            last_summary = segment['summary']
    if trend_state:
        merged['trend_state'] = trend_state
    if rolling_metrics:
        merged['rolling_metrics'] = rolling_metrics
    if support_zones:
        merged['support_resistance_zones'] = support_zones
    if pattern_candidates:
        merged['pattern_candidates'] = pattern_candidates
    if overlay_annotations:
        merged['overlay_annotations'] = overlay_annotations
    if multi_index_resonance:
        merged['multi_index_resonance'] = multi_index_resonance
    if market_sentiment:
        merged['market_sentiment'] = market_sentiment
    if last_summary:
        merged['summary'] = last_summary
    merged['data_quality'] = {
        'segments': total_segments,
        'warnings': data_quality_warnings,
    }
    return merged


def run_application_analysis_horizon(
    target_type: str,
    symbol: str,
    name: str,
    adjust: str = 'qfq',
    days: int = TARGET_HORIZON_DAYS,
    segments: int = TARGET_HORIZON_SEGMENTS,
) -> dict:
    import time

    horizon_input = build_horizon_analysis_input(target_type, symbol, name, adjust, days, segments)
    horizon_meta = horizon_input.get('horizon') or {}
    actual_segments = len(horizon_input.get('daily_segments') or [])
    prompt = _prompt_text()
    print(f'[ApplicationAnalysisHorizon] start target={target_type}/{symbol} days={horizon_meta.get("days")} segments={actual_segments} prompt_chars={len(prompt)}', flush=True)
    segment_results: list[dict] = []
    segment_inputs: list[dict] = []
    raw_keys_per_segment: list[list[str] | None] = []
    errors: list[str] = []
    started = time.monotonic()
    for segment_index in range(actual_segments):
        segment_input = _build_segment_input(horizon_input, segment_index)
        segment_inputs.append(segment_input)
        try:
            raw_response, _ = _call_minimax_json(prompt, segment_input, target_type, symbol, f'{name}#seg{segment_index + 1}')
            raw_keys = list(raw_response.keys()) if isinstance(raw_response, dict) else None
            raw_keys_per_segment.append(raw_keys)
            sanitized = _sanitize_annotations(raw_response)
            analysis_result = sanitized.get('analysis_result') if isinstance(sanitized, dict) else None
            if isinstance(analysis_result, dict):
                segment_results.append(analysis_result)
                print(f'[ApplicationAnalysisHorizon] segment {segment_index + 1}/{actual_segments} ok keys={list(analysis_result.keys())}', flush=True)
            else:
                segment_results.append({})
                errors.append(f'segment_{segment_index + 1}:no analysis_result')
        except Exception as exc:
            print(f'[ApplicationAnalysisHorizon] segment {segment_index + 1}/{actual_segments} error: {exc}', flush=True)
            segment_results.append({})
            raw_keys_per_segment.append(None)
            errors.append(f'segment_{segment_index + 1}:{exc}')
    merged = _merge_segment_results(segment_results)
    merged['target'] = horizon_input.get('target')
    merged['horizon'] = horizon_meta
    if errors:
        merged.setdefault('data_quality', {})['errors'] = errors
    elapsed = int(time.monotonic() - started)
    print(f'[ApplicationAnalysisHorizon] done elapsed={elapsed}s segments={actual_segments} merged_keys={list(merged.keys())}', flush=True)
    return {
        'analysis_input': horizon_input,
        'analysis_result': merged,
        'raw_result': {'merged': merged, 'segment_results': segment_results, 'errors': errors},
        'raw_root_keys': ['analysis_result'],
        'segments': {
            'count': actual_segments,
            'inputs': segment_inputs,
            'raw_keys_per_segment': raw_keys_per_segment,
        },
        'horizon': horizon_meta,
        'elapsed_seconds': elapsed,
    }


def run_application_analysis_target(target: dict) -> dict:
    target_type = str(target.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(target.get('symbol') or '').strip() or '000001'
    name = str(target.get('name') or symbol).strip() or symbol
    adjust = str(target.get('adjust') or 'qfq').strip() or 'qfq'
    days = int(target.get('horizon_days') or TARGET_HORIZON_DAYS)
    segments = int(target.get('horizon_segments') or TARGET_HORIZON_SEGMENTS)
    return run_application_analysis_horizon(target_type, symbol, name, adjust, days, segments)


# --- 最近 30 日 K 入口：用于按日持久化 short_term_trend / current_situation ---


def build_recent30_analysis_input(target_type: str, symbol: str, name: str, adjust: str = 'qfq') -> dict:
    payload = build_application_analysis_input(target_type, symbol, name, adjust)
    days = APPLICATION_ANALYSIS_RECENT30_DAYS
    bars = payload.setdefault('bars', {})
    daily = bars.get('daily') or {}
    daily_items = daily.get('items') or []
    if isinstance(daily_items, list):
        daily['items'] = _keep_tail(daily_items, days)
        daily['total_count'] = len(daily_items)
        daily['recent_window_days'] = days
    weekly = bars.get('weekly') or {}
    weekly_items = weekly.get('items') or []
    if isinstance(weekly_items, list):
        weekly['items'] = _keep_tail(weekly_items, 12)
    payload['analysis_windows'] = [3, 5, 10, 20]
    payload.setdefault('enabled_features', {})['short_term_trend_assessment'] = True
    payload.setdefault('enabled_features', {})['current_situation_assessment'] = True
    payload['recent_window'] = {
        'kind': 'recent_30_daily_k',
        'days': days,
    }
    return payload


def run_application_analysis_recent30(target_type: str, symbol: str, name: str, adjust: str = 'qfq') -> dict:
    analysis_input = build_recent30_analysis_input(target_type, symbol, name, adjust)
    prompt = _short_term_daily_prompt_text()
    print(f'[ApplicationAnalysisRecent30] target={target_type}/{symbol} prompt_chars={len(prompt)}', flush=True)
    raw_response, dump_paths = _call_minimax_json(prompt, analysis_input, target_type, symbol, name)
    raw_keys = list(raw_response.keys()) if isinstance(raw_response, dict) else None
    print(f'[ApplicationAnalysisRecent30] raw keys={raw_keys}', flush=True)
    sanitized = _sanitize_short_term_only(raw_response)
    return {
        'analysis_input': analysis_input,
        'analysis_result': sanitized.get('analysis_result'),
        'raw_result': sanitized,
        'raw_root_keys': raw_keys,
        'dump_paths': dump_paths,
        'recent_window': analysis_input.get('recent_window'),
    }


def _short_term_daily_prompt_text() -> str:
    raw = Path(SHORT_TERM_DAILY_PROMPT_FILE).read_text(encoding='utf-8').strip()
    enforcement = (
        "\n\n【输出硬约束】\n"
        "- 你只能输出一个 JSON 对象，必须以 `{` 开头、以 `}` 结束。\n"
        "- 严禁输出 <think>、<analysis>、```、Markdown、解释、问候、总结。\n"
        "- 严禁使用 reasoning_content、reasoning_details、audio_content 等非 JSON 文本。\n"
        "- 根字段只能出现 analysis_result；target / data_quality 必须放在 analysis_result 内部。\n"
        "- analysis_result 必须同时包含 short_term_trend 与 current_situation 两个字段，二者都可以是对象。\n"
        "- 不得输出 overlay_annotations、support_resistance_zones、pattern_candidates、"
        "market_sentiment、multi_index_resonance、trend_state、rolling_metrics、summary 等其他字段。\n"
        "- 不得新增本 prompt 未定义的字段。\n"
    )
    return raw + enforcement


def _sanitize_short_term_only(result: dict) -> dict:
    if not isinstance(result, dict):
        return {'analysis_result': {'short_term_trend': None, 'current_situation': None, 'data_quality': {'warnings': ['AI 返回不是 JSON 对象']}}}

    if isinstance(result.get('analysis_result'), dict):
        analysis_result = result['analysis_result']
    else:
        # 兼容 AI 把字段直接铺在根上的情况
        analysis_result = {}
        for key in [
            'target',
            'data_quality',
            'short_term_trend',
            'current_situation',
        ]:
            if key in result:
                analysis_result[key] = result[key]
        if not analysis_result:
            return {'analysis_result': {'short_term_trend': None, 'current_situation': None, 'data_quality': {'warnings': ['AI 未返回 analysis_result']}}}
        result['analysis_result'] = analysis_result

    # 过滤掉 prompt 之外的多余字段，避免对前端造成误解；缺失字段占位为 None
    cleaned: dict = {key: analysis_result[key] for key in ('target', 'data_quality') if key in analysis_result}
    cleaned['short_term_trend'] = analysis_result.get('short_term_trend') if isinstance(analysis_result.get('short_term_trend'), dict) else None
    cleaned['current_situation'] = analysis_result.get('current_situation') if isinstance(analysis_result.get('current_situation'), dict) else None

    data_quality = cleaned.get('data_quality')
    if not isinstance(data_quality, dict):
        data_quality = {}
        cleaned['data_quality'] = data_quality
    warnings = data_quality.get('warnings')
    if not isinstance(warnings, list):
        warnings = []
        data_quality['warnings'] = warnings

    if not isinstance(cleaned.get('short_term_trend'), dict):
        warnings.append('AI 未返回 short_term_trend')
    if not isinstance(cleaned.get('current_situation'), dict):
        warnings.append('AI 未返回 current_situation')

    result['analysis_result'] = cleaned
    return result


def _atomic_write_json_local(path: Path, data: Any) -> None:
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


def _daily_snapshot_target_dir(target: dict[str, Any]) -> Path:
    target_type = str(target.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(target.get('symbol') or '').strip() or 'unknown'
    return APPLICATION_ANALYSIS_DAILY_SNAPSHOT_DIR / f'{target_type}-{symbol}'


def _today_key() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _iso_now() -> str:
    return datetime.now().isoformat()


def write_daily_snapshot(target: dict[str, Any], payload: dict[str, Any], date_key: str | None = None) -> dict[str, Any]:
    directory = _daily_snapshot_target_dir(target)
    directory.mkdir(parents=True, exist_ok=True)
    key = (date_key or _today_key()).strip() or _today_key()
    snapshot_path = directory / f'{key}.json'
    analysis_result = payload.get('analysis_result') or {}
    short_term = analysis_result.get('short_term_trend') if isinstance(analysis_result, dict) else None
    situation = analysis_result.get('current_situation') if isinstance(analysis_result, dict) else None
    serialized = {
        'target': {
            'id': target.get('id'),
            'target_type': target.get('target_type'),
            'symbol': target.get('symbol'),
            'name': target.get('name'),
            'adjust': target.get('adjust'),
        },
        'date': key,
        'updated_at': _iso_now(),
        'recent_window': payload.get('recent_window'),
        'short_term_trend': short_term,
        'current_situation': situation,
        'summary': analysis_result.get('summary') if isinstance(analysis_result, dict) else None,
        'analysis_result': analysis_result,
    }
    _atomic_write_json_local(snapshot_path, serialized)
    return {'snapshot_path': str(snapshot_path), 'date': key}


def list_daily_snapshots(target: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    directory = _daily_snapshot_target_dir(target)
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
            'date': path.stem,
            'size_bytes': stat.st_size,
            'updated_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return out


def read_daily_snapshot(target: dict[str, Any], date_key: str) -> dict[str, Any] | None:
    directory = _daily_snapshot_target_dir(target)
    snapshot_path = directory / f'{date_key}.json'
    if not snapshot_path.exists():
        return None
    return read_json_file(snapshot_path, None)


def run_application_analysis_recent30_and_snapshot(target: dict[str, Any], date_key: str | None = None) -> dict[str, Any]:
    target_type = str(target.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(target.get('symbol') or '').strip() or '000001'
    name = str(target.get('name') or symbol).strip() or symbol
    adjust = str(target.get('adjust') or 'qfq').strip() or 'qfq'
    payload = run_application_analysis_recent30(target_type, symbol, name, adjust)
    paths = write_daily_snapshot(target, payload, date_key=date_key)
    return {
        'analysis_result': payload.get('analysis_result'),
        'short_term_trend': (payload.get('analysis_result') or {}).get('short_term_trend'),
        'current_situation': (payload.get('analysis_result') or {}).get('current_situation'),
        'snapshot_path': paths.get('snapshot_path'),
        'date': paths.get('date'),
    }
