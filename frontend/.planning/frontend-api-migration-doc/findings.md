# Frontend API Migration Findings

## Initial Observations

- Existing `src/services` folders:
  - `common`: `SERVICE_PREFIX`, retry HTTP, Java `Result<T>` parsing.
  - `ai`: AI Provider configuration routed through Java Gateway.
  - `market`: self-selected routed through Java Gateway.
  - `scheduler`: scheduler management extracted to service file but intentionally still uses Python legacy prefix.
- Main legacy API surface remains in `src/lib/api.ts`.

## API Surface Scan

- `src/lib/api.ts` exports the majority of old frontend API helpers.
- Major endpoint prefixes found:
  - `/api/transcribe`, `/api/stream`, `/api/task`, `/api/ask`, `/api/export-markdown`
  - `/api/reference/mp4-history`
  - `/api/parse`, `/api/parse-video`
  - `/api/stock-chart/*`
  - `/api/index-kline/*`
  - `/api/scheduler/*`
- Direct page-level network calls are limited:
  - `src/views/heatmap-demo/index.tsx` uses hardcoded `http://localhost:5000/api/stock-chart/style-sectors`.
  - `src/views/mp4-to-word/page.tsx` fetches remote downloader URLs directly, not backend APIs.

## Route/Page Scan

- Frontend routes are defined in `src/router/index.tsx`.
- API-bearing pages/components include:
  - `/downloader`
  - `/mp4-to-word` and `/mp4-to-word/history`
  - `/stock-chart`
  - `/stock-overview`
  - `/stock-overview/market`
  - `/market/pulse`
  - `/market/sentiment`
  - `/stock-overview/application-analysis`
  - `/stock-overview/industry-application`
  - `/stock-overview/self-selected`
  - `/settings/scheduler`
  - `/settings/ai-provider`
  - `heatmap-demo` and `heatmap-data-debug`

## Backend Capability Scan

- Old Python backend route files still own runtime-heavy APIs:
  - `backend/api/transcription.py`: upload, SSE, export, ask.
  - `backend/api/scheduler.py`: scheduler runtime management and trigger.
  - `backend/api/stock_chart.py` and `backend/api/stock/f10.py`: most market/stock endpoints.
  - `backend/api/mp4_history.py`: reference history.
- Java backend currently has:
  - `cynexus-ai`: `/api/ai/config/*`, AI CRUD and analysis-related table CRUD.
  - `cynexus-market`: `/api/market/data/*`, `/api/market/overview`, `/api/market/sectors/rank`, `/api/market/stocks/*/feature`.
  - `cynexus-core`: `/api/core/scheduler/*` table CRUD, not the Python runtime trigger contract.

## Final Document Findings

- Migration document was created at `design/front/infra/frontend-api-migration.md`.
- `design/front/infra/index.md` now links to the migration document.
- Current migrated frontend service groups:
  - AI Provider Settings: `src/services/ai/provider.ts`, Java `/api/ai/config/*`.
  - Self Selected: `src/services/market/self-selected.ts`, Java `/api/market/data/self-selected-*`.
  - Scheduler Management: `src/services/scheduler/management.ts`, still Python `/api/scheduler/*`.
- Remaining frontend API migration work is concentrated in:
  - collector/transcription/downloader/history.
  - stock chart/search/workspace/annotation/F10.
  - market overview/pulse/sentiment/MSI.
  - application analysis and industry application.
- Backend route scan also found Python endpoints not currently exposed as first-class frontend helpers, including F10 topic/theme APIs, limit/turnover APIs, ETF POC/debug APIs, and several industry/debug endpoints. These are recorded as non-primary migration candidates.
