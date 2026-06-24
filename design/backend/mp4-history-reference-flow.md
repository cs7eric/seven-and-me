# MP4 History Reference Flow

## 适用范围

- `/mp4-to-word`
- `/mp4-to-word/history`
- Downloader 远程转入后续的历史落盘

## 相关代码

- API
  - `backend/api/transcription.py`
  - `backend/api/mp4_history.py`
- Service / Repo
  - `backend/services/transcription_service.py`
  - `backend/services/mp4_history_service.py`
  - `backend/repositories/mp4_history_repo.py`

## 设计要点

- 实时任务态由 `task_id + SSE` 驱动
- 历史页读的是 `reference / history` 落盘结果，不直接依赖运行态内存
- Downloader 只是入口，真正的处理与落盘归 `mp4-to-word` 流程

## 维护要求

- 改任务状态、history 存储位置、Ask AI 历史接口时，前后端文档都要同步更新
