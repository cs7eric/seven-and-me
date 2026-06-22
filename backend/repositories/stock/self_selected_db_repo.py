"""Self-Selected Postgres repository.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\self-selected-postgres-migration.md`
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from backend.models.self_selected import SelfSelectedGroup, SelfSelectedItem
from backend.repositories.stock import self_selected_repo as legacy_json_repo


_UUID_NAMESPACE = UUID("5e7a92e0-fcd5-4ceb-9504-6f6d6e9b9196")


def _parse_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{field_name} must be a valid uuid") from exc


def _legacy_uuid(prefix: str, legacy_key: str) -> UUID:
    return uuid5(_UUID_NAMESPACE, f"{prefix}:{legacy_key}")


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None


def _is_system_target_group(group: SelfSelectedGroup) -> bool:
    return (group.list_kind or "").lower() == "system" and (group.name or "").strip().lower() == "target"
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _group_to_dict(group: SelfSelectedGroup) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "color": group.color,
        "list_kind": group.list_kind,
        "status": group.status,
        "sort_order": group.sort_order,
        "created_at": _iso(group.created_at),
        "updated_at": _iso(group.updated_at),
    }


def _item_to_dict(item: SelfSelectedItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "group_id": str(item.group_id),
        "symbol": item.symbol,
        "market": item.market,
        "name": item.name,
        "notes": item.notes,
        "target_type": item.target_type,
        "source_type": item.source_type,
        "status": item.status,
        "sort_order": item.sort_order,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


class SelfSelectedRepository:
    def __init__(self, db: Session):
        self.db = db

    def ensure_bootstrapped(self) -> None:
        group_count = self.db.scalar(
            select(func.count()).select_from(SelfSelectedGroup).where(SelfSelectedGroup.deleted_at.is_(None))
        )
        if group_count and group_count > 0:
            return
        legacy_groups = legacy_json_repo.list_groups()
        legacy_items = legacy_json_repo.list_items()
        if not legacy_groups and not legacy_items:
            return
        for group in legacy_groups:
            legacy_key = _strip(group.get("id"))
            group_id = _legacy_uuid("group", legacy_key) if legacy_key else _legacy_uuid("group", _strip(group.get("name")) or "unnamed")
            existing = self.db.scalar(
                self._alive_groups().where(SelfSelectedGroup.legacy_key == legacy_key)
            ) if legacy_key else self.db.get(SelfSelectedGroup, group_id)
            if existing is not None:
                continue
            self.db.add(
                SelfSelectedGroup(
                    id=group_id,
                    legacy_key=legacy_key,
                    name=_strip(group.get("name")) or "Unnamed",
                    description=_strip(group.get("description")),
                    color=_strip(group.get("color")) or "blue",
                    list_kind="manual",
                    status="active",
                    sort_order=int(group.get("sort_order") or 0),
                    created_at=_parse_datetime(group.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(group.get("updated_at")) or datetime.utcnow(),
                    remark="bootstrapped from legacy JSON",
                )
            )
        self.db.flush()
        for item in legacy_items:
            legacy_key = _strip(item.get("id"))
            item_id = _legacy_uuid("item", legacy_key) if legacy_key else _legacy_uuid("item", f"{item.get('group_id')}:{item.get('symbol')}")
            group_legacy_key = _strip(item.get("group_id"))
            group_id = _legacy_uuid("group", group_legacy_key) if group_legacy_key else None
            existing = self.db.scalar(
                self._alive_items().where(SelfSelectedItem.legacy_key == legacy_key)
            ) if legacy_key else self.db.get(SelfSelectedItem, item_id)
            if existing is not None or group_id is None:
                continue
            self.db.add(
                SelfSelectedItem(
                    id=item_id,
                    legacy_key=legacy_key,
                    group_id=group_id,
                    symbol=(_strip(item.get("symbol")) or "").upper(),
                    market=(_strip(item.get("market")) or None),
                    name=_strip(item.get("name")),
                    notes=_strip(item.get("notes")),
                    target_type=_strip(item.get("target_type")) or "stock",
                    source_type="imported",
                    status="active",
                    sort_order=int(item.get("sort_order") or 0),
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                    remark="bootstrapped from legacy JSON",
                )
            )
        self.db.flush()

    def _alive_groups(self) -> Select[tuple[SelfSelectedGroup]]:
        return select(SelfSelectedGroup).where(SelfSelectedGroup.deleted_at.is_(None))

    def _alive_items(self) -> Select[tuple[SelfSelectedItem]]:
        return select(SelfSelectedItem).where(SelfSelectedItem.deleted_at.is_(None))

    def get_group_entity(self, group_id: str | UUID) -> SelfSelectedGroup | None:
        return self.db.get(SelfSelectedGroup, _parse_uuid(group_id, "group_id"))

    def get_item_entity(self, item_id: str | UUID) -> SelfSelectedItem | None:
        return self.db.get(SelfSelectedItem, _parse_uuid(item_id, "item_id"))

    def list_groups(self) -> list[dict[str, Any]]:
        stmt = self._alive_groups().order_by(SelfSelectedGroup.sort_order.asc(), SelfSelectedGroup.created_at.asc())
        return [_group_to_dict(group) for group in self.db.scalars(stmt).all()]

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _strip(payload.get("name"))
        if not name:
            raise ValueError("group name is required")
        max_sort = self.db.scalar(
            select(SelfSelectedGroup.sort_order)
            .where(SelfSelectedGroup.deleted_at.is_(None))
            .order_by(SelfSelectedGroup.sort_order.desc())
            .limit(1)
        ) or 0
        group = SelfSelectedGroup(
            name=name,
            description=_strip(payload.get("description")),
            color=_strip(payload.get("color")) or "blue",
            status="active",
            sort_order=int(payload.get("sort_order") or max_sort + 1),
        )
        self.db.add(group)
        self.db.flush()
        return _group_to_dict(group)

    def update_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        group = self.db.get(SelfSelectedGroup, _parse_uuid(group_id, "group_id"))
        if group is None or group.deleted_at is not None:
            return None
        if "name" in payload:
            name = _strip(payload.get("name"))
            if not name:
                raise ValueError("group name is required")
            group.name = name
        if "description" in payload:
            group.description = _strip(payload.get("description"))
        if "color" in payload:
            group.color = _strip(payload.get("color")) or "blue"
        if "sort_order" in payload:
            group.sort_order = int(payload.get("sort_order") or 0)
        if "status" in payload:
            status = _strip(payload.get("status")) or "active"
            if status not in {"active", "disabled"}:
                raise ValueError("status must be active or disabled")
            group.status = status
        self.db.execute(text("update app.self_selected_lists set updated_at = now() where id = :id"), {"id": group.id})
        self.db.flush()
        self.db.refresh(group)
        return _group_to_dict(group)

    def delete_group(self, group_id: str) -> bool:
        group_uuid = _parse_uuid(group_id, "group_id")
        group = self.db.get(SelfSelectedGroup, group_uuid)
        if group is None or group.deleted_at is not None:
            return False
        if _is_system_target_group(group):
            raise ValueError("system group target cannot be deleted")
        self.db.execute(
            text(
                """
                update app.self_selected_list_items
                set deleted_at = now(), updated_at = now()
                where list_id = :group_id and deleted_at is null
                """
            ),
            {"group_id": group_uuid},
        )
        group.deleted_at = datetime.now(group.created_at.tzinfo) if group.created_at and group.created_at.tzinfo else datetime.utcnow()
        self.db.execute(text("update app.self_selected_lists set updated_at = now() where id = :id"), {"id": group.id})
        self.db.flush()
        return True

    def list_items(self, group_id: str | None = None) -> list[dict[str, Any]]:
        stmt = self._alive_items()
        if group_id:
            stmt = stmt.where(SelfSelectedItem.group_id == _parse_uuid(group_id, "group_id"))
        stmt = stmt.order_by(SelfSelectedItem.sort_order.asc(), SelfSelectedItem.created_at.asc())
        return [_item_to_dict(item) for item in self.db.scalars(stmt).all()]

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        group_id = _strip(payload.get("group_id"))
        symbol = (_strip(payload.get("symbol")) or "").upper()
        if not group_id:
            raise ValueError("group_id is required")
        if not symbol:
            raise ValueError("symbol is required")
        group_uuid = _parse_uuid(group_id, "group_id")
        group = self.db.get(SelfSelectedGroup, group_uuid)
        if group is None or group.deleted_at is not None:
            raise ValueError(f"group {group_id} not found")
        existing = self.db.scalar(
            self._alive_items().where(
                SelfSelectedItem.group_id == group_uuid,
                SelfSelectedItem.symbol == symbol,
            )
        )
        if existing is not None:
            raise ValueError(f"symbol {symbol} already in group {group_id}")
        max_sort = self.db.scalar(
            select(SelfSelectedItem.sort_order)
            .where(SelfSelectedItem.deleted_at.is_(None), SelfSelectedItem.group_id == group_uuid)
            .order_by(SelfSelectedItem.sort_order.desc())
            .limit(1)
        ) or 0
        target_type = _strip(payload.get("target_type")) or "stock"
        if target_type not in {"stock", "hk_stock", "etf", "index", "other"}:
            raise ValueError("target_type is invalid")
        item = SelfSelectedItem(
            group_id=group_uuid,
            symbol=symbol,
            market=(_strip(payload.get("market")) or None),
            name=_strip(payload.get("name")),
            notes=_strip(payload.get("notes")),
            target_type=target_type,
            status="active",
            sort_order=int(payload.get("sort_order") or max_sort + 1),
        )
        self.db.add(item)
        self.db.flush()
        return _item_to_dict(item)

    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        item = self.db.get(SelfSelectedItem, _parse_uuid(item_id, "item_id"))
        if item is None or item.deleted_at is not None:
            return None
        new_group_uuid = item.group_id
        if "group_id" in payload:
            new_group_id = _strip(payload.get("group_id"))
            if not new_group_id:
                raise ValueError("group_id is required")
            new_group_uuid = _parse_uuid(new_group_id, "group_id")
            group = self.db.get(SelfSelectedGroup, new_group_uuid)
            if group is None or group.deleted_at is not None:
                raise ValueError(f"group {new_group_id} not found")
            item.group_id = new_group_uuid
        if "symbol" in payload:
            symbol = (_strip(payload.get("symbol")) or "").upper()
            if not symbol:
                raise ValueError("symbol is required")
            item.symbol = symbol
        duplicate = self.db.scalar(
            self._alive_items().where(
                SelfSelectedItem.group_id == new_group_uuid,
                SelfSelectedItem.symbol == item.symbol,
                SelfSelectedItem.id != item.id,
            )
        )
        if duplicate is not None:
            raise ValueError(f"symbol {item.symbol} already exists in target group")
        if "market" in payload:
            item.market = (_strip(payload.get("market")) or None)
        if "name" in payload:
            item.name = _strip(payload.get("name"))
        if "notes" in payload:
            item.notes = _strip(payload.get("notes"))
        if "target_type" in payload:
            target_type = _strip(payload.get("target_type")) or "stock"
            if target_type not in {"stock", "hk_stock", "etf", "index", "other"}:
                raise ValueError("target_type is invalid")
            item.target_type = target_type
        if "status" in payload:
            status = _strip(payload.get("status")) or "active"
            if status not in {"active", "disabled"}:
                raise ValueError("status must be active or disabled")
            item.status = status
        if "sort_order" in payload:
            item.sort_order = int(payload.get("sort_order") or 0)
        self.db.execute(text("update app.self_selected_list_items set updated_at = now() where id = :id"), {"id": item.id})
        self.db.flush()
        self.db.refresh(item)
        return _item_to_dict(item)

    def delete_item(self, item_id: str) -> bool:
        item = self.db.get(SelfSelectedItem, _parse_uuid(item_id, "item_id"))
        if item is None or item.deleted_at is not None:
            return False
        item.deleted_at = datetime.now(item.created_at.tzinfo) if item.created_at and item.created_at.tzinfo else datetime.utcnow()
        self.db.execute(text("update app.self_selected_list_items set updated_at = now() where id = :id"), {"id": item.id})
        self.db.flush()
        return True


__all__ = ["SelfSelectedRepository"]
