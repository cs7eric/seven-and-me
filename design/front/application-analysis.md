# Application Analysis

## 入口

- Route: `/stock-overview/application-analysis`
- Module: `frontend/src/views/application-analysis/index.tsx`
- Related backend design: `design/backend/application-analysis-target-sync.md`

## 数据源 / API

- target 配置与同步
  - `/api/stock-chart/application-analysis/targets`
- 单标的分析结果
  - `/api/stock-chart/application-analysis/results/:targetId`
- 手动运行与后台触发
  - `/api/stock-chart/application-analysis/run`
  - `/api/stock-chart/application-analysis/trigger`
  - `/api/stock-chart/application-analysis/scheduler/*`
- 图表基础数据
  - `/api/stock-chart/klines`
  - `/api/stock-chart/intraday`
  - `/api/stock-chart/annotations`
  - `/api/stock-chart/auction*`

## 页面职责

- 管理 application-analysis target 列表与 horizon
- 支持从 `self-selected` 带 query 进入预览态，再决定是否正式加入 target
- 在右侧统一承载 K 线、AI 方向、分析详情、集合竞价、技术指标、资金流
- 手动触发单标的分析，或把任务交给 scheduler 在后台跑

## 关键逻辑

- `previewTarget` 是临时态，不直接写库
- `targets + horizon` 用 debounce 持久化，页面卸载时会补一次 flush
- 图表页用 `displayedTarget = previewTarget ?? selected`，所以预览态也能看 K 线和分时
- AI 结果只对正式 target 生效，预览态不展示 AI 方向和分析详情

## 代码入口

- `frontend/src/views/application-analysis/index.tsx`
- `frontend/src/views/application-analysis/components/target-card.tsx`
- `frontend/src/views/application-analysis/components/chart-card.tsx`
- `frontend/src/views/application-analysis/components/intraday-analysis-dialog.tsx`
- `frontend/src/views/application-analysis/components/auction-tab.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 修改 target 持久化、预览态、与 `self-selected target` 的同步规则前，先看后端设计文档
- 改动 tab 结构、数据源、scheduler 触发方式后，必须同步更新本文档
