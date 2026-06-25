from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config.settings import APPLICATION_ANALYSIS_AUCTION_FOLDER, BASE_DIR
from backend.services.stock.feature_summary import build_stock_feature_summary
from backend.utils.json_io import read_json_file


AUCTION_ANALYSIS_PROMPT_FILE = BASE_DIR / "prompt" / "auction_analysis.md"
AUCTION_ANALYSIS_DUMP_DIR = Path(BASE_DIR) / "runtime" / "auction-analysis-dumps"
AUCTION_ANALYSIS_MODEL = os.getenv("MINIMAX_AUCTION_ANALYSIS_MODEL") or os.getenv("MINIMAX_APPLICATION_ANALYSIS_MODEL") or os.getenv("MINIMAX_MODEL") or "MiniMax-M2.7"
AUCTION_ANALYSIS_TIMEOUT = int(os.getenv("MINIMAX_AUCTION_ANALYSIS_TIMEOUT") or os.getenv("MINIMAX_APPLICATION_ANALYSIS_TIMEOUT") or "600")
AUCTION_ANALYSIS_TEXT_CHUNK_CHARS = int(os.getenv("MINIMAX_AUCTION_ANALYSIS_TEXT_CHUNK_CHARS") or "120000")
AUCTION_ANALYSIS_MAX_INPUT_CHARS = int(os.getenv("MINIMAX_AUCTION_ANALYSIS_MAX_INPUT_CHARS") or "1000000")


def _beijing_today_key() -> str:
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")


def _target_key(target_type: str, symbol: str) -> str:
    return f"{(target_type or 'stock').strip() or 'stock'}-{(symbol or 'unknown').strip() or 'unknown'}"


def _auction_snapshot_dir(target_type: str, symbol: str) -> Path:
    return APPLICATION_ANALYSIS_AUCTION_FOLDER / _target_key(target_type, symbol)


def _auction_snapshot_path(target_type: str, symbol: str, date_key: str | None = None) -> Path:
    key = (date_key or _beijing_today_key()).strip() or _beijing_today_key()
    return _auction_snapshot_dir(target_type, symbol) / f"{key}.json"


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _prompt_text() -> str:
    raw = AUCTION_ANALYSIS_PROMPT_FILE.read_text(encoding="utf-8").strip()
    enforcement = (
        "\n\n【输出硬约束补充】\n"
        "- 你只能输出一个 JSON 对象，且该对象必须以字符 `{` 开头并以 `}` 结束。\n"
        "- 根字段只能出现 analysis_result。\n"
        "- 严禁输出 <think>、<analysis>、```、Markdown、解释、问候、总结、reasoning_content。\n"
        "- 严禁输出投资建议、买卖点、仓位、目标价、止损止盈。\n"
        "- 严禁使用“主力、庄家、操盘”等无法由输入证明的归因词。\n"
        "- 缺失数据用 null、unavailable 或 warnings 表示，不得编造。\n"
    )
    return raw + enforcement


def _strip_think_blocks(text: str) -> str:
    if "<think>" not in text and "</think>" not in text:
        return text
    import re

    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def _first_balanced_json(text: str) -> str:
    if not text:
        return ""
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def _extract_ai_content(payload: dict[str, Any]) -> str:
    candidates: list[str] = []

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 6 or value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("```"):
                candidates.append(text)
            return
        if isinstance(value, dict):
            for key in ["content", "text", "reply", "output", "answer"]:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip())
            for key in ["message", "messages", "delta", "choices", "data"]:
                if key in value:
                    collect(value.get(key), depth + 1)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)

    collect(payload)
    if not candidates:
        return ""
    raw = max(candidates, key=len)
    raw = _strip_think_blocks(raw)
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json\n", "", 1).replace("JSON\n", "", 1).strip()
    return _first_balanced_json(raw) or raw


def _chunk_input_text(analysis_input: dict[str, Any]) -> list[str]:
    serialized = json.dumps(analysis_input, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= AUCTION_ANALYSIS_TEXT_CHUNK_CHARS:
        return [serialized]
    header = {
        "chunk_warnings": [
            f"analysis_input split into multiple user messages because the per-message char limit was {AUCTION_ANALYSIS_TEXT_CHUNK_CHARS}.",
            f"original total chars: {len(serialized)}.",
            "Concatenate all chunks in order to reconstruct the original JSON object.",
        ],
    }
    chunks = [json.dumps(header, ensure_ascii=False, separators=(",", ":"))]
    remaining = serialized
    while len(remaining) > AUCTION_ANALYSIS_TEXT_CHUNK_CHARS:
        chunks.append(remaining[:AUCTION_ANALYSIS_TEXT_CHUNK_CHARS])
        remaining = remaining[AUCTION_ANALYSIS_TEXT_CHUNK_CHARS:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _dump_ai_payload(target_type: str, symbol: str, name: str, raw: dict[str, Any], content: str) -> dict[str, str]:
    AUCTION_ANALYSIS_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_target = f"{target_type or 'na'}-{symbol or 'na'}-{name or 'na'}".replace("/", "_").replace("\\", "_")
    raw_path = AUCTION_ANALYSIS_DUMP_DIR / f"{timestamp}-{safe_target}-raw.json"
    content_path = AUCTION_ANALYSIS_DUMP_DIR / f"{timestamp}-{safe_target}-content.txt"

    def write_atomic(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(value)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    write_atomic(raw_path, json.dumps(raw, ensure_ascii=False, indent=2))
    write_atomic(content_path, content or "")
    return {"raw": str(raw_path), "content": str(content_path)}


def _minimax_error_preview(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    safe_payload = {}
    for key in ["base_resp", "id", "model", "created", "usage"]:
        if key in payload:
            safe_payload[key] = payload.get(key)
    if not safe_payload:
        safe_payload = {key: payload.get(key) for key in list(payload.keys())[:8]}
    return json.dumps(safe_payload, ensure_ascii=False)[:800]


def call_auction_analysis_ai(system_prompt: str, analysis_input: dict[str, Any], *, target_type: str, symbol: str, name: str) -> tuple[dict[str, Any], dict[str, str]]:
    import time
    from backend.services.ai_provider_service import ai_provider_registry

    polisher = ai_provider_registry.get_polisher()
    ai_router = ai_provider_registry.get_ai_router()
    log_prefix = "[AuctionAnalysis]"
    chunks = _chunk_input_text(analysis_input)
    print(f"{log_prefix} start model={AUCTION_ANALYSIS_MODEL} chunks={len(chunks)} chars={[len(c) for c in chunks]} prompt_chars={len(system_prompt)}", flush=True)

    user_messages: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks):
        label = f"竞价分析输入片段 {index + 1}/{len(chunks)}，请按顺序拼接：" if len(chunks) > 1 else "竞价分析输入 JSON："
        user_messages.append({"role": "user", "name": "User", "content": f"{label}\n{chunk}"})
    user_messages.append({
        "role": "user",
        "name": "User",
        "content": (
            f"请阅读上面的 {len(chunks)} 条 user 消息，按顺序拼成完整 JSON 后，"
            "严格按系统 prompt 输出唯一 JSON 对象。根字段只能出现 analysis_result。"
        ),
    })

    messages = [{"role": "system", "content": system_prompt, "name": "MiniMax AI"}, *user_messages]
    started = time.monotonic()
    try:
        ai_response = ai_router.chat_completion(
            capability="auction_analysis",
            messages=messages,
            fallback_model=AUCTION_ANALYSIS_MODEL,
            fallback_base_url=polisher.BASE_URL,
            fallback_timeout=AUCTION_ANALYSIS_TIMEOUT,
            stream=False,
            temperature=0.15,
        )
    except ValueError:
        raise

    elapsed = int(time.monotonic() - started)
    print(f"{log_prefix} response elapsed={elapsed}s", flush=True)

    raw = ai_response.raw
    content = (ai_response.content or _extract_ai_content(raw)).strip()
    dump_paths = _dump_ai_payload(target_type, symbol, name, raw, content)
    if not content:
        raise ValueError(f"Auction Analysis AI 返回为空，响应摘要: {_minimax_error_preview(raw)}")

    try:
        parsed = polisher._parse_json_object(content)
    except Exception as exc:
        raise ValueError(f"Auction Analysis AI JSON 解析失败: {exc}; 内容预览: {content[:800]}") from exc
    return parsed, dump_paths


def _ensure_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _sanitize_result(result: Any, analysis_input: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("analysis_result"), dict):
        analysis_result = result["analysis_result"]
    elif isinstance(result, dict):
        analysis_result = result
        result = {"analysis_result": analysis_result}
    else:
        result = {"analysis_result": {}}
        analysis_result = result["analysis_result"]

    target = analysis_input.get("target") if isinstance(analysis_input.get("target"), dict) else {}
    analysis_result["target"] = {
        "target_type": analysis_result.get("target", {}).get("target_type") if isinstance(analysis_result.get("target"), dict) else target.get("target_type"),
        "symbol": analysis_result.get("target", {}).get("symbol") if isinstance(analysis_result.get("target"), dict) else target.get("symbol"),
        "name": analysis_result.get("target", {}).get("name") if isinstance(analysis_result.get("target"), dict) else target.get("name"),
    }

    data_quality = analysis_result.get("data_quality")
    if not isinstance(data_quality, dict):
        data_quality = {}
        analysis_result["data_quality"] = data_quality
    warnings = _ensure_list(data_quality.get("warnings"))
    input_warnings = _ensure_list((analysis_input.get("data_quality") or {}).get("warnings") if isinstance(analysis_input.get("data_quality"), dict) else [])
    for warning in input_warnings:
        if warning not in warnings:
            warnings.append(warning)
    data_quality["warnings"] = warnings
    if not isinstance(data_quality.get("missing_or_weak_dimensions"), list):
        data_quality["missing_or_weak_dimensions"] = []
    if not isinstance(data_quality.get("confidence"), (int, float)):
        data_quality["confidence"] = 60 if not warnings else 45

    result["analysis_result"] = analysis_result
    return result


def build_auction_analysis_input(target_type: str, symbol: str, name: str, adjust: str = "qfq", max_chars: int = AUCTION_ANALYSIS_MAX_INPUT_CHARS) -> dict[str, Any]:
    return build_stock_feature_summary(
        target_type=target_type,
        symbol=symbol,
        name=name,
        adjust=adjust,
        max_chars=max_chars,
    )


def run_auction_ai_analysis(target_type: str, symbol: str, name: str, adjust: str = "qfq", max_chars: int = AUCTION_ANALYSIS_MAX_INPUT_CHARS) -> dict[str, Any]:
    analysis_input = build_auction_analysis_input(target_type, symbol, name, adjust, max_chars)
    prompt = _prompt_text()
    raw_response, dump_paths = call_auction_analysis_ai(
        prompt,
        analysis_input,
        target_type=target_type,
        symbol=symbol,
        name=name,
    )
    sanitized = _sanitize_result(raw_response, analysis_input)
    return {
        "analysis_input": analysis_input,
        "analysis_result": sanitized.get("analysis_result"),
        "raw_result": sanitized,
        "raw_root_keys": list(raw_response.keys()) if isinstance(raw_response, dict) else None,
        "dump_paths": dump_paths,
    }


def write_auction_analysis_snapshot(target: dict[str, Any], payload: dict[str, Any], date_key: str | None = None) -> dict[str, Any]:
    target_type = str(target.get("target_type") or "stock").strip() or "stock"
    symbol = str(target.get("symbol") or "").strip() or "unknown"
    key = (date_key or _beijing_today_key()).strip() or _beijing_today_key()
    snapshot_path = _auction_snapshot_path(target_type, symbol, key)
    serialized = {
        "target": {
            "id": target.get("id"),
            "target_type": target_type,
            "symbol": symbol,
            "name": target.get("name") or symbol,
            "adjust": target.get("adjust") or "qfq",
            "tags": target.get("tags") or [],
        },
        "date": key,
        "updated_at": datetime.now().isoformat(),
        "analysis_input": payload.get("analysis_input"),
        "analysis_result": payload.get("analysis_result"),
        "raw_result": payload.get("raw_result"),
        "raw_root_keys": payload.get("raw_root_keys"),
        "dump_paths": payload.get("dump_paths"),
    }
    _atomic_write_json(snapshot_path, serialized)
    return {"snapshot_path": str(snapshot_path), "date": key, "updated": True}


def read_auction_analysis_snapshot(target_type: str, symbol: str, date_key: str | None = None) -> dict[str, Any] | None:
    return read_json_file(_auction_snapshot_path(target_type, symbol, date_key), None)


def list_auction_analysis_snapshots(target_type: str, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
    directory = _auction_snapshot_dir(target_type, symbol)
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"), key=lambda path: path.name, reverse=True)
    items: list[dict[str, Any]] = []
    for path in files[: max(1, limit)]:
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append({
            "filename": path.name,
            "path": str(path),
            "date": path.stem,
            "size_bytes": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return items


def run_auction_ai_analysis_target(target: dict[str, Any], date_key: str | None = None) -> dict[str, Any]:
    target_type = str(target.get("target_type") or "stock").strip() or "stock"
    symbol = str(target.get("symbol") or "").strip() or "000001"
    name = str(target.get("name") or symbol).strip() or symbol
    adjust = str(target.get("adjust") or "qfq").strip() or "qfq"
    payload = run_auction_ai_analysis(target_type, symbol, name, adjust, AUCTION_ANALYSIS_MAX_INPUT_CHARS)
    paths = write_auction_analysis_snapshot(target, payload, date_key=date_key)
    return {
        **payload,
        "snapshot_path": paths.get("snapshot_path"),
        "date": paths.get("date"),
        "updated": paths.get("updated"),
    }
