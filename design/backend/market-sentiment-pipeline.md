# Market Sentiment Pipeline

## 适用范围

- `/market/sentiment` 页面所依赖的 composite 指数和 9 个子因子

## 前端入口

- `frontend/src/views/market/market-sentiment/index.tsx`
- `frontend/src/views/market/market-sentiment/components/*.tsx`

## 相关代码

- API
  - `backend/api/stock_chart.py`
- Repository / Service
  - `backend/repositories/market/market_sentiment_index_repo.py`
  - `backend/repositories/market/risk_appetite_repo.py`
  - `backend/repositories/market/sector_breadth_repo.py`
  - `backend/repositories/market/turnover_activity_repo.py`
  - `backend/repositories/market/volatility_sentiment_repo.py`
  - `backend/repositories/market/style_risk_appetite_repo.py`
  - `backend/repositories/market/profit_effect_repo.py`
  - `backend/repositories/market/limit_repo.py`
- Scheduler
  - `backend/services/scheduler/market_sentiment_index_scheduler.py`
  - `backend/services/scheduler/risk_appetite_scheduler.py`
  - `backend/services/scheduler/sector_breadth_scheduler.py`
  - `backend/services/scheduler/turnover_activity_scheduler.py`
  - `backend/services/scheduler/volatility_sentiment_scheduler.py`
  - `backend/services/scheduler/style_risk_appetite_scheduler.py`
  - `backend/services/scheduler/profit_effect_scheduler.py`
  - `backend/services/scheduler/limit_emotion_scheduler.py`

## 设计要点

- 页面不是一个单一接口，而是“composite 主卡 + 多个独立因子卡”
- 每个因子都要同时提供 snapshot 和 history，保证同日回看与 sparkline 一致
- 主卡会额外拼接上证指数、成交额、主力净流等历史序列，形成 overlay 图

## 维护要求

- 新增、下线或重算因子时，前后端文档都要同步更新，不要只改 API 名称
