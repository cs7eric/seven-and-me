# Frontend API Migration

## Purpose

本文档记录旧前端 `frontend/src` 中所有需要迁移或拆分的 API 使用面，目标是把接口调用从巨型 `src/lib/api.ts` 逐步拆到 `src/services/{domain}/...`，并明确哪些后端能力迁到 Java 微服务，哪些必须继续由 Python 服务承载。

当前扫描日期：2026-06-26

## Source Files Reviewed

Frontend:

- `frontend/src/lib/api.ts`
- `frontend/src/services/**`
- `frontend/src/router/index.tsx`
- `frontend/src/views/**`
- `frontend/src/components/**`

Old Python backend:

- `backend/api/transcription.py`
- `backend/api/mp4_history.py`
- `backend/api/scheduler.py`
- `backend/api/self_selected.py`
- `backend/api/ai_providers.py`
- `backend/api/stock_chart.py`
- `backend/api/stock/f10.py`
- `backend/api/system.py`

New Java backend:

- `cynexus-ai/**/controller/*.java`
- `cynexus-market/**/controller/*.java`
- `cynexus-core/**/controller/*.java`

## Current Frontend Service Layout

```txt
frontend/src/services/
  common/
    service-prefix.ts        # SERVICE_PREFIX: legacy/cynexus/ai/market/core
    http.ts                  # fetchWithRetry
    cynexus-result.ts        # Java Result<T> adapter + BIGINT id preservation
  ai/
    provider.ts              # AI Provider 配置, 已接 Java Gateway
  market/
    self-selected.ts         # 自选股, 已接 Java Gateway
  scheduler/
    management.ts            # Scheduler 管理 API, 仍接 Python runtime
```

`src/lib/api.ts` 目前仍保留大量旧接口，同时 re-export 已拆出的服务。后续迁移应遵守：

- 新增或迁移的接口不再直接写进 `src/lib/api.ts`。
- 页面优先从 `@/services/{domain}/...` import。
- `src/lib/api.ts` 只做短期兼容导出，最终应逐步清空。
- 所有 Java 微服务路径必须通过 `SERVICE_PREFIX` 管理。
- Scheduler / crawler / transcription trigger 默认保持 Python，除非 Java 已实现等价运行时能力。

## Current Migration Snapshot

Already split from `src/lib/api.ts`:

| Domain | Frontend File | Backend |
|---|---|---|
| AI Provider Settings | `src/services/ai/provider.ts` | Java `cynexus-ai`, `/api/ai/config/*` |
| Self Selected | `src/services/market/self-selected.ts` | Java `cynexus-market`, `/api/market/data/self-selected-*` |
| Scheduler Management | `src/services/scheduler/management.ts` | Python legacy `/api/scheduler/*` |

Still importing from `@/lib/api`:

| Area | Representative Files |
|---|---|
| Global search/history | `src/components/global-command-palette.tsx`, `src/components/mp4-history-data-table.tsx` |
| MP4 workflow | `src/views/mp4-to-word/page.tsx`, `src/views/mp4-to-word/history.tsx` |
| Downloader | `src/views/downloader/index.tsx` |
| Stock chart | `src/views/stock-chart/index.tsx`, `src/views/stock-chart/components/symbol-search.tsx` |
| Stock detail/F10 | `src/components/stock-detail-dialog.tsx`, `src/components/industry-constituents-drawer.tsx` |
| Market overview/pulse/sentiment | `src/views/stock-overview/**`, `src/views/market/market-pulse/**`, `src/views/market/market-sentiment/**` |
| Application analysis | `src/views/application-analysis/**` |
| Industry application | `src/views/industry-application/**` |
| Self selected supplemental stock lookup | `src/views/self-selected/**` still imports stock search/sector types from `@/lib/api` |

## Service Prefix Standard

```ts
SERVICE_PREFIX.legacy      // old Flask/Python API, usually /api/*
SERVICE_PREFIX.cynexus     // Java Gateway root
SERVICE_PREFIX.ai          // /api/ai
SERVICE_PREFIX.aiConfig    // /api/ai/config
SERVICE_PREFIX.market      // /api/market
SERVICE_PREFIX.marketData  // /api/market/data
SERVICE_PREFIX.core        // /api/core
```

## Migration Status Legend

| Status | Meaning |
|---|---|
| Migrated | Frontend calls Java Gateway or new service file already. |
| Split Only | Frontend code is split into `src/services`, but backend still uses Python. |
| Pending | Still primarily lives in `src/lib/api.ts` and calls old Flask. |
| Keep Python | Should remain Python because it depends on local models, crawler runtime, files, or non-Java libraries. |
| Hybrid | Read/query can move to Java, but refresh/trigger/crawler remains Python. |

## Complete API Inventory

### 1. Transcription / MP4 Processing

Routes/pages:

- `/mp4-to-word`
- `/mp4-to-word/history`
- shared components: MP4 history table, command palette history search

Frontend helpers:

- `uploadFile`
- `uploadFileWithProgress`
- `createSSEConnection`
- `fetchTaskSnapshot`
- `askQuestion`
- `exportMarkdown`
- `checkStatus`
- `sendDownloaderResultToParse`

Current endpoints:

- `POST /api/transcribe`
- `GET /api/stream/{taskId}` via `EventSource`
- `GET /api/task/{taskId}`
- `POST /api/ask`
- `GET /api/export-markdown/{taskId}`
- `GET /api/status`
- `POST /api/parse-video`

Current backend owner:

- Python `backend/api/transcription.py`
- Python runtime store, local files, Whisper/model pipeline, SSE stream.

Target:

- Frontend file: `src/services/collector/transcription.ts`
- Backend owner: keep Python, later register as `cynexus-collector`.
- Java migration: not recommended for model runtime. Java may only proxy or store metadata.

Status:

- Pending frontend service split.
- Keep Python backend.

Notes:

- SSE must keep compatible event shape.
- Upload progress uses `XMLHttpRequest`; do not replace casually with `fetch`.
- `/api/ask` depends on existing Python AI provider registry and task context.

### 2. Downloader / Remote Parse

Routes/pages:

- `/downloader`
- `/mp4-to-word` remote parse handoff

Frontend helpers:

- `parseDownloaderUrl`
- `sendDownloaderResultToParse`

Current endpoints:

- `GET /api/parse?...`
- `POST /api/parse-video`

Current backend owner:

- Python downloader/parser flow.

Target:

- Frontend file: `src/services/collector/downloader.ts`
- Backend owner: keep Python collector.

Status:

- Pending frontend service split.
- Keep Python backend.

Notes:

- `src/views/mp4-to-word/page.tsx` also directly fetches remote `draft.downloadUrl`; this is not a backend API and should remain browser-side unless CORS or security requirements change.

### 3. MP4 Reference History

Routes/pages:

- `/mp4-to-word/history`
- command palette
- MP4 history data table

Frontend helpers:

- `saveMP4History`
- `listMP4History`
- `reorderMP4History`
- `deleteMP4History`
- `getMP4History`
- `askHistoryQuestion`

Current endpoints:

- `POST /api/reference/mp4-history`
- `GET /api/reference/mp4-history`
- `POST /api/reference/mp4-history/reorder`
- `GET /api/reference/mp4-history/{id}`
- `DELETE /api/reference/mp4-history/{id}`
- `POST /api/reference/mp4-history/{id}/ask`

Current backend owner:

- Python `backend/api/mp4_history.py`

Target:

- Frontend file: `src/services/collector/mp4-history.ts`
- Backend owner:
  - storage-only CRUD can move to Java `core` later.
  - `ask` should stay Python/collector until Java AI execution has equivalent history context.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

### 4. AI Provider Settings

Routes/pages:

- `/settings/ai-provider`

Frontend service:

- `src/services/ai/provider.ts`

Frontend helpers:

- `fetchAiCapabilities`
- `fetchAiProviderTypes`
- `fetchAiProviders`
- `createAiProvider`
- `updateAiProvider`
- `deleteAiProvider`
- `fetchAiBindings`
- `upsertAiBinding`

Old endpoints:

- `GET /api/ai/capabilities`
- `GET /api/ai/provider-types`
- `GET /api/ai/providers`
- `POST /api/ai/providers`
- `PUT/PATCH/DELETE /api/ai/providers/{id}`
- `GET /api/ai/bindings`
- `POST/PUT/PATCH /api/ai/bindings`

Current Java endpoints:

- `GET /api/ai/config/providers`
- `GET /api/ai/config/providers/{id}`
- `POST /api/ai/config/providers`
- `PUT /api/ai/config/providers`
- `DELETE /api/ai/config/providers/{id}`
- `GET /api/ai/config/usage-bindings`
- `GET /api/ai/config/usage-bindings/{id}`
- `POST /api/ai/config/usage-bindings`
- `PUT /api/ai/config/usage-bindings`

Current backend owner:

- Java `cynexus-ai`

Status:

- Migrated.

Open items:

- Java does not yet expose `capabilities` and `provider-types`; frontend currently keeps static constants for these lists.
- Consider adding Java endpoints later:
  - `GET /api/ai/config/capabilities`
  - `GET /api/ai/config/provider-types`

### 5. Scheduler Management

Routes/pages:

- `/settings/scheduler`
- future dashboard scheduler cards

Frontend service:

- `src/services/scheduler/management.ts`

Frontend helpers:

- `fetchSchedulerDailyStats`
- `fetchSchedulerCategories`
- `fetchSchedulerJobs`
- `fetchSchedulerJobHistory`
- `enableSchedulerJob`
- `disableSchedulerJob`
- `triggerSchedulerJob`
- `startSchedulerJob`
- `stopSchedulerJob`
- `deleteSchedulerJob`

Current endpoints:

- `GET /api/scheduler/stats/daily`
- `GET /api/scheduler/categories`
- `GET /api/scheduler/jobs`
- `GET /api/scheduler/jobs/{jobId}`
- `GET /api/scheduler/jobs/{jobId}/history`
- `POST /api/scheduler/jobs/{jobId}/enable`
- `POST /api/scheduler/jobs/{jobId}/disable`
- `POST /api/scheduler/jobs/{jobId}/trigger`
- `POST /api/scheduler/jobs/{jobId}/start`
- `POST /api/scheduler/jobs/{jobId}/stop`
- `DELETE /api/scheduler/jobs/{jobId}`

Current backend owner:

- Python `backend/api/scheduler.py`

Java table CRUD available:

- `GET /api/core/scheduler/jobs`
- `GET /api/core/scheduler/categories`
- `GET /api/core/scheduler/category-mappings`
- `GET /api/core/scheduler/run-history`
- `GET /api/core/scheduler/statuses`
- plus create/update/delete CRUD for the same resources.

Status:

- Split Only.
- Trigger remains Python by design.

Migration rule:

- Keep `triggerSchedulerJob`, `startSchedulerJob`, `stopSchedulerJob`, `enableSchedulerJob`, `disableSchedulerJob`, `deleteSchedulerJob` on Python until Java owns the actual runtime scheduler.
- Java `core` can be used later for persisted registry/status/history reads, but its DTO shape does not yet match `/settings/scheduler` page requirements.

### 6. Self Selected

Routes/pages:

- `/stock-overview/self-selected`
- command palette uses list/search data

Frontend service:

- `src/services/market/self-selected.ts`

Frontend helpers:

- `fetchSelfSelectedGroups`
- `createSelfSelectedGroup`
- `updateSelfSelectedGroup`
- `deleteSelfSelectedGroup`
- `fetchSelfSelectedItems`
- `createSelfSelectedItem`
- `updateSelfSelectedItem`
- `deleteSelfSelectedItem`

Old endpoints:

- `GET/POST /api/self-selected/groups`
- `PUT/DELETE /api/self-selected/groups/{id}`
- `GET/POST /api/self-selected/items`
- `PUT/DELETE /api/self-selected/items/{id}`

Current Java endpoints:

- `GET/POST/PUT /api/market/data/self-selected-lists`
- `GET/DELETE /api/market/data/self-selected-lists/{id}`
- `GET/POST/PUT /api/market/data/self-selected-list-items`
- `GET/DELETE /api/market/data/self-selected-list-items/{id}`

Current backend owner:

- Java `cynexus-market`

Status:

- Migrated.

### 7. Stock Search / Chart / Workspace / Annotation

Routes/pages:

- `/stock-chart`
- stock detail dialog
- symbol search component
- application-analysis target search

Frontend helpers:

- `searchStockChart`
- `fetchStockKlines`
- `fetchStockWorkspace`
- `saveStockWorkspace`
- `listStockAnnotations`
- `createStockAnnotation`
- `deleteStockAnnotation`
- `fetchStockAuction`
- `fetchStockIntraday`
- `fetchStockMeta`
- `fetchStockSectors`

Current endpoints:

- `GET /api/stock-chart/search`
- `GET /api/stock-chart/klines`
- `GET/POST /api/stock-chart/workspace`
- `GET/POST /api/stock-chart/annotations`
- `DELETE /api/stock-chart/annotations/{id}`
- `GET /api/stock-chart/auction`
- `GET /api/stock-chart/intraday`
- `GET /api/stock-chart/stock-meta`
- `GET /api/stock-chart/f10/stock-sectors`

Current backend owner:

- Python `backend/api/stock_chart.py`
- Python `backend/api/stock/f10.py`
- DuckDB/ClickHouse/Postgres mixed data sources.

Target:

- Frontend files:
  - `src/services/market/stock-search.ts`
  - `src/services/market/stock-chart.ts`
  - `src/services/market/stock-workspace.ts`
  - `src/services/market/stock-annotation.ts`
  - `src/services/market/stock-feature.ts`
- Backend owner:
  - query/read APIs: Java `cynexus-market` where data already exists in Postgres/ClickHouse.
  - live external fetches: Python collector until Java has equivalent adapters.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

Java related endpoints already exist:

- `GET /api/market/stocks/{symbol}/daily-feature`
- `GET /api/market/stocks/{symbol}/intraday-feature`

### 8. F10 / Fundamental Data

Routes/pages:

- stock detail dialog
- industry constituents drawer

Frontend helpers:

- `fetchStockValuation`
- `fetchStockFinanceReport`
- `fetchStockBusinessComposition`
- `fetchStockProfitForecast`
- `fetchStockAnnouncements`
- `fetchStockNews`
- `fetchStockRoadshows`
- `fetchStockCompanyNews`
- `fetchIndustryConstituentsByCode`
- `refreshIndustryConstituentsByCode`
- `fetchCachedIndustryConstituentsCodes`
- `fetchIndustryConstituentsByName`
- `refreshIndustryConstituentsByName`
- `fetchIndustryConstituentsFromIndexByCode`
- `fetchIndustryConstituentsFromIndexByName`

Related backend endpoints that exist but are not first-class frontend helpers in `src/lib/api.ts` yet:

- `/api/stock-chart/f10/topics`
- `/api/stock-chart/f10/topic-compare`
- `/api/stock-chart/f10/topic-stocks`
- `/api/stock-chart/f10/stock-topics`
- `/api/stock-chart/f10/theme-market`
- `/api/stock-chart/f10/stock-info`
- `/api/stock-chart/f10/company-profile`
- `/api/stock-chart/f10/finance-diagnosis`
- `/api/stock-chart/f10/stock-score`
- `/api/stock-chart/f10/ranking-detail`
- `/api/stock-chart/f10/governance`
- `/api/stock-chart/sectors-market`
- `/api/stock-chart/sectors-market/industry`
- `/api/stock-chart/sectors-market/concept`
- `/api/stock-chart/eltdx/industry-index-kline`
- `/api/stock-chart/eltdx/concept-index-kline`
- `/api/stock-chart/eltdx/index-kline`
- `/api/stock-chart/eltdx/index-codes`

Current endpoints:

- `GET /api/stock-chart/f10/valuation`
- `GET /api/stock-chart/f10/finance-report`
- `GET /api/stock-chart/f10/business-composition`
- `GET /api/stock-chart/f10/profit-forecast`
- `GET /api/stock-chart/f10/announcements`
- `GET /api/stock-chart/f10/news`
- `GET /api/stock-chart/f10/roadshows`
- `GET /api/stock-chart/f10/company-news`
- `GET /api/stock-chart/ths-industry/constituents-by-code`
- `POST /api/stock-chart/ths-industry/constituents-by-code/refresh`
- `GET /api/stock-chart/ths-industry/constituents-by-code/cached`
- `GET /api/stock-chart/ths-industry/constituents`
- `GET /api/stock-chart/ths-industry/constituents-file`

Current backend owner:

- Python `backend/api/stock/f10.py`
- Python `backend/api/stock_chart.py`
- hexin-v / q.10jqka crawler logic.

Target:

- Frontend file: `src/services/market/f10.ts`
- Backend owner:
  - cached read endpoints can move to Java market after data is persisted.
  - refresh/crawl endpoints stay Python collector.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

### 9. Market Overview / Market Pulse

Routes/pages:

- `/stock-overview`
- `/stock-overview/market`
- `/market/pulse`
- `/stock-overview/market-pulse`
- heatmap components

Frontend helpers:

- `fetchMarketBreadth`
- `fetchMarketBreadthSeries`
- `fetchMarketOverviewEltdx`
- `triggerMarketOverviewEltdxRefresh`
- `fetchMarketOverviewAkshare`
- `triggerMarketOverviewAkshareRefresh`
- `fetchManualFundFlow`
- `saveManualFundFlow`
- `fetchMarketOverviewAkshareArchive`
- `fetchMarketPulseHistory`
- `fetchMarketOverview`
- `fetchMarketPulse`
- `fetchStyleSectors`
- `fetchStyleSectorConstituents`
- `fetchMarketPulseRotationTrend`
- `fetchMarketPulseIndustryCompare`
- `fetchIndustryFundFlowIndustryList`
- `fetchMarketPulseLimitEmotion`
- `refreshMarketPulseLimitEmotion`
- `fetchIndustryDetail`
- `fetchIndustryFundFlow`
- `refreshIndustryFundFlow`
- `fetchIndustryFundFlowHistory`
- `fetchMarketPulseSchedulerStatus`
- `triggerMarketPulseSnapshot`

Current endpoints:

- `GET /api/stock-chart/market-breadth`
- `GET /api/stock-chart/market-breadth-series`
- `GET /api/stock-chart/market-overview-eltdx`
- `POST /api/stock-chart/market-overview-eltdx/refresh`
- `GET /api/stock-chart/market-overview-akshare`
- `POST /api/stock-chart/market-overview-akshare/refresh`
- `GET/POST /api/stock-chart/market-overview-manual-fund-flow`
- `GET /api/stock-chart/market-overview-akshare/archive/{date}`
- `GET /api/stock-chart/market-overview-akshare/history`
- `GET /api/stock-chart/market-overview`
- `GET /api/stock-chart/market-pulse/all`
- `GET /api/stock-chart/style-sectors`
- `GET /api/stock-chart/style-sectors/{name}/constituents`
- `GET /api/stock-chart/market-pulse/rotation-trend`
- `GET /api/stock-chart/market-pulse/industry-compare`
- `GET /api/stock-chart/ths-industry/fund-flow/industry-series`
- `GET /api/stock-chart/market-pulse/limit-emotion`
- `POST /api/stock-chart/market-pulse/limit-emotion/refresh`
- `GET /api/stock-chart/market-pulse/industry-detail`
- `GET /api/stock-chart/ths-industry/fund-flow`
- `POST /api/stock-chart/ths-industry/fund-flow/refresh`
- `GET /api/stock-chart/ths-industry/fund-flow/history`
- `GET /api/stock-chart/market-pulse-scheduler/status`
- `POST /api/stock-chart/market-pulse-scheduler/trigger`

Related backend endpoints that exist but are not first-class frontend helpers in `src/lib/api.ts` yet:

- `/api/stock-chart/limit-count`
- `/api/stock-chart/limit-count/refresh`
- `/api/stock-chart/turnover`
- `/api/stock-chart/turnover/refresh`
- `/api/stock-chart/turnover/refresh-all`
- `/api/stock-chart/turnover/scheduler/status`
- `/api/stock-chart/turnover/scheduler/trigger`
- `/api/stock-chart/market-pulse/strong`
- `/api/stock-chart/market-pulse/capital-flow`
- `/api/stock-chart/market-pulse/rotation`
- `/api/stock-chart/market-pulse/sector-history`
- `/api/stock-chart/market-pulse/sector-daily`
- `/api/stock-chart/market-pulse-scheduler/trigger-constituents`
- `/api/stock-chart/ths-industry/list`
- `/api/stock-chart/ths-industry/info`
- `/api/stock-chart/ths-industry/kline`
- `/api/stock-chart/individual/main-fund-flow`
- `/api/stock-chart/qt/fund-flow`
- `/api/stock-chart/qt/fund-flow-batch`
- `/api/stock-chart/ths-industry/constituents-all`
- `/api/stock-chart/ths-industry/fund-flow/db-history`
- `/api/stock-chart/market-pulse/limit-emotion/daily-snapshot`
- `/api/stock-chart/market-pulse/limit-emotion/history`
- `/api/stock-chart/market-pulse/limit-emotion/config`

Current backend owner:

- Python market repositories and schedulers.

Target:

- Frontend files:
  - `src/services/market/overview.ts`
  - `src/services/market/pulse.ts`
  - `src/services/market/industry.ts`
  - `src/services/market/style-sector.ts`
- Backend owner:
  - read APIs over migrated Postgres/ClickHouse tables: Java `cynexus-market`.
  - refresh/trigger/crawler APIs: Python collector.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

Java related endpoints already exist:

- `GET /api/market/overview`
- `GET /api/market/sectors/rank`
- CRUD under `/api/market/data/*` for migrated market tables.

Special note:

- `triggerMarketPulseSnapshot` must remain Python until Java owns the runtime scheduler and crawler chain.

### 10. Market Sentiment / MSI

Routes/pages:

- `/market/sentiment`
- `poc/sentiment-overlay`

Frontend helpers:

- `fetchMarketSentimentMaCount`
- `fetchMarketSentimentMaCountHistory`
- `fetchMarketPulseIndexReturns`
- `fetchMarketPulseIndexReturnsHistory`
- `fetchMarketSentimentSectorBreadth`
- `fetchMarketSentimentSectorBreadthHistory`
- `fetchMarketSentimentRiskAppetite`
- `fetchMarketSentimentRiskAppetiteHistory`
- `fetchMarketSentimentLimitEmotionSummary`
- `fetchMarketSentimentLimitEmotionSummaryHistory`
- `fetchMarketSentimentVolatilitySentiment`
- `fetchMarketSentimentVolatilitySentimentHistory`
- `fetchMarketSentimentTurnoverActivity`
- `fetchMarketSentimentTurnoverActivityHistory`
- `fetchMarketSentimentStyleRiskAppetite`
- `fetchMarketSentimentStyleRiskAppetiteHistory`
- `fetchMarketSentimentProfitEffect`
- `fetchMarketSentimentProfitEffectHistory`
- `fetchMarketSentimentIndex`
- `fetchMarketSentimentIndexHistory`
- `fetchIndexKlineBatch`
- `fetchIndexDailyHistory`
- `fetchMarketOverviewHistory`

Current endpoints:

- `GET /api/stock-chart/market-sentiment/ma-count`
- `GET /api/stock-chart/market-sentiment/ma-count/history`
- `GET /api/stock-chart/market-pulse/index-returns`
- `GET /api/stock-chart/market-pulse/index-returns/history`
- `GET /api/stock-chart/market-sentiment/sector-breadth`
- `GET /api/stock-chart/market-sentiment/risk-appetite`
- `GET /api/stock-chart/market-sentiment/limit-emotion-summary`
- `GET /api/stock-chart/market-sentiment/volatility-sentiment`
- `GET /api/stock-chart/market-sentiment/turnover-activity`
- `GET /api/stock-chart/market-sentiment/style-risk-appetite`
- `GET /api/stock-chart/market-sentiment/profit-effect`
- `GET /api/stock-chart/market-sentiment/index`
- history variants for the same indicators.
- `GET /api/index-kline/batch`
- `GET /api/stock-chart/index/daily`
- `GET /api/stock-chart/market-overview/history`

Current backend owner:

- Python market repositories over DuckDB/Postgres-derived data.

Target:

- Frontend file: `src/services/market/sentiment.ts`
- Backend owner:
  - Java `cynexus-market` for Postgres read tables:
    - `msi_index_daily`
    - `msi_limit_emotion_daily`
    - `msi_ma_count_daily`
    - `msi_profit_effect_daily`
    - `msi_risk_appetite_daily`
    - `msi_style_risk_daily`
    - `msi_turnover_activity_daily`
    - `msi_volatility_daily`
    - `msi_sector_breadth_daily`
  - ClickHouse-backed raw daily/index data can be exposed by Java market later if repository exists.
  - Refresh calculations remain Python collector until rewritten.

Status:

- Pending frontend service split.
- High-priority Java read migration candidate.

### 11. Application Analysis

Routes/pages:

- `/stock-overview/application-analysis`
- application-analysis components:
  - target cards
  - auction tab
  - technical indicator tab
  - intraday analysis dialog

Frontend helpers:

- `runApplicationAnalysis`
- `fetchApplicationAnalysisTargets`
- `saveApplicationAnalysisTargets`
- `fetchApplicationAnalysisResult`
- `triggerApplicationAnalysis`
- `fetchApplicationAnalysisSchedulerStatus`
- `controlApplicationAnalysisScheduler`
- `refreshApplicationAnalysisRecent30`
- `listApplicationAnalysisRecent30`
- `readApplicationAnalysisRecent30`
- `listApplicationAnalysisRecent30Full`
- `runAuctionAiAnalysis`
- `fetchAuctionAiAnalysisSnapshot`
- `triggerAuctionAiAnalysisScheduler`

Current endpoints:

- `POST /api/stock-chart/application-analysis`
- `GET/POST /api/stock-chart/application-analysis/targets`
- `GET /api/stock-chart/application-analysis/results/{targetId}`
- `POST /api/stock-chart/application-analysis/refresh`
- `GET /api/stock-chart/application-analysis/scheduler`
- `POST /api/stock-chart/application-analysis/scheduler/{start|stop}`
- `POST /api/stock-chart/application-analysis/recent30/refresh`
- `GET /api/stock-chart/application-analysis/recent30/{targetId}`
- `GET /api/stock-chart/application-analysis/recent30/{targetId}/full`
- `POST /api/stock-chart/auction-ai-analysis`
- `GET /api/stock-chart/auction-ai-analysis`
- `POST /api/stock-chart/auction-ai-analysis/scheduler/trigger`

Current backend owner:

- Python stock chart + AI analysis pipeline.

Target:

- Frontend file: `src/services/ai/application-analysis.ts`
- Backend owner:
  - Java `cynexus-ai` already has table CRUD for:
    - `analysis-configs`
    - `analysis-daily-snapshots`
    - `analysis-result-current`
    - `analysis-result-history`
    - `analysis-targets`
  - Python should remain owner for execution/trigger until Java AI orchestration is feature-complete.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

Migration rule:

- Targets/results reads can migrate to Java after DTO shape is aligned.
- `triggerApplicationAnalysis`, scheduler start/stop, auction trigger remain Python initially.

### 12. Industry / Concept Application

Routes/pages:

- `/stock-overview/industry-application`

Frontend helpers:

- `fetchIndustryApplicationTargets`
- `saveIndustryApplicationTargets`
- `fetchIndustryApplicationTargetCodes`
- `fetchIndustryApplicationKline`
- `refreshIndustryApplication`
- `fetchIndustryApplicationResult`
- `fetchIndustryApplicationOverview`
- `fetchMarketHeatmap`

Current endpoints:

- `GET/POST /api/stock-chart/industry-application/targets`
- `GET /api/stock-chart/industry-application/target-codes`
- `GET /api/stock-chart/industry-application/kline`
- `POST /api/stock-chart/industry-application/refresh`
- `GET /api/stock-chart/industry-application/results/{targetId}`
- `GET /api/stock-chart/industry-application/overview`
- `GET /api/stock-chart/industry-application/heatmap`

Current backend owner:

- Python stock chart / industry application services.

Target:

- Frontend file: `src/services/ai/industry-application.ts` or `src/services/market/industry-application.ts`.
- Backend owner:
  - target/config/result AI portions: Java `cynexus-ai`.
  - market data/kline/heatmap portions: Java `cynexus-market`.
  - refresh execution remains Python collector until orchestration is migrated.

Status:

- Pending frontend service split.
- Hybrid backend candidate.

### 13. Heatmap Demo / Debug Pages

Routes/pages:

- `/heatmap-demo`
- `/heatmap-data-debug`

Current behavior:

- `src/views/heatmap-demo/index.tsx` hardcodes `http://localhost:5000/api/stock-chart/style-sectors`.

Target:

- Replace hardcoded URL with service call:
  - `src/services/market/style-sector.ts`
  - `SERVICE_PREFIX.legacy` initially.
  - later Java `SERVICE_PREFIX.market`.

Status:

- Pending cleanup.

### 14. Dashboard / System

Routes/pages:

- `/dashboard`

Current behavior:

- Mostly static cards and future API placeholders.
- Mentions future `/api/scheduler/jobs`, `/api/ask`, `/api/system/model-info`.

Current endpoints used elsewhere:

- `GET /api/status`
- `GET /api/system/db-health` exists in Python backend but not currently central in frontend API helpers.

Target:

- Frontend file: `src/services/core/system.ts`
- Backend owner:
  - Java `core` for service health.
  - Python collector health for model/Whisper/runtime details.

Status:

- Pending design.

## Frontend-Unused Or Debug Backend APIs

These Python endpoints were found during backend route scan, but the current frontend migration does not treat them as primary page dependencies. Keep them out of Java migration unless a page or workflow explicitly starts using them:

| Area | Endpoints |
|---|---|
| Static files | `/uploads/{filename}`, `/outputs/{filename}` |
| Stock debug / POC | `/api/stock-chart/etf/poc`, `/api/stock-chart/feature-summary` |
| Auction history/status | `/api/stock-chart/auction-ai-analysis/history`, `/api/stock-chart/auction-ai-analysis/scheduler` |
| Industry extra views | `/api/stock-chart/industry-application/results`, `/api/stock-chart/industry-application/tdx-industry-56`, `/api/stock-chart/industry-application/tdx-industry-kline`, `/api/stock-chart/industry-application/tdx-industry-snapshot` |
| System diagnostics | `/api/system/db-health` |

## Recommended `src/services` Target Structure

```txt
src/services/
  common/
    service-prefix.ts
    http.ts
    cynexus-result.ts
  ai/
    provider.ts                  # done
    application-analysis.ts       # pending
    industry-application.ts       # pending if AI-owned pieces are separated
  collector/
    transcription.ts              # pending
    downloader.ts                 # pending
    mp4-history.ts                # pending
    runtime.ts                    # pending, system/model status
  core/
    scheduler-data.ts             # pending, Java /api/core/scheduler table CRUD
    system.ts                     # pending
  market/
    self-selected.ts              # done
    stock-search.ts               # pending
    stock-chart.ts                # pending
    stock-workspace.ts            # pending
    stock-annotation.ts           # pending
    f10.ts                        # pending
    overview.ts                   # pending
    pulse.ts                      # pending
    sentiment.ts                  # pending
    industry.ts                   # pending
    style-sector.ts               # pending
  scheduler/
    management.ts                 # done, Python runtime
```

## Migration Priority

### Phase 1: Frontend service split without backend behavior changes

Goal: remove most business APIs from `src/lib/api.ts` while preserving current behavior.

Order:

1. `collector/transcription.ts`
2. `collector/downloader.ts`
3. `collector/mp4-history.ts`
4. `market/stock-search.ts`
5. `market/stock-chart.ts`
6. `market/f10.ts`
7. `market/overview.ts`
8. `market/pulse.ts`
9. `market/sentiment.ts`
10. `ai/application-analysis.ts`
11. `market/industry-application.ts` or `ai/industry-application.ts`

Validation:

- No direct service implementation remains in `src/lib/api.ts`.
- Pages import directly from `src/services/...`.
- `pnpm exec tsc --noEmit --pretty false` passes.

### Phase 2: Java read API migration

Goal: move stable reads backed by Postgres/ClickHouse into Java Gateway.

Suggested order:

1. Market Sentiment reads (`msi_*` tables).
2. Market overview reads (`mkt_*` tables).
3. Industry fund flow / sector pulse reads.
4. Application analysis target/result reads using `cynexus-ai`.
5. Stock feature reads using `cynexus-market`.
6. Scheduler persisted registry/status/history reads using `cynexus-core`, only after DTO adapter is designed.

Validation:

- Long IDs are preserved as strings.
- Java `Result<T>` is adapted centrally.
- No trigger or crawler is accidentally moved to Java.

### Phase 3: Runtime trigger migration only after equivalent service exists

Do not migrate these until Java or a managed Python service owns equivalent runtime:

- `/api/scheduler/jobs/{id}/trigger`
- `/api/stock-chart/market-pulse-scheduler/trigger`
- `/api/stock-chart/application-analysis/refresh`
- `/api/stock-chart/application-analysis/scheduler/{start|stop}`
- `/api/stock-chart/auction-ai-analysis/scheduler/trigger`
- `/api/stock-chart/ths-industry/*/refresh`
- `/api/stock-chart/market-overview-*/*refresh`
- `/api/transcribe`
- `/api/stream/{taskId}`

## Backend Ownership Matrix

| Domain | Preferred Java Service | Keep Python For |
|---|---|---|
| AI Provider config | `cynexus-ai` | none, except static capabilities until Java endpoint exists |
| AI execution / prompts | `cynexus-ai` | legacy MP4 context execution until rewritten |
| Application analysis data | `cynexus-ai` | refresh, scheduler, auction runtime |
| Self selected | `cynexus-market` | none |
| Market sentiment reads | `cynexus-market` | indicator refresh/calculation pipeline |
| Market overview/pulse reads | `cynexus-market` | crawler/refresh/snapshot trigger |
| F10 cached reads | `cynexus-market` | hexin-v/10jqka crawler refresh |
| Stock chart raw K-line | `cynexus-market` over ClickHouse | live external fetch fallback |
| Scheduler registry/status tables | `cynexus-core` | runtime process control and trigger |
| MP4 transcription | none or `cynexus-collector` | Whisper/model/files/SSE |
| Downloader | none or `cynexus-collector` | parsing and remote media handling |
| MP4 history | `cynexus-core` possible | history ask/context AI until rewritten |

## Page-Level Migration Checklist

| Page | Current Important APIs | Target Service Files | Backend Plan |
|---|---|---|---|
| `/downloader` | `parseDownloaderUrl` | `collector/downloader.ts` | Python collector |
| `/mp4-to-word` | upload, SSE, task, ask, export | `collector/transcription.ts` | Python collector |
| `/mp4-to-word/history` | MP4 history CRUD/ask | `collector/mp4-history.ts` | hybrid core + Python |
| `/stock-chart` | search, kline, workspace, annotations, auction, intraday | `market/*` | hybrid Java reads + Python live |
| `/stock-overview` | market overview | `market/overview.ts` | Java reads, Python refresh |
| `/stock-overview/market` | market pulse | `market/pulse.ts`, `market/industry.ts` | Java reads, Python trigger |
| `/market/pulse` | overview/pulse/style/heatmap | `market/pulse.ts`, `market/style-sector.ts` | Java reads, Python refresh |
| `/market/sentiment` | MSI indicators | `market/sentiment.ts` | Java read migration priority |
| `/stock-overview/application-analysis` | target/result/recent30/scheduler/auction | `ai/application-analysis.ts` | hybrid |
| `/stock-overview/industry-application` | industry app target/kline/result/heatmap | `ai` + `market` split | hybrid |
| `/stock-overview/self-selected` | self selected CRUD | `market/self-selected.ts` | migrated Java |
| `/settings/scheduler` | scheduler management | `scheduler/management.ts` | split only, Python runtime |
| `/settings/ai-provider` | AI provider CRUD/binding | `ai/provider.ts` | migrated Java |
| `/heatmap-demo` | hardcoded style sectors | `market/style-sector.ts` | cleanup needed |

## Acceptance Rules For Each Migrated API Group

1. Service file exists under `src/services/{domain}`.
2. Page imports from service file, not `@/lib/api`.
3. Uses `SERVICE_PREFIX`, not raw `http://localhost:5000` or inline `/api/...` unless the function explicitly accepts external URLs.
4. Java-backed APIs use `cynexusResult<T>`.
5. BIGINT IDs remain strings in frontend models.
6. Trigger APIs document whether they call Python or Java.
7. `pnpm exec tsc --noEmit --pretty false` passes.
8. For touched files, run targeted eslint.

## Known Risks

- `src/lib/api.ts` is still large and mixes many domains.
- Some Python endpoints return shape `{ ok, items, count }`, while Java returns `Result<T>`; adapters must be explicit.
- Some frontend types use snake_case for legacy compatibility; Java DTOs are camelCase.
- Refresh/trigger endpoints often have side effects and should not be migrated by URL replacement alone.
- `heatmap-demo` contains a hardcoded backend URL and should be fixed early.
- Scheduler Java CRUD is not equivalent to Python runtime scheduler contract.

## Next Recommended Work

1. Move transcription/downloader/history into `src/services/collector`.
2. Move market sentiment APIs into `src/services/market/sentiment.ts` while still calling Python.
3. Add Java market read endpoints/adapters for MSI tables.
4. Move market pulse/overview APIs into service files.
5. Split application-analysis into `src/services/ai/application-analysis.ts`, keeping execution triggers on Python.
6. Only after service split is complete, reduce `src/lib/api.ts` to re-export compatibility or delete it.
