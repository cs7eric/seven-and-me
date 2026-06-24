# Stock Chart

## 入口

- Route: `/stock-chart`
- Module: `frontend/src/views/stock-chart/index.tsx`
- Detail: `design/front/intraday-bs-marker.md`

## 数据源 / API

- 搜索与图表
  - `/api/stock-chart/search`
  - `/api/stock-chart/klines`
  - `/api/stock-chart/workspace`
- 标注与手动 B/S 点
  - `/api/stock-chart/annotations`
- 集合竞价 / 分时辅助
  - `/api/stock-chart/auction`
- 技术指标辅助
  - `/api/stock-chart/stock-meta`
  - `/api/stock-chart/market-breadth*`

## 页面职责

- 提供股票 / 指数 / 板块统一图表工作台
- 承担 workspace 保存、常用指标切换、手动 B/S 点、示例标注
- 给其它页面复用的图表交互提供参考实现

## 关键逻辑

- 周期切到分钟级时，强制 `adjust = none`
- 手动 B/S 点与普通 annotation 分开存；B/S 走共享的 `period = "all"`
- 页面初始化时同时拉 workspace、K 线、annotation、auction、breadth、meta
- `stockMeta -> sectorIndexSymbol` 会驱动上下文指数对比数据补拉

## 代码入口

- `frontend/src/views/stock-chart/index.tsx`
- `frontend/src/views/stock-chart/components/chart-panel.tsx`
- `frontend/src/views/stock-chart/components/technical-indicator-panel.tsx`
- `frontend/src/views/stock-chart/lib/store.ts`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果改动 annotation 存储约定、workspace 字段或 B/S 点持久化规则，必须同步更新本文档和 `intraday-bs-marker` 设计
