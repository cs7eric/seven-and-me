"""自选股（self-selected）数据访问层。

- groups.json: 所有分类（group）
- items.json: 所有自选股（item），通过 ``group_id`` 关联到 group
- 删除 group 时**级联删除**其下所有 item
- 写操作都用 :func:`backend.utils.json_io.write_json_file`（原子写）
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from backend.config.settings import SELF_SELECTED_GROUPS_FILE, SELF_SELECTED_ITEMS_FILE
from backend.utils.json_io import read_json_file, write_json_file

_write_lock = threading.Lock()

_GROUP_DEFAULTS = {"version": 1, "groups": []}
_ITEM_DEFAULTS = {"version": 1, "items": []}


def _now() -> str:
    return datetime.now().isoformat()


def _new_id(prefix: str) -> str:
    """短 id：``ss-<prefix>-<ms timestamp>-<rand>``。人类可读。"""
    import random

    rand = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
    return f"ss-{prefix}-{int(datetime.now().timestamp() * 1000)}-{rand}"


# ---------------------------------------------------------------------------
# group
# ---------------------------------------------------------------------------


def _load_groups() -> list[dict[str, Any]]:
    payload = read_json_file(SELF_SELECTED_GROUPS_FILE, _GROUP_DEFAULTS)
    return payload.get("groups", [])


def _save_groups(groups: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "groups": groups, "updated_at": _now()}
    write_json_file(SELF_SELECTED_GROUPS_FILE, payload)


def list_groups() -> list[dict[str, Any]]:
    groups = _load_groups()
    return sorted(groups, key=lambda g: (g.get("sort_order", 0), g.get("created_at", "")))


def get_group(group_id: str) -> dict[str, Any] | None:
    for g in _load_groups():
        if g.get("id") == group_id:
            return g
    return None


def create_group(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("group name is required")

    now = _now()
    with _write_lock:
        groups = _load_groups()
        max_sort = max((g.get("sort_order", 0) for g in groups), default=0)
        group = {
            "id": payload.get("id") or _new_id("grp"),
            "name": name,
            "description": (payload.get("description") or "").strip() or None,
            "color": (payload.get("color") or "blue").strip() or "blue",
            "sort_order": int(payload.get("sort_order", max_sort + 1)),
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        }
        groups.append(group)
        _save_groups(groups)
    return group


def update_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    now = _now()
    with _write_lock:
        groups = _load_groups()
        idx = next((i for i, g in enumerate(groups) if g.get("id") == group_id), None)
        if idx is None:
            return None
        g = groups[idx]
        for key in ("name", "description", "color"):
            if key in payload:
                value = payload.get(key)
                if value is not None and isinstance(value, str):
                    value = value.strip()
                g[key] = value if value else None
        if "sort_order" in payload:
            try:
                g["sort_order"] = int(payload["sort_order"])
            except (TypeError, ValueError):
                pass
        g["updated_at"] = now
        _save_groups(groups)
    return g


def delete_group(group_id: str) -> bool:
    """删除 group 并级联删除其下所有 item。"""
    with _write_lock:
        groups = _load_groups()
        new_groups = [g for g in groups if g.get("id") != group_id]
        if len(new_groups) == len(groups):
            return False
        _save_groups(new_groups)
        # 级联删 item
        items = _load_items_raw()
        new_items = [it for it in items if it.get("group_id") != group_id]
        if len(new_items) != len(items):
            _save_items_raw(new_items)
    return True


# ---------------------------------------------------------------------------
# item
# ---------------------------------------------------------------------------


def _load_items_raw() -> list[dict[str, Any]]:
    payload = read_json_file(SELF_SELECTED_ITEMS_FILE, _ITEM_DEFAULTS)
    return payload.get("items", [])


def _save_items_raw(items: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "items": items, "updated_at": _now()}
    write_json_file(SELF_SELECTED_ITEMS_FILE, payload)


def list_items(group_id: str | None = None) -> list[dict[str, Any]]:
    items = _load_items_raw()
    if group_id:
        items = [it for it in items if it.get("group_id") == group_id]
    return sorted(items, key=lambda it: (it.get("sort_order", 0), it.get("created_at", "")))


def get_item(item_id: str) -> dict[str, Any] | None:
    for it in _load_items_raw():
        if it.get("id") == item_id:
            return it
    return None


def create_item(payload: dict[str, Any]) -> dict[str, Any]:
    group_id = (payload.get("group_id") or "").strip()
    symbol = (payload.get("symbol") or "").strip()
    if not group_id:
        raise ValueError("group_id is required")
    if not symbol:
        raise ValueError("symbol is required")

    with _write_lock:
        if get_group(group_id) is None:
            raise ValueError(f"group {group_id} not found")
        items = _load_items_raw()
        max_sort = max(
            (it.get("sort_order", 0) for it in items if it.get("group_id") == group_id),
            default=0,
        )
        now = _now()
        item = {
            "id": payload.get("id") or _new_id("itm"),
            "group_id": group_id,
            "symbol": symbol,
            "market": (payload.get("market") or "").strip().upper() or None,
            "name": (payload.get("name") or "").strip() or None,
            "notes": (payload.get("notes") or "").strip() or None,
            "sort_order": int(payload.get("sort_order", max_sort + 1)),
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        }
        items.append(item)
        _save_items_raw(items)
    return item


def update_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    now = _now()
    with _write_lock:
        items = _load_items_raw()
        idx = next((i for i, it in enumerate(items) if it.get("id") == item_id), None)
        if idx is None:
            return None
        it = items[idx]
        for key in ("symbol", "market", "name", "notes", "group_id"):
            if key in payload:
                value = payload.get(key)
                if value is not None and isinstance(value, str):
                    value = value.strip()
                if key == "market" and value:
                    value = value.upper()
                it[key] = value if value else None
        if "sort_order" in payload:
            try:
                it["sort_order"] = int(payload["sort_order"])
            except (TypeError, ValueError):
                pass
        it["updated_at"] = now
        _save_items_raw(items)
    return it


def delete_item(item_id: str) -> bool:
    with _write_lock:
        items = _load_items_raw()
        new_items = [it for it in items if it.get("id") != item_id]
        if len(new_items) == len(items):
            return False
        _save_items_raw(new_items)
    return True
