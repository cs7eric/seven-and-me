# Market Sentiment

## 入口

- Route: `/market/sentiment`
- Module: `frontend/src/views/market/market-sentiment/index.tsx`
- Related backend design: `design/backend/market-sentiment-pipeline.md`

## 数据源 / API

- composite 主卡
  - `/api/stock-chart/market-sentiment-index`
  - `/api/stock-chart/market-sentiment-index/history`
  - `/api/stock-chart/turnover-activity/history`
  - `/api/stock-chart/index-daily/history`
  - `/api/stock-chart/market-overview/history`
- 子卡因子
  - `risk-appetite*`
  - `market-breadth*`
  - `new-high-252d*`
  - `sector-breadth*`
  - `turnover-activity*`
  - `limit-emotion-summary*`
  - `volatility-sentiment*`
  - `style-risk-appetite*`
  - `profit-effect*`

## 页面职责

- 用 1 张 composite 大卡 + 9 张子卡表达市场情绪全景
- 支持按日期回看同一天的所有情绪因子
- 每张卡自己负责 snapshot + history 拉取，页面本身只负责日期联动

## 关键逻辑

- `index.tsx` 只有 `date` 状态，不直接持有具体因子数据
- 主卡需要拼接多来源历史序列，形成 overlay 图
- 各子卡统一模式：`snapshot + 3y history -> sparkline + 当日分数`
- 页面的复杂度主要在“因子口径一致”和“同日联动”，不是容器布局

## 代码入口

- `frontend/src/views/market/market-sentiment/index.tsx`
- `frontend/src/views/market/market-sentiment/components/market-sentiment-index-card.tsx`
- `frontend/src/views/market/market-sentiment/components/*.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 新增或替换情绪因子时，要同时更新本文档和后端 pipeline 文档
- 如果页面改成集中式数据加载，不要只改代码，先更新本文档里的职责描述
