r"""Application Analysis target Postgres repository.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\application-analysis-target-postgres-migration.md`

后续如果调整 targets 表结构、字段映射、双向同步规则或 self-selected target 分组行为，
请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from backend.config.settings import APPLICATION_ANALYSIS_TARGETS_FILE
from backend.models.application_analysis import ApplicationAnalysisConfig, ApplicationAnalysisTarget
from backend.models.self_selected import SelfSelectedGroup, SelfSelectedItem
from backend.utils.json_io import read_json_file


_UUID_NAMESPACE = UUID("9f0a6b46-a83f-43ca-8123-646b949cb0bf")
_TARGET_GROUP_NAME = "target"


def _legacy_uuid(prefix: str, legacy_key: str) -> UUID:
    return uuid5(_UUID_NAMESPACE, f"{prefix}:{legacy_key}")


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.utcnow()


def _target_key(target_type: str, symbol: str) -> str:
    return f"{target_type}-{symbol}".lower()


def _item_to_target_dict(item: ApplicationAnalysisTarget) -> dict[str, Any]:
    return {
        "id": item.target_key,
        "target_type": item.target_type,
        "symbol": item.symbol,
        "name": item.name,
        "adjust": item.adjust,
        "enabled": item.enabled,
        "interval_minutes": item.interval_minutes,
        "tags": list(item.tags or []),
        "last_updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "last_result_path": None,
        "market": item.market,
    }


class ApplicationAnalysisTargetRepository:
    def __init__(self, db: Session):
        self.db = db

    def _alive_targets(self) -> Select[tuple[ApplicationAnalysisTarget]]:
        return select(ApplicationAnalysisTarget).where(ApplicationAnalysisTarget.deleted_at.is_(None))

    def _alive_groups(self) -> Select[tuple[SelfSelectedGroup]]:
        return select(SelfSelectedGroup).where(SelfSelectedGroup.deleted_at.is_(None))

    def _alive_items(self) -> Select[tuple[SelfSelectedItem]]:
        return select(SelfSelectedItem).where(SelfSelectedItem.deleted_at.is_(None))

    def ensure_bootstrapped(self) -> None:
        count = self.db.scalar(
            select(func.count()).select_from(ApplicationAnalysisTarget).where(ApplicationAnalysisTarget.deleted_at.is_(None))
        )
        self.ensure_target_group()
        self.ensure_default_config()
        if count and count > 0:
            self.ensure_self_selected_links()
            return
        self._bootstrap_from_legacy_json()

    def ensure_default_config(self) -> ApplicationAnalysisConfig:
        config = self.db.scalar(
            select(ApplicationAnalysisConfig).where(
                ApplicationAnalysisConfig.config_key == "default",
                ApplicationAnalysisConfig.deleted_at.is_(None),
            )
        )
        if config is not None:
            return config
        config = ApplicationAnalysisConfig(config_key="default")
        self.db.add(config)
        self.db.flush()
        return config

    def ensure_target_group(self) -> SelfSelectedGroup:
        group = self.db.scalar(
            self._alive_groups().where(
                func.lower(SelfSelectedGroup.name) == _TARGET_GROUP_NAME,
            )
        )
        if group is not None:
            if group.list_kind != "system":
                group.list_kind = "system"
            return group
        group = SelfSelectedGroup(
            legacy_key="system-target",
            name=_TARGET_GROUP_NAME,
            description="system mirrored from application analysis targets",
            color="amber",
            list_kind="system",
            status="active",
            sort_order=-100,
            remark="system target group for application analysis sync",
        )
        self.db.add(group)
        self.db.flush()
        return group

    def _bootstrap_from_legacy_json(self) -> None:
        raw = read_json_file(APPLICATION_ANALYSIS_TARGETS_FILE, None)
        if not isinstance(raw, dict):
            return
        config = self.ensure_default_config()
        horizon = raw.get("horizon") if isinstance(raw.get("horizon"), dict) else {}
        config.horizon_days = max(30, int(horizon.get("days") or 120))
        config.horizon_segments = max(1, int(horizon.get("segments") or 4))
        config.monthly_keep = max(1, int(horizon.get("monthly_keep") or 6))
        config.weekly_keep = max(1, int(horizon.get("weekly_keep") or 12))

        for index, item in enumerate(raw.get("items") or []):
            if not isinstance(item, dict):
                continue
            target_type = _strip(item.get("target_type")) or "stock"
            symbol = (_strip(item.get("symbol")) or "").upper()
            if not symbol:
                continue
            target_key = _target_key(target_type, symbol)
            existing = self.get_target_by_key(target_key)
            if existing is not None:
                continue
            target = ApplicationAnalysisTarget(
                id=_legacy_uuid("application-analysis-target", _strip(item.get("id")) or target_key),
                target_key=target_key,
                legacy_key=_strip(item.get("id")),
                symbol=symbol,
                market=_strip(item.get("market")),
                name=_strip(item.get("name")) or symbol,
                target_type=target_type,
                adjust=_strip(item.get("adjust")) or "qfq",
                enabled=bool(item.get("enabled", True)),
                interval_minutes=max(5, int(item.get("interval_minutes") or 60)),
                source_type="imported",
                status="active",
                sort_order=index + 1,
                tags=[str(tag) for tag in (item.get("tags") or []) if str(tag).strip()],
                extra={"bootstrappedFrom": str(APPLICATION_ANALYSIS_TARGETS_FILE)},
                remark="bootstrapped from legacy application-analysis targets.json",
                created_at=_parse_datetime(raw.get("updated_at")) or _now(),
                updated_at=_parse_datetime(raw.get("updated_at")) or _now(),
            )
            self.db.add(target)
            self.db.flush()
            self._upsert_self_selected_target_item(target)
        self.db.flush()

    def ensure_self_selected_links(self) -> None:
        targets = self.db.scalars(
            self._alive_targets().order_by(ApplicationAnalysisTarget.sort_order.asc(), ApplicationAnalysisTarget.created_at.asc())
        ).all()
        for target in targets:
            self._upsert_self_selected_target_item(target)
        self.db.flush()

    def load_config_payload(self) -> dict[str, Any]:
        config = self.ensure_default_config()
        return {
            "version": 1,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            "horizon": {
                "days": config.horizon_days,
                "segments": config.horizon_segments,
                "monthly_keep": config.monthly_keep,
                "weekly_keep": config.weekly_keep,
            },
            "items": self.list_targets(),
        }

    def save_config_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self.ensure_default_config()
        horizon = payload.get("horizon") if isinstance(payload.get("horizon"), dict) else {}
        config.horizon_days = max(30, int(horizon.get("days") or config.horizon_days or 120))
        config.horizon_segments = max(1, int(horizon.get("segments") or config.horizon_segments or 4))
        config.monthly_keep = max(1, int(horizon.get("monthly_keep") or config.monthly_keep or 6))
        config.weekly_keep = max(1, int(horizon.get("weekly_keep") or config.weekly_keep or 12))
        config.updated_at = _now()

        incoming = payload.get("items") if isinstance(payload.get("items"), list) else []
        alive_by_key = {target.target_key: target for target in self.db.scalars(self._alive_targets()).all()}
        seen_keys: set[str] = set()

        for index, raw in enumerate(incoming):
            if not isinstance(raw, dict):
                continue
            target_type = _strip(raw.get("target_type")) or "stock"
            symbol = (_strip(raw.get("symbol")) or "").upper()
            if not symbol:
                continue
            target_key = _target_key(target_type, symbol)
            seen_keys.add(target_key)
            existing = alive_by_key.get(target_key)
            if existing is None:
                target = ApplicationAnalysisTarget(
                    target_key=target_key,
                    legacy_key=_strip(raw.get("id")) or target_key,
                    symbol=symbol,
                    market=_strip(raw.get("market")),
                    name=_strip(raw.get("name")) or symbol,
                    target_type=target_type,
                    adjust=_strip(raw.get("adjust")) or "qfq",
                    enabled=bool(raw.get("enabled", True)),
                    interval_minutes=max(5, int(raw.get("interval_minutes") or 60)),
                    source_type="manual",
                    status="active",
                    sort_order=index + 1,
                    tags=[str(tag) for tag in (raw.get("tags") or []) if str(tag).strip()],
                    extra={},
                )
                self.db.add(target)
                self.db.flush()
                self._upsert_self_selected_target_item(target)
                continue

            existing.market = _strip(raw.get("market")) or existing.market
            existing.name = _strip(raw.get("name")) or existing.name
            existing.adjust = _strip(raw.get("adjust")) or "qfq"
            existing.enabled = bool(raw.get("enabled", True))
            existing.interval_minutes = max(5, int(raw.get("interval_minutes") or 60))
            existing.sort_order = index + 1
            existing.tags = [str(tag) for tag in (raw.get("tags") or []) if str(tag).strip()]
            existing.updated_at = _now()
            self._upsert_self_selected_target_item(existing)

        for key, target in alive_by_key.items():
            if key in seen_keys:
                continue
            self.soft_delete_target(target)

        self.db.flush()
        return self.load_config_payload()

    def list_targets(self) -> list[dict[str, Any]]:
        stmt = self._alive_targets().order_by(ApplicationAnalysisTarget.sort_order.asc(), ApplicationAnalysisTarget.created_at.asc())
        return [_item_to_target_dict(item) for item in self.db.scalars(stmt).all()]

    def get_target_by_public_id(self, target_id: str) -> dict[str, Any] | None:
        target = self.get_target_by_key(target_id)
        return _item_to_target_dict(target) if target else None

    def get_target_entity_by_public_id(self, target_id: str) -> ApplicationAnalysisTarget | None:
        return self.get_target_by_key(target_id)

    def get_target_by_key(self, target_key: str) -> ApplicationAnalysisTarget | None:
        return self.db.scalar(
            self._alive_targets().where(ApplicationAnalysisTarget.target_key == str(target_key).lower())
        )

    def soft_delete_target(self, target: ApplicationAnalysisTarget) -> None:
        now = _now()
        target.deleted_at = now
        target.updated_at = now
        if target.self_selected_item_id:
            item = self.db.get(SelfSelectedItem, target.self_selected_item_id)
            if item is not None and item.deleted_at is None:
                item.deleted_at = now
                item.updated_at = now

    def sync_target_from_self_selected_item(self, item: SelfSelectedItem, group: SelfSelectedGroup) -> None:
        if group.name.lower() != _TARGET_GROUP_NAME:
            return
        target_type = item.target_type or "stock"
        symbol = (item.symbol or "").upper()
        if not symbol:
            return
        target_key = _target_key(target_type, symbol)
        target = self.get_target_by_key(target_key)
        if target is None:
            max_sort = self.db.scalar(
                select(ApplicationAnalysisTarget.sort_order)
                .where(ApplicationAnalysisTarget.deleted_at.is_(None))
                .order_by(ApplicationAnalysisTarget.sort_order.desc())
                .limit(1)
            ) or 0
            target = ApplicationAnalysisTarget(
                target_key=target_key,
                legacy_key=target_key,
                self_selected_item_id=item.id,
                symbol=symbol,
                market=item.market,
                name=item.name or symbol,
                target_type=target_type,
                adjust="qfq",
                enabled=True,
                interval_minutes=60,
                source_type="self_selected_sync",
                status="active",
                sort_order=max_sort + 1,
                tags=[],
                extra={"syncedFromSelfSelected": True},
                remark="created from self-selected target group",
            )
            self.db.add(target)
            self.db.flush()
        else:
            target.self_selected_item_id = item.id
            target.market = item.market or target.market
            target.name = item.name or target.name
            target.target_type = target_type
            target.updated_at = _now()

    def sync_target_delete_from_self_selected_item(self, item: SelfSelectedItem) -> None:
        target = self.db.scalar(
            self._alive_targets().where(ApplicationAnalysisTarget.self_selected_item_id == item.id)
        )
        if target is not None:
            self.soft_delete_target(target)

    def _upsert_self_selected_target_item(self, target: ApplicationAnalysisTarget) -> SelfSelectedItem:
        group = self.ensure_target_group()
        existing = None
        if target.self_selected_item_id:
            existing = self.db.get(SelfSelectedItem, target.self_selected_item_id)
            if existing is not None and existing.deleted_at is not None:
                existing = None
        if existing is None:
            existing = self.db.scalar(
                self._alive_items().where(
                    SelfSelectedItem.group_id == group.id,
                    SelfSelectedItem.symbol == target.symbol,
                )
            )
        if existing is None:
            item = SelfSelectedItem(
                legacy_key=f"application-target:{target.target_key}",
                group_id=group.id,
                symbol=target.symbol,
                market=target.market,
                name=target.name,
                notes=None,
                target_type=target.target_type,
                source_type="imported" if target.source_type == "imported" else "manual",
                status="active",
                sort_order=target.sort_order,
                extra={
                    "linkedApplicationAnalysisTargetKey": target.target_key,
                    "linkedApplicationAnalysisTargetId": str(target.id),
                },
                remark="mirrored from application analysis target",
            )
            self.db.add(item)
            self.db.flush()
            target.self_selected_item_id = item.id
            return item
        existing.market = target.market
        existing.name = target.name
        existing.target_type = target.target_type
        existing.sort_order = target.sort_order
        extra = dict(existing.extra or {})
        extra["linkedApplicationAnalysisTargetKey"] = target.target_key
        extra["linkedApplicationAnalysisTargetId"] = str(target.id)
        existing.extra = extra
        existing.updated_at = _now()
        target.self_selected_item_id = existing.id
        return existing


__all__ = ["ApplicationAnalysisTargetRepository", "_TARGET_GROUP_NAME"]
