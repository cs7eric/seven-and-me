# Scheduler Registry Runtime

## 适用范围

- `/settings/scheduler` 页面
- `scheduler/jobs.json` 注册表
- job category、运行态、history 展示

## 相关代码

- API
  - `backend/api/scheduler.py`
- Repo / Service
  - `backend/repositories/scheduler/job_repo.py`
  - `backend/services/scheduler/config_store.py`
  - `backend/services/scheduler/status_store.py`
  - `backend/services/scheduler/job_history.py`
  - `backend/services/scheduler/job_description_catalog.py`

## 设计要点

- 前端列表展示的是“注册表 + live 状态 + 上次运行摘要”的组合视图
- category 由后端定义，前端只做 tab 分组和排序消费
- 单 job history 按需拉取，避免首页把所有历史都带回来

## 维护要求

- 改 `jobs.json` 结构、category 元数据或 action response 时，同步更新前端 design 文档
