from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.config.database import session_scope
from backend.repositories.ai_provider_repo import AIProviderRepository

# AI Provider architecture docs:
#   design/backend/ai-provider.md
# Keep that document in sync when changing these endpoints or payload contracts.

ai_provider_bp = Blueprint("ai_provider", __name__)


@ai_provider_bp.route("/api/ai/capabilities")
def list_ai_capabilities():
    with session_scope() as db:
        return jsonify({"items": AIProviderRepository(db).list_capabilities()})


@ai_provider_bp.route("/api/ai/provider-types")
def list_ai_provider_types():
    with session_scope() as db:
        return jsonify({"items": AIProviderRepository(db).list_provider_types()})


@ai_provider_bp.route("/api/ai/providers")
def list_ai_providers():
    with session_scope() as db:
        return jsonify({"items": AIProviderRepository(db).list_providers()})


@ai_provider_bp.route("/api/ai/providers", methods=["POST"])
def create_ai_provider():
    payload = request.get_json() or {}
    if not str(payload.get("code") or "").strip():
        return jsonify({"error": "code is required"}), 400
    if not str(payload.get("name") or "").strip():
        return jsonify({"error": "name is required"}), 400
    with session_scope() as db:
        repo = AIProviderRepository(db)
        if repo.get_provider_by_code(str(payload.get("code")).strip()):
            return jsonify({"error": "provider code already exists"}), 409
        return jsonify(repo.create_provider(payload)), 201


@ai_provider_bp.route("/api/ai/providers/<provider_id>", methods=["PUT", "PATCH"])
def update_ai_provider(provider_id: str):
    payload = request.get_json() or {}
    with session_scope() as db:
        item = AIProviderRepository(db).update_provider(provider_id, payload)
        if not item:
            return jsonify({"error": "provider not found"}), 404
        return jsonify(item)


@ai_provider_bp.route("/api/ai/providers/<provider_id>", methods=["DELETE"])
def delete_ai_provider(provider_id: str):
    with session_scope() as db:
        deleted = AIProviderRepository(db).delete_provider(provider_id)
        if not deleted:
            return jsonify({"error": "provider not found"}), 404
        return jsonify({"ok": True, "id": provider_id})


@ai_provider_bp.route("/api/ai/bindings")
def list_ai_bindings():
    with session_scope() as db:
        return jsonify({"items": AIProviderRepository(db).list_bindings()})


@ai_provider_bp.route("/api/ai/bindings", methods=["POST", "PUT", "PATCH"])
def upsert_ai_binding():
    payload = request.get_json() or {}
    if not str(payload.get("capability") or "").strip():
        return jsonify({"error": "capability is required"}), 400
    with session_scope() as db:
        return jsonify(AIProviderRepository(db).upsert_binding(payload))
