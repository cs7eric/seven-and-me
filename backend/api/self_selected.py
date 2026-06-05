"""自选股（self-selected）REST API。

由 ``/stock-overview/self-selected`` 页面使用：
- group：用户自己创建的分类（如「长线持仓」「短线观察」），tab 形式渲染
- item：分类下的具体股票
- 全部数据落盘到 ``reference/self-selected/{groups,items}.json``

所有写操作走 :mod:`backend.repositories.stock.self_selected_repo`（带锁、原子写）。
"""
from __future__ import annotations

import traceback
from typing import Any

from flask import Blueprint, jsonify, request

from backend.repositories.stock import self_selected_repo

self_selected_bp = Blueprint("self_selected", __name__)


# ---------------------------------------------------------------------------
# group
# ---------------------------------------------------------------------------


@self_selected_bp.route("/api/self-selected/groups", methods=["GET"])
def list_groups():
    try:
        items = self_selected_repo.list_groups()
        return jsonify({"ok": True, "items": items, "count": len(items)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/groups", methods=["POST"])
def create_group():
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        group = self_selected_repo.create_group(payload)
        return jsonify({"ok": True, "item": group})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/groups/<group_id>", methods=["PUT"])
def update_group(group_id: str):
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        group = self_selected_repo.update_group(group_id, payload)
        if group is None:
            return jsonify({"ok": False, "error": f"group {group_id} not found"}), 404
        return jsonify({"ok": True, "item": group})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/groups/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    try:
        ok = self_selected_repo.delete_group(group_id)
        if not ok:
            return jsonify({"ok": False, "error": f"group {group_id} not found"}), 404
        return jsonify({"ok": True, "group_id": group_id})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# item
# ---------------------------------------------------------------------------


@self_selected_bp.route("/api/self-selected/items", methods=["GET"])
def list_items():
    try:
        group_id = request.args.get("group_id") or None
        items = self_selected_repo.list_items(group_id=group_id)
        return jsonify({"ok": True, "items": items, "count": len(items), "group_id": group_id})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/items", methods=["POST"])
def create_item():
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        item = self_selected_repo.create_item(payload)
        return jsonify({"ok": True, "item": item})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/items/<item_id>", methods=["PUT"])
def update_item(item_id: str):
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    try:
        item = self_selected_repo.update_item(item_id, payload)
        if item is None:
            return jsonify({"ok": False, "error": f"item {item_id} not found"}), 404
        return jsonify({"ok": True, "item": item})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@self_selected_bp.route("/api/self-selected/items/<item_id>", methods=["DELETE"])
def delete_item(item_id: str):
    try:
        ok = self_selected_repo.delete_item(item_id)
        if not ok:
            return jsonify({"ok": False, "error": f"item {item_id} not found"}), 404
        return jsonify({"ok": True, "item_id": item_id})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500
