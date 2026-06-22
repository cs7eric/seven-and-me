"""自选股（self-selected）REST API.

由 ``/stock-overview/self-selected`` 页面使用:
- group: 用户自己创建的分类（如「长线持仓」「短线观察」），tab 形式渲染
- item: 分类下的具体股票
- 全部数据落盘到 Postgres, 走 :mod:`backend.repositories.stock.self_selected_db_repo`

接口路径 / method / 响应字段全部跟旧 JSON 版对齐, 前端不用改.

约定:
  - API 层 = 唯一允许 ``session_scope()`` 的地方 (事务边界 = 一个 HTTP 请求)
  - repository 不做 commit / rollback
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from backend.config.database import session_scope
from backend.services.stock.self_selected_service import SelfSelectedService

logger = logging.getLogger(__name__)

self_selected_bp = Blueprint("self_selected", __name__)


def _err(msg: str, code: int = 500):
    return jsonify({"ok": False, "error": msg}), code


# ---------------------------------------------------------------------------
# group
# ---------------------------------------------------------------------------

@self_selected_bp.route("/api/self-selected/groups", methods=["GET"])
def list_groups():
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            items = service.list_groups()
        return jsonify({"ok": True, "items": items, "count": len(items)})
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_groups failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/groups", methods=["POST"])
def create_group():
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            group = service.create_group(payload)
        return jsonify({"ok": True, "item": group})
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_group failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/groups/<group_id>", methods=["PUT"])
def update_group(group_id: str):
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            group = service.update_group(group_id, payload)
        if group is None:
            return _err(f"group {group_id} not found", 404)
        return jsonify({"ok": True, "item": group})
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_group failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/groups/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            ok = service.delete_group(group_id)
        if not ok:
            return _err(f"group {group_id} not found", 404)
        return jsonify({"ok": True, "group_id": group_id})
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete_group failed")
        return _err(str(exc), 500)


# ---------------------------------------------------------------------------
# item
# ---------------------------------------------------------------------------

@self_selected_bp.route("/api/self-selected/items", methods=["GET"])
def list_items():
    group_id = request.args.get("group_id") or None
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            items = service.list_items(group_id=group_id)
        return jsonify({
            "ok": True,
            "items": items,
            "count": len(items),
            "group_id": group_id,
        })
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_items failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/items", methods=["POST"])
def create_item():
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            item = service.create_item(payload)
        return jsonify({"ok": True, "item": item})
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_item failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/items/<item_id>", methods=["PUT"])
def update_item(item_id: str):
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            item = service.update_item(item_id, payload)
        if item is None:
            return _err(f"item {item_id} not found", 404)
        return jsonify({"ok": True, "item": item})
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_item failed")
        return _err(str(exc), 500)


@self_selected_bp.route("/api/self-selected/items/<item_id>", methods=["DELETE"])
def delete_item(item_id: str):
    try:
        with session_scope() as db:
            service = SelfSelectedService(db)
            ok = service.delete_item(item_id)
        if not ok:
            return _err(f"item {item_id} not found", 404)
        return jsonify({"ok": True, "item_id": item_id})
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete_item failed")
        return _err(str(exc), 500)
