# Stock Chart API Aggregation

## Required Entry

后续任何人如果要看、改、重构 `stock_chart` 相关接口，请先看本文，再去代码。

相关文件：

- `F:\dev-repo\mp4-to-word-new\design\backend\stock-chart-api-aggregation.md`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock_chart.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\stock\f10.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\kline_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\workspace_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\application_analysis_scheduler.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_overview_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\market_heatmap_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\stock\limit_emotion_service.py`

要求：

- 先更新本文档，再改代码
- 改完代码后，必须把本文档回写到最新状态

## Scope

`backend/api/stock_chart.py` 不是单一业务接口，而是一个聚合入口，承载了：

- stock chart 搜索 / K 线 / 分时 / workspace / annotation
- auction / auction AI analysis
- application-analysis target / result / scheduler 触发
- market overview / market heatmap / market pulse / limit emotion 的一部分接口
- market sentiment 默认日期等页面级辅助能力

它的职责是“对前端统一出入口”，不是“自己承载全部业务计算”。

## Layer Rules

### 1. API 层职责

- 解析 query/body
- 统一响应结构
- 做轻量参数校验和 fallback
- 把请求分发到 service / repository

### 2. API 层不应承担

- 重业务计算
- 多来源数据融合细节
- 持久化协议本身
- scheduler 运行逻辑

这些应下沉到 `backend/services/stock/*` 或 repository。

## Main Flows

### 1. K 线 / 分时

- route:
  - `/api/stock-chart/search`
  - `/api/stock-chart/klines`
  - `/api/stock-chart/intraday`
- core:
  - `search_stock_chart`
  - `resolve_stock_klines`
  - `build_intraday_snapshot`
- 特点：
  - API 层负责 target_type / period / adjust 参数归一
  - 指数分钟级数据优先读持久化 snapshot，不够时再退到 timeshare 推导

### 2. Workspace / Annotation

- route:
  - `/api/stock-chart/workspace`
  - `/api/stock-chart/annotations`
- core:
  - `get_stock_workspace`
  - `put_stock_workspace`
  - `list_stock_annotations`
  - `create_stock_annotation`
  - `update_stock_annotation`
  - `remove_stock_annotation`
- 特点：
  - workspace 和 annotation 是图表状态持久化入口
  - 前端 `stock-chart`、`application-analysis` 的 B/S 标记都依赖这条链路

### 3. Application Analysis

- route:
  - `/api/stock-chart/application-analysis/*`
- core:
  - `backend.services.stock.application_analysis_scheduler`
  - `backend.services.stock.application_analysis_service`
  - `backend.services.stock.application_analysis_store`
- 特点：
  - API 层主要做 target 列表、结果读取、scheduler 控制和手动触发
  - target 与 self-selected 系统组的同步规则见 `application-analysis-target-sync.md`

### 4. 市场概览 / 热力图 / 情绪

- route:
  - `/api/stock-chart/market-overview*`
  - `/api/stock-chart/industry-application/heatmap`
  - `/api/stock-chart/market-pulse/limit-emotion*`
- core:
  - `market_overview_service`
  - `market_heatmap_service`
  - `limit_emotion_service`
- 特点：
  - 页面看起来在前端是一个页面，后端其实是多条 service 链路拼出来的

## Maintenance Notes

- 如果 `stock_chart.py` 继续膨胀，优先按业务域拆 blueprint，不要把新能力继续平铺进去
- 改接口时，除代码外至少同步检查：
  - 前端 design 文档是否需要更新
  - 对应 service 的交易日 / fallback 规则是否被影响
  - annotation / workspace / application-analysis 是否被连带影响
