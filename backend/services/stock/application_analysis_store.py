r"""Application Analysis store backed by Postgres.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\application-analysis-target-postgres-migration.md`

后续如果调整 targets 持久化、target/self-selected 双向同步、result/history/recent30 持久化、
结果文件命名规则或 API 兼容层，
请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.config.database import session_scope
from backend.config.settings import (
    APPLICATION_ANALYSIS_HISTORY_FOLDER,
    APPLICATION_ANALYSIS_RESULTS_FOLDER,
    APPLICATION_ANALYSIS_SCHEDULER_FILE,
)
from backend.repositories.stock.application_analysis_result_repo import ApplicationAnalysisResultRepository
from backend.services.stock.application_analysis_target_sync_service import ApplicationAnalysisTargetSyncService
from backend.utils.json_io import read_json_file

DEFAULT_HORIZON = {"days": 120, "segments": 4, "monthly_keep": 12, "weekly_keep": 26}

_lock_scheduler = threading.Lock()


def _ensure_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")


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


def _normalize_targets(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    horizon = data.get("horizon") if isinstance(data.get("horizon"), dict) else {}
    horizon_out = {**DEFAULT_HORIZON, **horizon}
    try:
        days = int(horizon_out.get("days") or DEFAULT_HORIZON["days"])
    except (TypeError, ValueError):
        days = DEFAULT_HORIZON["days"]
    try:
        segments = int(horizon_out.get("segments") or DEFAULT_HORIZON["segments"])
    except (TypeError, ValueError):
        segments = DEFAULT_HORIZON["segments"]
    try:
        monthly_keep = int(horizon_out.get("monthly_keep") or DEFAULT_HORIZON["monthly_keep"])
    except (TypeError, ValueError):
        monthly_keep = DEFAULT_HORIZON["monthly_keep"]
    try:
        weekly_keep = int(horizon_out.get("weekly_keep") or DEFAULT_HORIZON["weekly_keep"])
    except (TypeError, ValueError):
        weekly_keep = DEFAULT_HORIZON["weekly_keep"]
    horizon_out = {
        "days": max(30, days),
        "segments": max(1, segments),
        "monthly_keep": max(1, monthly_keep),
        "weekly_keep": max(1, weekly_keep),
    }
    items_raw = data.get("items") if isinstance(data.get("items"), list) else []
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(items_raw):
        if not isinstance(raw_item, dict):
            continue
        target_type = str(raw_item.get("target_type") or "stock").strip() or "stock"
        symbol = str(raw_item.get("symbol") or "").strip().upper() or f"item-{index + 1}"
        name = str(raw_item.get("name") or symbol).strip() or symbol
        try:
            interval_value = int(raw_item.get("interval_minutes") or 60)
        except (TypeError, ValueError):
            interval_value = 60
        interval_value = max(5, interval_value)
        item_id = str(raw_item.get("id") or f"{target_type}-{symbol}").strip().lower() or f"{target_type}-{symbol}".lower()
        tags = raw_item.get("tags") if isinstance(raw_item.get("tags"), list) else []
        items.append(
            {
                "id": item_id,
                "target_type": target_type,
                "symbol": symbol,
                "market": str(raw_item.get("market") or "").strip().upper() or None,
                "name": name,
                "adjust": str(raw_item.get("adjust") or "qfq").strip() or "qfq",
                "enabled": bool(raw_item.get("enabled", True)),
                "interval_minutes": interval_value,
                "tags": [str(tag) for tag in tags if str(tag).strip()],
            }
        )
    return {
        "version": 1,
        "updated_at": data.get("updated_at") or None,
        "horizon": horizon_out,
        "items": items,
    }


def load_targets() -> dict[str, Any]:
    _ensure_env()
    with session_scope() as db:
        service = ApplicationAnalysisTargetSyncService(db)
        payload = service.load_config()
    payload["horizon"] = {**DEFAULT_HORIZON, **(payload.get("horizon") or {})}
    return payload


def save_targets(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_env()
    normalized = _normalize_targets(payload)
    normalized["updated_at"] = datetime.now().isoformat()
    with session_scope() as db:
        service = ApplicationAnalysisTargetSyncService(db)
        saved = service.save_config(normalized)
    saved["horizon"] = {**DEFAULT_HORIZON, **(saved.get("horizon") or {})}
    return saved


def _ensure_result_bootstrapped(targets: list[dict[str, Any]]) -> None:
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        repo.ensure_bootstrapped(targets)


def result_filename(item: dict[str, Any]) -> str:
    target_type = str(item.get("target_type") or "stock").strip() or "stock"
    symbol = str(item.get("symbol") or "").strip() or "unknown"
    return f"{target_type}-{symbol}.json"


def result_path(item: dict[str, Any]) -> Path:
    return APPLICATION_ANALYSIS_RESULTS_FOLDER / result_filename(item)


def history_dir(item: dict[str, Any]) -> Path:
    target_type = str(item.get("target_type") or "stock").strip() or "stock"
    symbol = str(item.get("symbol") or "").strip() or "unknown"
    return APPLICATION_ANALYSIS_HISTORY_FOLDER / f"{target_type}-{symbol}"


def write_result(item: dict[str, Any], payload: dict[str, Any], source_kind: str = "runtime") -> dict[str, Any]:
    _ensure_env()
    _ensure_result_bootstrapped([item])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.write_result(item, payload, source_kind=source_kind)


def read_result(item: dict[str, Any]) -> dict[str, Any] | None:
    _ensure_env()
    _ensure_result_bootstrapped([item])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.read_result(item)


def list_result_files() -> list[dict[str, Any]]:
    _ensure_env()
    targets = load_targets().get("items", [])
    _ensure_result_bootstrapped(targets)
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.list_result_files()


def load_scheduler_status() -> dict[str, Any]:
    with _lock_scheduler:
        raw = read_json_file(APPLICATION_ANALYSIS_SCHEDULER_FILE, None)
    if not raw:
        return {
            "running": False,
            "started_at": None,
            "last_tick_at": None,
            "last_run": None,
            "runs": 0,
        }
    return raw


def save_scheduler_status(status: dict[str, Any]) -> None:
    with _lock_scheduler:
        _atomic_write_json(APPLICATION_ANALYSIS_SCHEDULER_FILE, status)


def list_history(item: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    _ensure_env()
    _ensure_result_bootstrapped([item])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.list_history(item, limit=limit)


def save_daily_snapshot_payload(target: dict[str, Any], payload: dict[str, Any], date_key: str) -> dict[str, str]:
    _ensure_env()
    _ensure_result_bootstrapped([target])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.save_daily_snapshot(target, date_key, payload, source_kind="runtime")


def list_daily_snapshot_files(target: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    _ensure_env()
    _ensure_result_bootstrapped([target])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.list_daily_snapshots(target, limit=limit)


def read_daily_snapshot_payload(target: dict[str, Any], date_key: str) -> dict[str, Any] | None:
    _ensure_env()
    _ensure_result_bootstrapped([target])
    with session_scope() as db:
        repo = ApplicationAnalysisResultRepository(db)
        return repo.read_daily_snapshot(target, date_key)


def touch_updated_marker() -> None:
    pass
