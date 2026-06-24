# Industry Application

## 入口

- Route: `/stock-overview/industry-application`
- Module: `frontend/src/views/industry-application/index.tsx`

## 数据源 / API

- target 配置
  - `/api/stock-chart/industry-application/targets`
  - `/api/stock-chart/industry-application/target-codes`
- K 线与指标
  - `/api/stock-chart/industry-application/kline`
  - `/api/stock-chart/industry-application/results/:targetId`
- 手动刷新落盘
  - `/api/stock-chart/industry-application/refresh`
- 总览热力图
  - `/api/stock-chart/industry-application/heatmap`

## 页面职责

- 管理行业 / 概念 watchlist
- 支持 query 预览，再决定是否加入 watchlist
- 左侧维护目标，右侧承载总览、K 线、技术指标、资金流等 tab
- 当前没有 scheduler，刷新由手动触发

## 关键逻辑

- 页面布局与 `application-analysis` 对齐，但数据口径不同
- `ChartCard` 复用个股分析页组件，K 线数据通过 `eltdxBarToStockBar` 适配
- `overview` tab 的热力图可自动刷新，其余 tab 围绕单个行业/概念展开
- `AI 方向 / 分析详情 / 分时` 目前是明确的不可用能力，不是假装有数据

## 代码入口

- `frontend/src/views/industry-application/index.tsx`
- `frontend/src/views/industry-application/components/sector-heatmap.tsx`
- `frontend/src/views/industry-application/components/industry-technical-indicator-panel.tsx`
- `frontend/src/views/industry-application/components/industry-fund-flow-table.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果以后接 scheduler、AI 分析明细或真实分时能力，要先改本文档里的“页面职责”和“关键逻辑”
