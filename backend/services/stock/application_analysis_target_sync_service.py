r"""Application Analysis target sync service.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\application-analysis-target-postgres-migration.md`

这里负责:
- application-analysis targets 的 Postgres 读写
- 与 self-selected 系统分组 `target` 的双向同步
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.repositories.stock.application_analysis_target_repo import (
    ApplicationAnalysisTargetRepository,
    _TARGET_GROUP_NAME,
)
from backend.repositories.stock.self_selected_db_repo import SelfSelectedRepository


class ApplicationAnalysisTargetSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.target_repo = ApplicationAnalysisTargetRepository(db)
        self.self_repo = SelfSelectedRepository(db)

    def ensure_bootstrapped(self) -> None:
        self.self_repo.ensure_bootstrapped()
        self.target_repo.ensure_bootstrapped()

    def list_targets(self) -> list[dict]:
        self.ensure_bootstrapped()
        return self.target_repo.list_targets()

    def load_config(self) -> dict:
        self.ensure_bootstrapped()
        return self.target_repo.load_config_payload()

    def save_config(self, payload: dict) -> dict:
        self.ensure_bootstrapped()
        return self.target_repo.save_config_payload(payload)

    def get_target(self, target_id: str) -> dict | None:
        self.ensure_bootstrapped()
        return self.target_repo.get_target_by_public_id(target_id)

    def get_target_group_name(self) -> str:
        return _TARGET_GROUP_NAME

    def on_self_selected_item_created(self, item_id: str) -> None:
        self.ensure_bootstrapped()
        item = self.self_repo.get_item_entity(item_id)
        if item is None or item.deleted_at is not None:
            return
        group = self.self_repo.get_group_entity(item.group_id)
        if group is None or group.deleted_at is not None:
            return
        self.target_repo.sync_target_from_self_selected_item(item, group)

    def on_self_selected_item_updated(self, item_id: str) -> None:
        self.on_self_selected_item_created(item_id)

    def on_self_selected_item_deleted(self, item_id: str) -> None:
        self.self_repo.ensure_bootstrapped()
        self.target_repo.ensure_target_group()
        self.target_repo.ensure_default_config()
        item = self.self_repo.get_item_entity(item_id)
        if item is None:
            return
        group = self.self_repo.get_group_entity(item.group_id)
        if group is None or group.name.lower() != _TARGET_GROUP_NAME:
            return
        self.target_repo.sync_target_delete_from_self_selected_item(item)


__all__ = ["ApplicationAnalysisTargetSyncService"]
