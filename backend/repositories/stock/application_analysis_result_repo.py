r"""Application Analysis result/history/daily snapshot repository.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\application-analysis-target-postgres-migration.md`

后续如果调整 Application Analysis result/history/recent30 的表结构、导入规则、
兼容字段或前端元信息返回，请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from backend.config.settings import (
    APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER,
    APPLICATION_ANALYSIS_HISTORY_FOLDER,
    APPLICATION_ANALYSIS_RESULTS_FOLDER,
)
from backend.models.application_analysis import (
    ApplicationAnalysisDailySnapshot,
    ApplicationAnalysisResultCurrent,
    ApplicationAnalysisResultHistory,
    ApplicationAnalysisTarget,
)
from backend.utils.json_io import read_json_file


def _now() -> datetime:
    return datetime.utcnow()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_trade_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_history_key_as_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if text.endswith(".json"):
        text = text[:-5]
    try:
        return datetime.strptime(text, "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def _target_payload(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": target.get("id"),
        "target_type": target.get("target_type"),
        "symbol": target.get("symbol"),
        "name": target.get("name"),
        "adjust": target.get("adjust"),
        "tags": list(target.get("tags") or []),
    }


def _result_payload(target: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": _target_payload(target),
        "updated_at": payload.get("updated_at") or _now().isoformat(),
        "analysis_input": payload.get("analysis_input"),
        "analysis_result": payload.get("analysis_result"),
        "raw_result": payload.get("raw_result"),
        "raw_root_keys": payload.get("raw_root_keys"),
        "dump_paths": payload.get("dump_paths"),
        "segments": payload.get("segments"),
        "horizon": payload.get("horizon"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
    }


class ApplicationAnalysisResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def _alive_targets(self) -> Select[tuple[ApplicationAnalysisTarget]]:
        return select(ApplicationAnalysisTarget).where(ApplicationAnalysisTarget.deleted_at.is_(None))

    def _alive_current(self) -> Select[tuple[ApplicationAnalysisResultCurrent]]:
        return select(ApplicationAnalysisResultCurrent).where(ApplicationAnalysisResultCurrent.deleted_at.is_(None))

    def _alive_history(self) -> Select[tuple[ApplicationAnalysisResultHistory]]:
        return select(ApplicationAnalysisResultHistory).where(ApplicationAnalysisResultHistory.deleted_at.is_(None))

    def _alive_daily(self) -> Select[tuple[ApplicationAnalysisDailySnapshot]]:
        return select(ApplicationAnalysisDailySnapshot).where(ApplicationAnalysisDailySnapshot.deleted_at.is_(None))

    def ensure_bootstrapped(self, targets: list[dict[str, Any]]) -> None:
        current_count = self.db.scalar(
            select(func.count()).select_from(ApplicationAnalysisResultCurrent).where(ApplicationAnalysisResultCurrent.deleted_at.is_(None))
        ) or 0
        history_count = self.db.scalar(
            select(func.count()).select_from(ApplicationAnalysisResultHistory).where(ApplicationAnalysisResultHistory.deleted_at.is_(None))
        ) or 0
        daily_count = self.db.scalar(
            select(func.count()).select_from(ApplicationAnalysisDailySnapshot).where(ApplicationAnalysisDailySnapshot.deleted_at.is_(None))
        ) or 0
        if current_count == 0 or history_count == 0:
            self._bootstrap_legacy_results(targets)
        if daily_count == 0:
            self._bootstrap_legacy_daily_snapshots(targets)

    def _resolve_target_entity(self, target_key: str) -> ApplicationAnalysisTarget | None:
        return self.db.scalar(self._alive_targets().where(ApplicationAnalysisTarget.target_key == str(target_key).lower()))

    def _upsert_current(
        self,
        target: dict[str, Any],
        payload: dict[str, Any],
        *,
        source_kind: str = "runtime",
        analysis_run_at: datetime | None = None,
    ) -> ApplicationAnalysisResultCurrent:
        target_key = str(target.get("id") or "").lower()
        if not target_key:
            raise ValueError("target id is required for current result")
        row = self.db.scalar(self._alive_current().where(ApplicationAnalysisResultCurrent.target_key == target_key))
        if row is None:
            row = ApplicationAnalysisResultCurrent(target_key=target_key)
            self.db.add(row)
        target_entity = self._resolve_target_entity(target_key)
        row.target_id = target_entity.id if target_entity is not None else None
        row.status = "success"
        row.analysis_run_at = analysis_run_at or _parse_datetime(payload.get("updated_at")) or _now()
        row.payload = deepcopy(payload)
        row.remark = source_kind
        self.db.flush()
        return row

    def _upsert_history(
        self,
        target: dict[str, Any],
        payload: dict[str, Any],
        *,
        history_key: str,
        source_kind: str = "runtime",
        analysis_run_at: datetime | None = None,
    ) -> ApplicationAnalysisResultHistory:
        target_key = str(target.get("id") or "").lower()
        if not target_key:
            raise ValueError("target id is required for history result")
        row = self.db.scalar(
            self._alive_history().where(
                ApplicationAnalysisResultHistory.target_key == target_key,
                ApplicationAnalysisResultHistory.history_key == history_key,
            )
        )
        if row is None:
            row = ApplicationAnalysisResultHistory(target_key=target_key, history_key=history_key)
            self.db.add(row)
        target_entity = self._resolve_target_entity(target_key)
        row.target_id = target_entity.id if target_entity is not None else None
        row.source_kind = source_kind
        row.analysis_run_at = analysis_run_at or _parse_datetime(payload.get("updated_at")) or _parse_history_key_as_datetime(history_key) or _now()
        row.payload = deepcopy(payload)
        row.remark = source_kind
        self.db.flush()
        return row

    def write_result(self, target: dict[str, Any], payload: dict[str, Any], *, source_kind: str = "runtime") -> dict[str, str]:
        serialized = _result_payload(target, payload)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        history_key = f"{timestamp}.json"
        self._upsert_current(target, serialized, source_kind=source_kind)
        self._upsert_history(target, serialized, history_key=history_key, source_kind=source_kind)
        return {
            "result_path": str(APPLICATION_ANALYSIS_RESULTS_FOLDER / f"{target.get('id')}.json"),
            "history_path": str(APPLICATION_ANALYSIS_HISTORY_FOLDER / str(target.get("id") or "unknown") / history_key),
        }

    def read_result(self, target: dict[str, Any]) -> dict[str, Any] | None:
        target_key = str(target.get("id") or "").lower()
        if not target_key:
            return None
        row = self.db.scalar(self._alive_current().where(ApplicationAnalysisResultCurrent.target_key == target_key))
        if row is None:
            return None
        return deepcopy(row.payload or {})

    def list_result_files(self) -> list[dict[str, Any]]:
        stmt = self._alive_current().order_by(ApplicationAnalysisResultCurrent.analysis_run_at.desc())
        out: list[dict[str, Any]] = []
        for row in self.db.scalars(stmt).all():
            payload = row.payload or {}
            filename = f"{row.target_key}.json"
            out.append(
                {
                    "filename": filename,
                    "path": str(APPLICATION_ANALYSIS_RESULTS_FOLDER / filename),
                    "size_bytes": len(str(payload)),
                    "updated_at": (
                        _parse_datetime(payload.get("updated_at")) or row.analysis_run_at or row.updated_at or _now()
                    ).isoformat(),
                }
            )
        return out

    def list_history(self, target: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        target_key = str(target.get("id") or "").lower()
        if not target_key:
            return []
        stmt = (
            self._alive_history()
            .where(ApplicationAnalysisResultHistory.target_key == target_key)
            .order_by(ApplicationAnalysisResultHistory.analysis_run_at.desc(), ApplicationAnalysisResultHistory.created_at.desc())
        )
        out: list[dict[str, Any]] = []
        for row in self.db.scalars(stmt).all()[: max(1, limit)]:
            out.append(
                {
                    "filename": row.history_key,
                    "path": str(APPLICATION_ANALYSIS_HISTORY_FOLDER / target_key / row.history_key),
                    "updated_at": (row.analysis_run_at or row.created_at or _now()).isoformat(),
                }
            )
        return out

    def save_daily_snapshot(
        self,
        target: dict[str, Any],
        trade_date: str,
        payload: dict[str, Any],
        *,
        source_kind: str = "runtime",
    ) -> dict[str, str]:
        target_key = str(target.get("id") or "").lower()
        trade_date_value = _parse_trade_date(trade_date)
        if not target_key or trade_date_value is None:
            raise ValueError("target id and valid trade_date are required for daily snapshot")
        row = self.db.scalar(
            self._alive_daily().where(
                ApplicationAnalysisDailySnapshot.target_key == target_key,
                ApplicationAnalysisDailySnapshot.trade_date == trade_date_value,
                ApplicationAnalysisDailySnapshot.snapshot_kind == "recent30",
            )
        )
        if row is None:
            row = ApplicationAnalysisDailySnapshot(
                target_key=target_key,
                trade_date=trade_date_value,
                snapshot_kind="recent30",
            )
            self.db.add(row)
        target_entity = self._resolve_target_entity(target_key)
        row.target_id = target_entity.id if target_entity is not None else None
        row.payload = deepcopy(payload)
        row.remark = source_kind
        self.db.flush()
        return {
            "snapshot_path": str(APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER / target_key / f"{trade_date}.json"),
            "date": trade_date,
        }

    def list_daily_snapshots(self, target: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        target_key = str(target.get("id") or "").lower()
        if not target_key:
            return []
        stmt = (
            self._alive_daily()
            .where(
                ApplicationAnalysisDailySnapshot.target_key == target_key,
                ApplicationAnalysisDailySnapshot.snapshot_kind == "recent30",
            )
            .order_by(ApplicationAnalysisDailySnapshot.trade_date.desc(), ApplicationAnalysisDailySnapshot.updated_at.desc())
        )
        out: list[dict[str, Any]] = []
        for row in self.db.scalars(stmt).all()[: max(1, limit)]:
            filename = f"{row.trade_date.isoformat()}.json"
            payload = row.payload or {}
            out.append(
                {
                    "filename": filename,
                    "path": str(APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER / target_key / filename),
                    "date": row.trade_date.isoformat(),
                    "size_bytes": len(str(payload)),
                    "updated_at": (_parse_datetime(payload.get("updated_at")) or row.updated_at or _now()).isoformat(),
                }
            )
        return out

    def read_daily_snapshot(self, target: dict[str, Any], trade_date: str) -> dict[str, Any] | None:
        target_key = str(target.get("id") or "").lower()
        trade_date_value = _parse_trade_date(trade_date)
        if not target_key or trade_date_value is None:
            return None
        row = self.db.scalar(
            self._alive_daily().where(
                ApplicationAnalysisDailySnapshot.target_key == target_key,
                ApplicationAnalysisDailySnapshot.trade_date == trade_date_value,
                ApplicationAnalysisDailySnapshot.snapshot_kind == "recent30",
            )
        )
        if row is None:
            return None
        return deepcopy(row.payload or {})

    def _bootstrap_legacy_results(self, targets: list[dict[str, Any]]) -> None:
        for target in targets:
            target_key = str(target.get("id") or "").lower()
            if not target_key:
                continue
            result_path = APPLICATION_ANALYSIS_RESULTS_FOLDER / f"{target_key}.json"
            result_payload = read_json_file(result_path, None)
            if isinstance(result_payload, dict):
                self._upsert_current(
                    target,
                    result_payload,
                    source_kind="bootstrap",
                    analysis_run_at=_parse_datetime(result_payload.get("updated_at")) or _now(),
                )
            history_dir = APPLICATION_ANALYSIS_HISTORY_FOLDER / target_key
            if not history_dir.exists():
                continue
            for path in sorted(history_dir.glob("*.json")):
                payload = read_json_file(path, None)
                if not isinstance(payload, dict):
                    continue
                self._upsert_history(
                    target,
                    payload,
                    history_key=path.name,
                    source_kind="bootstrap",
                    analysis_run_at=_parse_datetime(payload.get("updated_at")) or _parse_history_key_as_datetime(path.name) or _now(),
                )
        self.db.flush()

    def _bootstrap_legacy_daily_snapshots(self, targets: list[dict[str, Any]]) -> None:
        for target in targets:
            target_key = str(target.get("id") or "").lower()
            if not target_key:
                continue
            directory = APPLICATION_ANALYSIS_DAILY_SNAPSHOT_FOLDER / target_key
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                payload = read_json_file(path, None)
                if not isinstance(payload, dict):
                    continue
                trade_date = _parse_trade_date(path.stem)
                if trade_date is None:
                    continue
                row = self.db.scalar(
                    self._alive_daily().where(
                        ApplicationAnalysisDailySnapshot.target_key == target_key,
                        ApplicationAnalysisDailySnapshot.trade_date == trade_date,
                        ApplicationAnalysisDailySnapshot.snapshot_kind == "recent30",
                    )
                )
                if row is None:
                    row = ApplicationAnalysisDailySnapshot(
                        target_key=target_key,
                        trade_date=trade_date,
                        snapshot_kind="recent30",
                    )
                    self.db.add(row)
                target_entity = self._resolve_target_entity(target_key)
                row.target_id = target_entity.id if target_entity is not None else None
                row.payload = deepcopy(payload)
                row.remark = "bootstrap"
        self.db.flush()


__all__ = ["ApplicationAnalysisResultRepository"]
