# Application Analysis Postgres Migration

## Required Entry

后续任何人如果要看、改、重构以下功能，请先看本文，再去代码：

- `F:\dev-repo\mp4-to-word-new\backend\models\application_analysis.py`
- `F:\dev-repo\mp4-to-word-new\backend\repositories\stock\application_analysis_target_repo.py`
- `F:\dev-repo\mp4-to-word-new\backend\repositories\stock\self_selected_db_repo.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_store.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_scheduler.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_target_sync_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\self_selected_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock_chart.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\self_selected.py`
- `F:\dev-repo\mp4-to-word-new\frontend\src\lib\api.ts`
- `F:\dev-repo\mp4-to-word-new\frontend\src\views\application-analysis\index.tsx`
- `F:\dev-repo\mp4-to-word-new\frontend\src\views\application-analysis\components\target-card.tsx`
- `F:\dev-repo\mp4-to-word-new\frontend\src\views\self-selected\index.tsx`
- `F:\dev-repo\mp4-to-word-new\frontend\src\views\self-selected\components\item-row.tsx`
- `F:\dev-repo\mp4-to-word-new\frontend\src\views\self-selected\components\add-item-tile.tsx`

要求：

- 先更新本文档，再改代码。
- 改完代码后，必须同步把本文档回写到最新状态。

## Scope

本次迁移覆盖 4 部分：

- `Application Analysis targets`
- `Application Analysis result latest / history`
- `Application Analysis recent30 daily snapshot`
- `Self-Selected` 中的系统分组 `target`

不在本次迁移范围内：

- scheduler 状态文件 `reference/application-analysis/scheduler.json`
- 其它业务线的 JSON 持久化

## Goals

- 抛弃运行时 `reference/application-analysis/targets.json` 取值逻辑
- 抛弃运行时 `reference/application-analysis/results/**` 结果真相源逻辑
- 抛弃运行时 `reference/application-analysis/history/**` 历史真相源逻辑
- 抛弃运行时 `runtime/application-analysis-daily-snapshots/**` recent30 真相源逻辑
- Application Analysis 改为 Postgres 统一持久化
- `Self-Selected` 中自动维护系统分组 `target`
- `Application Analysis target` 与 `Self-Selected target group` 双向同步
- 前端明确标识 target 系统组，且系统组不可删除

## Business Rules

### 1. 主体关系

- `Application Analysis targets` 是独立业务表，不借用 self-selected item 表本身存分析配置。
- `Self-Selected` 中的 `target` 分组是系统镜像分组，不是 source of truth。
- `Application Analysis result latest / history / recent30 snapshot` 也都是独立业务存储，不挂靠 self-selected。

### 2. target 与 self-selected 的同步方向

#### target -> self-selected

- 当 target 新增/更新时：
  - 自动同步到 `self-selected` 的系统分组 `target`
- 当 target 删除时：
  - 自动软删 `self-selected target` 分组中的镜像条目

#### self-selected(target group) -> target

- 当用户在 `self-selected` 的 `target` 系统分组里新增/更新条目时：
  - 自动同步到 `Application Analysis targets`
- 当用户删除 `self-selected target` 分组中的条目时：
  - 自动软删对应 target

#### 非 target 分组不参与同步

- 普通自选分组仍只是 watchlist
- 只有 `list_kind=system` 且业务名为 `target` 的分组参与 target 双向联动

### 3. 系统分组约束

- `Self-Selected target` 分组属于系统分组
- 系统分组必须可见
- 系统分组不可删除
- 前端必须给系统分组明显标识
- 在系统分组内允许继续“加入 target”，作为用户显式入口

### 4. 结果与历史的语义

#### latest result

- 每个 target 只有一份“当前最新分析结果”
- 每次 scheduler/manual 成功执行：
  - 覆盖 current 记录
  - 同时追加一条 history snapshot

#### history snapshot

- history 是 append-only 语义
- 一次分析运行对应一条快照
- 不因为 current 被覆盖而丢失旧记录

#### recent30 daily snapshot

- recent30 是按 `trade_date` 维度持久化
- 同一个 `target + trade_date + snapshot_kind` 只有一条有效记录
- 同日再次刷新是 update，不是新增多条

## Field Mapping

### target 主表保留字段

- `target_key`
- `legacy_key`
- `symbol`
- `market`
- `name`
- `target_type`
- `adjust`
- `enabled`
- `interval_minutes`
- `sort_order`
- `tags`
- `source_type`
- `extra`

### self-selected target 分组镜像保留字段

- `group_id`
- `symbol`
- `market`
- `name`
- `notes`
- `target_type`
- `extra.linkedApplicationAnalysisTargetKey`
- `extra.linkedApplicationAnalysisTargetId`

说明：

- target 表承接分析配置字段
- self-selected item 继续保留 `notes`
- notes 不反向写回 target 主表

### result / history / daily snapshot 保留字段

为了兼容旧接口结构，PG 中保留旧 JSON 主体字段：

- `target`
- `updated_at`
- `analysis_input`
- `analysis_result`
- `raw_result`
- `raw_root_keys`
- `dump_paths`
- `segments`
- `horizon`
- `elapsed_seconds`
- `recent_window`
- `date`
- `short_term_trend`
- `current_situation`
- `summary`

## Schema

### 1. `app.application_analysis_configs`

用途：

- 保存 target 页面全局配置

字段：

- `id uuid pk`
- `config_key varchar(64)`，默认 `default`
- `status varchar(32)`：`active | disabled`
- `horizon_days integer`
- `horizon_segments integer`
- `monthly_keep integer`
- `weekly_keep integer`
- `extra jsonb`
- `remark text`
- `created_at / updated_at / deleted_at`

### 2. `app.application_analysis_targets`

用途：

- Application Analysis target 主表

字段：

- `id uuid pk`
- `target_key varchar(64)`，如 `stock-600021`
- `legacy_key varchar(64)`
- `self_selected_item_id uuid`
- `symbol varchar(32)`
- `market varchar(8)`
- `name varchar(128)`
- `target_type varchar(32)`：
  - `stock`
  - `hk_stock`
  - `etf`
  - `index`
  - `other`
- `adjust varchar(16)`
- `enabled boolean`
- `interval_minutes integer`
- `source_type varchar(32)`：
  - `manual`
  - `search`
  - `imported`
  - `self_selected_sync`
- `status varchar(32)`：
  - `active`
  - `disabled`
- `sort_order integer`
- `tags jsonb`
- `extra jsonb`
- `remark text`
- `created_at / updated_at / deleted_at`

### 3. `app.application_analysis_result_current`

用途：

- 每个 target 的当前最新分析结果

字段建议：

- `id uuid pk`
- `target_id uuid`
- `target_key varchar(64)`
- `status varchar(32)`：
  - `success`
  - `failed`
- `analysis_run_at timestamptz`
- `payload jsonb`
- `remark text`
- `created_at / updated_at / deleted_at`

约束：

- `target_id` 活跃态唯一

### 4. `app.application_analysis_result_history`

用途：

- 保存 Application Analysis 每次运行的历史快照

字段建议：

- `id uuid pk`
- `target_id uuid`
- `target_key varchar(64)`
- `analysis_run_at timestamptz`
- `payload jsonb`
- `source_kind varchar(32)`：
  - `scheduler`
  - `manual`
  - `api`
  - `scheduler_recent30_daily`
- `created_at / updated_at / deleted_at`

说明：

- history 为 append-only
- 不做 current 覆盖

### 5. `app.application_analysis_daily_snapshots`

用途：

- recent30 结果按交易日持久化

字段建议：

- `id uuid pk`
- `target_id uuid`
- `target_key varchar(64)`
- `trade_date date`
- `snapshot_kind varchar(32)`，当前固定 `recent30`
- `payload jsonb`
- `created_at / updated_at / deleted_at`

约束：

- `(target_id, trade_date, snapshot_kind)` 活跃态唯一

## Runtime Architecture

### 1. target config 层

- 对外继续保留 `load_targets()` / `save_targets()`
- 上层 API / scheduler / 页面不用改调用入口
- 底层真相源已经是 Postgres

### 2. latest result / history 层

- 对外继续保留：
  - `write_result`
  - `read_result`
  - `list_result_files`
  - `list_history`
- 但这些函数不再读写本地 JSON
- 旧 `path / filename` 字段只作为兼容层元信息虚拟返回

### 3. recent30 daily snapshot 层

- 对外继续保留：
  - `write_daily_snapshot`
  - `list_daily_snapshots`
  - `read_daily_snapshot`
- 底层切到 Postgres
- scheduler / API / 前端继续沿用原函数签名

### 4. bootstrap 策略

- `targets.json` 只作为首次导入源
- `results/**` / `history/**` / `daily snapshots/**` 只作为一次性迁移导入源
- 迁移完成后不再作为运行时真相源

## API Compatibility

### application-analysis

- `GET /api/stock-chart/application-analysis/targets`
- `PUT /api/stock-chart/application-analysis/targets`
- `GET /api/stock-chart/application-analysis/results`
- `GET /api/stock-chart/application-analysis/results/<target_id>`
- `POST /api/stock-chart/application-analysis/refresh`
- `GET /api/stock-chart/application-analysis/recent30/<target_id>`
- `GET /api/stock-chart/application-analysis/recent30/<target_id>/full`

兼容要求：

- 前端依旧能拿到 `_meta_result_path`
- 前端依旧能拿到 `_meta_history`
- recent30 列表仍返回 `filename / path / date / updated_at`
- 这些 path 字段允许是虚拟逻辑路径，作用只剩“可理解”和“兼容旧 UI”

### self-selected

- `GET /api/self-selected/groups`
- `DELETE /api/self-selected/groups/<group_id>`

额外要求：

- 后端要阻止系统组删除
- 前端不能只靠隐藏按钮，后端也必须做强约束

## Frontend Requirements

### Self-Selected 页面

- target 系统组要有特殊 badge / 文案
- target 系统组的 delete 入口必须隐藏或禁用
- group header 要能说明这是“应用分析联动分组”
- `AddItemTile` 在 target 组里要展示更明确入口，如：
  - `加入 target`
  - 或 `加入应用分析`

### Application Analysis 页面

- 文案不能再写“保存到 targets.json”
- 从自选页跳来预览时，加入动作实际上是写 Postgres
- 如果某个 target 来自 target 系统组联动，前端无需区分 source of truth，统一按 target 主表渲染

## Migration Steps

### 1. 先建表

```powershell
alembic upgrade head
```

### 2. 迁移 targets/config

- 从 `reference/application-analysis/targets.json` 导入
- 创建系统分组 `target`
- 建立 target 与 self-selected target 镜像关系

### 3. 迁移 result/history

- 扫描旧 `reference/application-analysis/results/*.json`
- 写入 `application_analysis_result_current`
- 扫描旧 `reference/application-analysis/history/*/*.json`
- 写入 `application_analysis_result_history`

导入原则：

- current 以结果文件为准
- history 全量导入
- 若 current 与 history 同时存在同一时点数据，以 current 维持最新展示，history 不去重也可以接受

### 4. 迁移 recent30 daily snapshot

- 扫描旧 daily snapshot 目录
- 逐 target / trade_date 导入
- 已存在同主键记录时做 upsert

### 5. 切换运行时真相源

- 先完成导入
- 再切换 `read/write/list` 逻辑到 PG
- 切换后旧 JSON 不再参与运行时读写

## Current Decisions

- target 表独立存，不和 self-selected item 混成一张表
- `self-selected target` 是系统镜像分组，不是 source of truth
- 系统分组不可删除
- 普通自选组不参与 target 同步
- latest result / history / recent30 snapshot 都切到 Postgres
- scheduler 状态文件本次继续保留本地 JSON

## Change Log

### 2026-06-22

- 新增 `application_analysis_configs`
- 新增 `application_analysis_targets`
- `Application Analysis targets/config` 从 JSON 切到 Postgres
- `Self-Selected` 引入系统分组 `target`
- 建立 target <-> self-selected(target group) 双向同步

### 2026-06-21

- 补充本次真实迁移范围定义：
  - result latest
  - result history
  - recent30 daily snapshot
  - self-selected target system group 保护与 UI 入口
- 明确旧 JSON 文件后续仅可作为一次性导入来源，不再作为运行时真相源
