# Scheduler Settings

## 入口

- Route: `/settings/scheduler`
- Module: `frontend/src/views/settings/scheduler/index.tsx`
- Related backend design: `design/backend/scheduler-registry-runtime.md`

## 数据源 / API

- job 列表 / 分类 / 日统计
  - `/api/scheduler/jobs`
  - `/api/scheduler/categories`
  - `/api/scheduler/stats/daily`
- 单 job history
  - `/api/scheduler/jobs/:id/history`
- 控制动作
  - `/api/scheduler/jobs/:id/enable`
  - `/api/scheduler/jobs/:id/disable`
  - `/api/scheduler/jobs/:id/start`
  - `/api/scheduler/jobs/:id/stop`
  - `/api/scheduler/jobs/:id/trigger`
  - `DELETE /api/scheduler/jobs/:id`

## 页面职责

- 展示 scheduler 注册表、分组、运行态、最近运行摘要
- 提供 enable/disable/start/stop/trigger/delete 等运维动作
- 懒加载单 job history，避免首页过重

## 关键逻辑

- category tab 只是前端分组视图，真实排序依赖后端 `categorySortOrders`
- job card 和详情 dialog 共用同一份 job 数据；history 单独按需拉取
- 所有动作完成后都会延时 refresh，等后端先把状态写回

## 代码入口

- `frontend/src/views/settings/scheduler/index.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果后端 category / live status / action response 结构变更，必须同步更新本文档
