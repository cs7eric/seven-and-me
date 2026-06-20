"""自选股 DB 仓库 (Postgres + SQLAlchemy).

跟 :mod:`backend.repositories.stock.self_selected_repo` (JSON 版) 接口对齐,
但是返回的字段更"裸": datetime 直接转 ISO 字符串, None 透传.

约定 (跟 CLAUDE.md / 项目分层一致):
  - repository 不做 commit: 事务边界 = ``session_scope()``
  - repository 不做 HTTP / jsonify / 业务校验: 那层在 API
  - repository 不 import backend.api.*
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.self_selected import SelfSelectedGroup, SelfSelectedItem


# ---------------------------------------------------------------------------
# 序列化 helpers
# ---------------------------------------------------------------------------

def _group_to_dict(group: SelfSelectedGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "color": group.color,
        "sort_order": group.sort_order,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
    }


def _item_to_dict(item: SelfSelectedItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "group_id": item.group_id,
        "symbol": item.symbol,
        "market": item.market,
        "name": item.name,
        "notes": item.notes,
        "target_type": item.target_type,
        "sort_order": item.sort_order,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class SelfSelectedRepository:
    """自选股 DB CRUD. 一个实例绑一个 Session, 一次性用."""

    def __init__(self, db: Session):
        self.db = db

    # ---- group ----

    def list_groups(self) -> list[dict[str, Any]]:
        stmt = (
            select(SelfSelectedGroup)
            .order_by(
                SelfSelectedGroup.sort_order.asc(),
                SelfSelectedGroup.created_at.asc(),
            )
        )
        return [_group_to_dict(g) for g in self.db.scalars(stmt).all()]

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        g = self.db.get(SelfSelectedGroup, group_id)
        return _group_to_dict(g) if g else None

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _strip(payload.get("name"))
        if not name:
            raise ValueError("group name is required")

        # sort_order 默认 = max+1 (插到末尾)
        max_sort = self.db.scalar(
            select(SelfSelectedGroup.sort_order).order_by(
                SelfSelectedGroup.sort_order.desc()
            ).limit(1)
        ) or 0

        group = SelfSelectedGroup(
            name=name,
            description=_strip(payload.get("description")),
            color=_strip(payload.get("color")) or "blue",
            sort_order=int(payload.get("sort_order") or max_sort + 1),
        )
        self.db.add(group)
        self.db.flush()
        return _group_to_dict(group)

    def update_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        g = self.db.get(SelfSelectedGroup, group_id)
        if g is None:
            return None
        if "name" in payload:
            new_name = _strip(payload.get("name"))
            if new_name:
                g.name = new_name
        if "description" in payload:
            g.description = _strip(payload.get("description"))
        if "color" in payload:
            color = _strip(payload.get("color"))
            if color:
                g.color = color
        if "sort_order" in payload:
            try:
                g.sort_order = int(payload["sort_order"])
            except (TypeError, ValueError):
                pass
        self.db.flush()
        return _group_to_dict(g)

    def delete_group(self, group_id: str) -> bool:
        g = self.db.get(SelfSelectedGroup, group_id)
        if g is None:
            return False
        self.db.delete(g)  # cascade 删 items (ondelete=CASCADE)
        self.db.flush()
        return True

    # ---- item ----

    def list_items(self, group_id: str | None = None) -> list[dict[str, Any]]:
        stmt = select(SelfSelectedItem)
        if group_id:
            stmt = stmt.where(SelfSelectedItem.group_id == group_id)
        stmt = stmt.order_by(
            SelfSelectedItem.sort_order.asc(),
            SelfSelectedItem.created_at.asc(),
        )
        return [_item_to_dict(it) for it in self.db.scalars(stmt).all()]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        it = self.db.get(SelfSelectedItem, item_id)
        return _item_to_dict(it) if it else None

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        group_id = _strip(payload.get("group_id"))
        symbol = _strip(payload.get("symbol"))
        if not group_id:
            raise ValueError("group_id is required")
        if not symbol:
            raise ValueError("symbol is required")

        # group 必须存在
        if self.db.get(SelfSelectedGroup, group_id) is None:
            raise ValueError(f"group {group_id} not found")

        # 唯一约束保护 (group_id, symbol) — 已存在就拒
        existing = self.db.scalar(
            select(SelfSelectedItem).where(
                SelfSelectedItem.group_id == group_id,
                SelfSelectedItem.symbol == symbol,
            )
        )
        if existing is not None:
            raise ValueError(f"symbol {symbol} already in group {group_id}")

        # sort_order = 该 group 内 max+1
        max_sort = self.db.scalar(
            select(SelfSelectedItem.sort_order)
            .where(SelfSelectedItem.group_id == group_id)
            .order_by(SelfSelectedItem.sort_order.desc())
            .limit(1)
        ) or 0

        market = _strip(payload.get("market"))
        if market:
            market = market.upper()

        item = SelfSelectedItem(
            group_id=group_id,
            symbol=symbol,
            market=market,
            name=_strip(payload.get("name")),
            notes=_strip(payload.get("notes")),
            target_type=_strip(payload.get("target_type")) or "stock",
            sort_order=int(payload.get("sort_order") or max_sort + 1),
        )
        self.db.add(item)
        self.db.flush()
        return _item_to_dict(item)

    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        it = self.db.get(SelfSelectedItem, item_id)
        if it is None:
            return None

        if "symbol" in payload:
            new_symbol = _strip(payload.get("symbol"))
            if new_symbol:
                it.symbol = new_symbol
        if "market" in payload:
            market = _strip(payload.get("market"))
            if market:
                it.market = market.upper()
            else:
                it.market = None
        if "name" in payload:
            it.name = _strip(payload.get("name"))
        if "notes" in payload:
            it.notes = _strip(payload.get("notes"))
        if "group_id" in payload:
            new_group_id = _strip(payload.get("group_id"))
            if new_group_id and self.db.get(SelfSelectedGroup, new_group_id) is None:
                raise ValueError(f"group {new_group_id} not found")
            if new_group_id:
                it.group_id = new_group_id
        if "target_type" in payload:
            tt = _strip(payload.get("target_type"))
            if tt:
                it.target_type = tt
        if "sort_order" in payload:
            try:
                it.sort_order = int(payload["sort_order"])
            except (TypeError, ValueError):
                pass
        self.db.flush()
        return _item_to_dict(it)

    def delete_item(self, item_id: str) -> bool:
        it = self.db.get(SelfSelectedItem, item_id)
        if it is None:
            return False
        self.db.delete(it)
        self.db.flush()
        return True


__all__ = ["SelfSelectedRepository"]
