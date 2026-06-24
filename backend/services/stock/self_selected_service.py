"""Self-Selected service layer.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\self-selected-postgres-migration.md`
`F:\dev-repo\mp4-to-word-new\design\backend\application-analysis-target-sync.md`
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.repositories.stock.self_selected_db_repo import SelfSelectedRepository
from backend.services.stock.application_analysis_target_sync_service import ApplicationAnalysisTargetSyncService


class SelfSelectedService:
    """API 与 repository 之间的轻量服务层。

    负责:
    - 首次运行时触发 JSON -> Postgres 导入
    - 对外提供稳定的 use-case 入口
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = SelfSelectedRepository(db)
        self.target_sync = ApplicationAnalysisTargetSyncService(db)

    def list_groups(self) -> list[dict]:
        self.repo.ensure_bootstrapped()
        return self.repo.list_groups()

    def create_group(self, payload: dict) -> dict:
        self.repo.ensure_bootstrapped()
        return self.repo.create_group(payload)

    def update_group(self, group_id: str, payload: dict) -> dict | None:
        self.repo.ensure_bootstrapped()
        return self.repo.update_group(group_id, payload)

    def delete_group(self, group_id: str) -> bool:
        self.repo.ensure_bootstrapped()
        return self.repo.delete_group(group_id)

    def list_items(self, group_id: str | None = None) -> list[dict]:
        self.repo.ensure_bootstrapped()
        return self.repo.list_items(group_id=group_id)

    def create_item(self, payload: dict) -> dict:
        self.repo.ensure_bootstrapped()
        item = self.repo.create_item(payload)
        self.target_sync.on_self_selected_item_created(item["id"])
        return item

    def update_item(self, item_id: str, payload: dict) -> dict | None:
        self.repo.ensure_bootstrapped()
        item = self.repo.update_item(item_id, payload)
        if item is not None:
            self.target_sync.on_self_selected_item_updated(item["id"])
        return item

    def delete_item(self, item_id: str) -> bool:
        self.repo.ensure_bootstrapped()
        ok = self.repo.delete_item(item_id)
        if ok:
            self.target_sync.on_self_selected_item_deleted(item_id)
        return ok


__all__ = ["SelfSelectedService"]
