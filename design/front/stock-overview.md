# Stock Overview

## 入口

- Route: `/stock-overview`
- Module: `frontend/src/views/stock-overview/index.tsx`

## 数据源 / API

- `/api/stock-chart/market-overview`

## 页面职责

- 展示市场情景驾驶舱
- 把后端生成的 market overview 结果拆成 hero、行动剧本、K 线区间、周期矩阵、相似场景、行业主线等版块

## 关键逻辑

- 前端几乎不做业务计算，主要负责把后端返回的结构化结果可视化
- 页面 load 很轻，复杂度在 SVG K 线区间图和多面板展示，不在状态机

## 代码入口

- `frontend/src/views/stock-overview/index.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果后端 `market-overview` 返回结构变化，优先改本文档里的字段职责说明，再动组件
