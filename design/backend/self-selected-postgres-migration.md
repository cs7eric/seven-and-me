# Self-Selected Postgres Migration

本文档是 `Self-Selected` 模块的维护入口。后续任何涉及表结构、ORM、repository、service、API、UI 协议的修改，先读本文，再改代码；改完后同步更新本文。

## 背景

原实现把自选股存到：

- `reference/self-selected/groups.json`
- `reference/self-selected/items.json`

这套方式能跑，但不适合继续扩展：

- 无法稳定承接并发写入
- 删除和唯一性依赖应用层约束
- 无法沉淀 schema / migration / ORM 规范
- 后续要做重排、批量导入、跨页面联动时维护成本高

本次迁移的目标是：运行时读写全面切到 Postgres，JSON 仅作为历史数据导入来源。

## 业务模型

页面真实业务只有两层：

1. 自选分组
   - 页面顶部 tab
   - 用户可创建、排序、删除
   - 业务上是“watchlist/list”

2. 分组条目
   - 分组下的一只标的
   - 记录 symbol、market、name、notes、target_type
   - 点击条目跳到 `application-analysis`

因此数据库只保留两张核心表，不为旧 JSON 结构迁就。

## 表设计

### `app.self_selected_lists`

含义：自选分组。

关键字段：

- `id uuid pk`
- `legacy_key varchar(64)`：保留旧 JSON id，方便首次导入去重
- `name varchar(128)`：tab 名称
- `description text`
- `color varchar(32)`：前端主题色 key
- `list_kind varchar(32)`：`manual | system`
- `status varchar(32)`：`active | disabled`
- `sort_order integer`
- `extra jsonb`
- `created_at / updated_at / deleted_at`
- `remark text`

### `app.self_selected_list_items`

含义：分组里的标的条目。

关键字段：

- `id uuid pk`
- `legacy_key varchar(64)`：保留旧 JSON id
- `list_id uuid`：逻辑关联 `self_selected_lists.id`
- `symbol varchar(32)`
- `market varchar(8)`：如 `SH` / `SZ` / `HK`
- `name varchar(128)`
- `notes text`
- `target_type varchar(32)`：`stock | hk_stock | etf | index | other`
- `source_type varchar(32)`：`manual | search | imported`
- `status varchar(32)`：`active | disabled`
- `sort_order integer`
- `extra jsonb`
- `created_at / updated_at / deleted_at`
- `remark text`

### 约束与索引

- 不使用物理外键，遵循 `skills/sql.md`
- `list_id + symbol` 做软删唯一索引
- `legacy_key` 做软删唯一索引，保证 JSON 首次导入幂等
- 分组、条目都使用 `updated_at` trigger

## 分层设计

### ORM

文件：

- [self_selected.py](/F:/dev-repo/mp4-to-word-new/backend/models/self_selected.py)

职责：

- 只描述数据库实体
- 字段名与 SQL 保持一致
- `SelfSelectedItem.group_id` 实际映射到列 `list_id`

### Repository

文件：

- [self_selected_db_repo.py](/F:/dev-repo/mp4-to-word-new/backend/repositories/stock/self_selected_db_repo.py)

职责：

- 只处理 Postgres CRUD
- 查询默认过滤 `deleted_at IS NULL`
- 负责首次 `JSON -> Postgres` 导入
- 返回前端兼容字段：仍输出 `group_id`

### Service

文件：

- [self_selected_service.py](/F:/dev-repo/mp4-to-word-new/backend/services/stock/self_selected_service.py)

职责：

- 作为 API 上行入口
- 先 `ensure_bootstrapped()`，再执行业务动作

### API

文件：

- [self_selected.py](/F:/dev-repo/mp4-to-word-new/backend/api/self_selected.py)

职责：

- 维持原有 REST 路径不变
- 事务边界仍在 `session_scope()`
- 对前端继续暴露 `groups/items` 语义

### Frontend

关键文件：

- [api.ts](/F:/dev-repo/mp4-to-word-new/frontend/src/lib/api.ts)
- [index.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/index.tsx)
- [item-row.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/components/item-row.tsx)
- [create-item-dialog.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/components/create-item-dialog.tsx)

当前要求：

- 页面文案不能再把运行时持久化描述成 `reference/self-selected`
- 条目跳转分析页时优先使用后端返回的 `target_type`

## 迁移策略

1. 新 migration 建 `app.self_selected_lists` / `app.self_selected_list_items`
2. 运行时首次访问模块时，如果新表为空，则从旧 JSON 导入
3. 导入时用 `legacy_key -> uuid5` 做稳定映射
4. 导入完成后，运行时只读写 Postgres

## 修改清单

涉及这一模块时，至少同步检查这些位置：

- schema / migration
- ORM
- repository
- service
- API response types
- frontend `Self-Selected` 页面文案与跳转逻辑
- 本文档

## 后续演进建议

如果后面要继续扩展，优先在这套模型上做，而不是回退到 JSON：

- 分组拖拽排序
- 条目拖拽排序
- 批量导入自选
- 条目标签 / 风险级别
- “已加入应用分析”状态做数据库快照化
