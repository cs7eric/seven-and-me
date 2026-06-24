# Backend Design Index

本文档是后端业务设计入口。修改 API、service、repository、scheduler 前，先看这里，再进入对应 design。

## 使用规则

- 修改后端业务逻辑前，先读对应 `design/backend/*.md`
- 如果改了接口契约、数据源优先级、交易日规则、落盘位置、同步关系或 scheduler 行为，同步更新 design
- 关键入口文件顶部说明应回链到对应 design；新增重要入口时也补同类说明

## 业务索引

- `Stock Chart API 聚合入口`
  - design: `design/backend/stock-chart-api-aggregation.md`
  - code: `backend/api/stock_chart.py`
- `Application Analysis target / Self-Selected target 同步`
  - design: `design/backend/application-analysis-target-sync.md`
  - code: `backend/services/stock/application_analysis_target_sync_service.py`
- `Market Sentiment 因子链`
  - design: `design/backend/market-sentiment-pipeline.md`
  - code: `backend/services/scheduler/*sentiment*.py`, `backend/repositories/market/*`
- `Scheduler 注册表 / 分类 / 运行态`
  - design: `design/backend/scheduler-registry-runtime.md`
  - code: `backend/api/scheduler.py`, `backend/repositories/scheduler/job_repo.py`
- `Transcription Runtime / SSE / Remote Parse`
  - design: `design/backend/transcription-runtime-flow.md`
  - code: `backend/api/transcription.py`, `backend/services/transcription_service.py`
- `MP4 History / reference 落盘`
  - design: `design/backend/mp4-history-reference-flow.md`
  - code: `backend/api/mp4_history.py`, `backend/services/mp4_history_service.py`

## 已有专项设计

- `design/backend/market-overview-json-to-postgres.md`
- `design/backend/market-pulse-postgres-migration.md`
- `design/backend/limit-emotion-json-to-postgres.md`
- `design/backend/self-selected-postgres-migration.md`
- `design/backend/application-analysis-target-postgres-migration.md`
- `design/backend/stock-data-source.md`
