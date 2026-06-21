"""Self-Selected service layer.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\self-selected-postgres-migration.md`
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.repositories.stock.self_selected_db_repo import SelfSelectedRepository


class SelfSelectedService:
    """API 与 repository 之间的轻量服务层。

    负责:
    - 首次运行时触发 JSON -> Postgres 导入
    - 对外提供稳定的 use-case 入口
    """

    def __init__(self, db: Session):
        self.repo = SelfSelectedRepository(db)

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
        return self.repo.create_item(payload)

    def update_item(self, item_id: str, payload: dict) -> dict | None:
        self.repo.ensure_bootstrapped()
        return self.repo.update_item(item_id, payload)

    def delete_item(self, item_id: str) -> bool:
        self.repo.ensure_bootstrapped()
        return self.repo.delete_item(item_id)


__all__ = ["SelfSelectedService"]
