# Front Design Index

本文档是前端业务设计入口。先看这里，再进入对应页面设计文档和代码。

## 使用规则

- 修改业务页前，先读对应 `design/front/*.md`
- 如果改动了数据源、API、状态流、关键组件拆分或页面职责，同步更新对应 design
- 入口页顶部注释会回链到对应 design 文档；如果新增页面，也补同类注释

## 页面索引

- `Application Analysis`
  - route: `/stock-overview/application-analysis`
  - design: `design/front/application-analysis.md`
- `Industry Application`
  - route: `/stock-overview/industry-application`
  - design: `design/front/industry-application.md`
- `Stock Chart`
  - route: `/stock-chart`
  - design: `design/front/stock-chart.md`
- `Self-Selected`
  - route: `/stock-overview/self-selected`
  - design: `design/front/self-selected-item-card.md`
- `Market Pulse`
  - route: `/market/pulse`
  - design: `design/front/infra/market-pulse.detail.md`
- `Market Sentiment`
  - route: `/market/sentiment`
  - design: `design/front/market-sentiment.md`
- `MP4 to Word`
  - route: `/mp4-to-word`
  - design: `design/front/mp4-to-word.md`
- `MP4 History`
  - route: `/mp4-to-word/history`
  - design: `design/front/mp4-to-word.md`
- `Downloader`
  - route: `/downloader`
  - design: `design/front/downloader.md`
- `Scheduler Settings`
  - route: `/settings/scheduler`
  - design: `design/front/settings-scheduler.md`
- `Stock Overview`
  - route: `/stock-overview`
  - design: `design/front/stock-overview.md`

## 后端联动设计

- `Application Analysis target / Self-Selected target` 同步
  - `design/backend/application-analysis-target-sync.md`
- `Market Sentiment` 因子链路
  - `design/backend/market-sentiment-pipeline.md`
- `Scheduler` 注册表与运行态
  - `design/backend/scheduler-registry-runtime.md`
- `MP4 History / reference` 落盘链路
  - `design/backend/mp4-history-reference-flow.md`
