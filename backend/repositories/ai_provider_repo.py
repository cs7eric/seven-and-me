from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.ai_provider import AIProvider, AIUsageBinding

# AI Provider architecture docs:
#   design/backend/ai-provider.md
# Keep that document in sync when changing provider types, capability routing, or CRUD shape.

CAPABILITIES: list[dict[str, str]] = [
    {"code": "text_polish", "label": "MP4 text polish"},
    {"code": "text_summary", "label": "MP4 summary"},
    {"code": "post_metadata", "label": "Markdown metadata"},
    {"code": "mp4_qa", "label": "MP4 Ask AI"},
    {"code": "application_analysis", "label": "Stock application analysis"},
    {"code": "application_recent30", "label": "Recent 30-day analysis"},
    {"code": "auction_analysis", "label": "Auction AI analysis"},
]

PROVIDER_TYPES: list[dict[str, str]] = [
    {
        "code": "minimax",
        "label": "MiniMax",
        "default_base_url": "https://api.minimaxi.com",
        "default_model": "MiniMax-M2.5",
        "api_key_env": "MINIMAX_API_KEY",
        "group_id_env": "MINIMAX_GROUP_ID",
    },
    {
        "code": "openai_compatible",
        "label": "OpenAI compatible",
        "default_base_url": "https://api.openai.com",
        "default_model": "",
        "api_key_env": "OPENAI_API_KEY",
        "group_id_env": "",
    },
    {
        "code": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "group_id_env": "",
    },
    {
        "code": "anthropic_compatible",
        "label": "Anthropic compatible",
        "default_base_url": "",
        "default_model": "",
        "api_key_env": "",
        "group_id_env": "",
    },
]


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _provider_to_dict(row: AIProvider, *, include_secret: bool = False) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "provider_type": row.provider_type,
        "base_url": row.base_url or "",
        "default_model": row.default_model or "",
        "models": row.models or [],
        "api_key": row.api_key if include_secret else "",
        "api_key_masked": _mask_secret(row.api_key),
        "api_key_env": row.api_key_env or "",
        "group_id": row.group_id or "",
        "group_id_env": row.group_id_env or "",
        "is_enabled": bool(row.is_enabled),
        "timeout_seconds": row.timeout_seconds,
        "extra": row.extra or {},
        "remark": row.remark or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _binding_to_dict(row: AIUsageBinding, provider: AIProvider | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "capability": row.capability,
        "label": row.label,
        "provider_id": str(row.provider_id) if row.provider_id else "",
        "provider": _provider_to_dict(provider) if provider else None,
        "model_override": row.model_override or "",
        "is_enabled": bool(row.is_enabled),
        "params": row.params or {},
        "remark": row.remark or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _uuid_value(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class AIProviderRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_capabilities(self) -> list[dict[str, str]]:
        return CAPABILITIES

    def list_provider_types(self) -> list[dict[str, str]]:
        return PROVIDER_TYPES

    def list_providers(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(AIProvider)
            .where(AIProvider.deleted_at.is_(None))
            .order_by(AIProvider.created_at.asc())
        ).scalars().all()
        return [_provider_to_dict(row) for row in rows]

    def get_provider(self, provider_id: str | UUID) -> AIProvider | None:
        return self.db.execute(
            select(AIProvider).where(
                AIProvider.deleted_at.is_(None),
                AIProvider.id == _uuid_value(provider_id),
            )
        ).scalar_one_or_none()

    def get_provider_by_code(self, code: str) -> AIProvider | None:
        return self.db.execute(
            select(AIProvider).where(
                AIProvider.deleted_at.is_(None),
                AIProvider.code == code,
            )
        ).scalar_one_or_none()

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_models = payload.get("models")
        models = [str(m).strip() for m in raw_models if str(m).strip()] if isinstance(raw_models, list) else []
        row = AIProvider(
            code=str(payload.get("code") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            provider_type=str(payload.get("provider_type") or "minimax").strip(),
            base_url=str(payload.get("base_url") or "").strip() or None,
            default_model=str(payload.get("default_model") or "").strip() or None,
            models=models,
            api_key=str(payload.get("api_key") or "").strip() or None,
            api_key_env=str(payload.get("api_key_env") or "").strip() or None,
            group_id=str(payload.get("group_id") or "").strip() or None,
            group_id_env=str(payload.get("group_id_env") or "").strip() or None,
            is_enabled=bool(payload.get("is_enabled", True)),
            timeout_seconds=payload.get("timeout_seconds") or None,
            extra=payload.get("extra") if isinstance(payload.get("extra"), dict) else {},
            remark=str(payload.get("remark") or "").strip() or None,
        )
        self.db.add(row)
        self.db.flush()
        return _provider_to_dict(row)

    def update_provider(self, provider_id: str | UUID, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.get_provider(provider_id)
        if not row:
            return None
        for key in [
            "code",
            "name",
            "provider_type",
            "base_url",
            "default_model",
            "api_key_env",
            "group_id",
            "group_id_env",
            "remark",
        ]:
            if key in payload:
                setattr(row, key, str(payload.get(key) or "").strip() or None)
        if "api_key" in payload and str(payload.get("api_key") or "").strip():
            row.api_key = str(payload.get("api_key")).strip()
        if "is_enabled" in payload:
            row.is_enabled = bool(payload.get("is_enabled"))
        if "timeout_seconds" in payload:
            row.timeout_seconds = payload.get("timeout_seconds") or None
        if "extra" in payload and isinstance(payload.get("extra"), dict):
            row.extra = payload["extra"]
        if "models" in payload and isinstance(payload.get("models"), list):
            row.models = [str(m).strip() for m in payload["models"] if str(m).strip()]
        row.updated_at = datetime.utcnow()
        self.db.flush()
        return _provider_to_dict(row)

    def delete_provider(self, provider_id: str | UUID) -> bool:
        row = self.get_provider(provider_id)
        if not row:
            return False
        row.deleted_at = datetime.utcnow()
        row.is_enabled = False
        self.db.flush()
        return True

    def list_bindings(self) -> list[dict[str, Any]]:
        bindings = self.db.execute(
            select(AIUsageBinding)
            .where(AIUsageBinding.deleted_at.is_(None))
            .order_by(AIUsageBinding.capability.asc())
        ).scalars().all()
        provider_ids = [row.provider_id for row in bindings if row.provider_id]
        providers = {}
        if provider_ids:
            provider_rows = self.db.execute(
                select(AIProvider).where(AIProvider.id.in_(provider_ids), AIProvider.deleted_at.is_(None))
            ).scalars().all()
            providers = {row.id: row for row in provider_rows}
        return [_binding_to_dict(row, providers.get(row.provider_id)) for row in bindings]

    def get_binding_row(self, capability: str) -> AIUsageBinding | None:
        return self.db.execute(
            select(AIUsageBinding).where(
                AIUsageBinding.deleted_at.is_(None),
                AIUsageBinding.capability == capability,
            )
        ).scalar_one_or_none()

    def upsert_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        capability = str(payload.get("capability") or "").strip()
        row = self.get_binding_row(capability)
        if row is None:
            label = str(payload.get("label") or "").strip()
            if not label:
                label = next((item["label"] for item in CAPABILITIES if item["code"] == capability), capability)
            row = AIUsageBinding(capability=capability, label=label)
            self.db.add(row)
        if "label" in payload:
            row.label = str(payload.get("label") or "").strip() or row.label
        if "provider_id" in payload:
            provider_id = str(payload.get("provider_id") or "").strip()
            row.provider_id = UUID(provider_id) if provider_id else None
        if "model_override" in payload:
            row.model_override = str(payload.get("model_override") or "").strip() or None
        if "is_enabled" in payload:
            row.is_enabled = bool(payload.get("is_enabled"))
        if "params" in payload and isinstance(payload.get("params"), dict):
            row.params = payload["params"]
        if "remark" in payload:
            row.remark = str(payload.get("remark") or "").strip() or None
        row.updated_at = datetime.utcnow()
        self.db.flush()
        provider = self.get_provider(row.provider_id) if row.provider_id else None
        return _binding_to_dict(row, provider)

    def resolve_binding(self, capability: str) -> tuple[AIUsageBinding | None, AIProvider | None]:
        binding = self.get_binding_row(capability)
        if not binding or not binding.is_enabled or not binding.provider_id:
            return binding, None
        provider = self.get_provider(binding.provider_id)
        if not provider or not provider.is_enabled:
            return binding, None
        return binding, provider
