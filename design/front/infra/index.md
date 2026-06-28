## Market Pulse

- Route: `/stock-overview/market`
- Module: `frontend/src/views/stock-overview/market-pulse/index.tsx`
- Detail: `./market-pulse.detail.md`
- Front Index: `design/front/index.md`
- Data Source: Postgres 行业资金流日快照, 手动触发时可先刷新当日快照
- APIs: `/api/stock-chart/market-pulse/all`, `/api/stock-chart/market-pulse/rotation-trend` (also carries composite top-10 metadata for compare defaults), `/api/stock-chart/market-pulse/industry-compare`, `/api/stock-chart/ths-industry/fund-flow/industry-series`, `/api/stock-chart/market-pulse/scheduler/status`, `/api/stock-chart/market-pulse/snapshot`
- Components: `PageHeader`, `StrongSectors`, `CapitalFlow`, `IndustryRotation`, `RotationTrend`, `IndustryComparePanel`, `IndustryDetailDrawer`

## Maintenance

- 修改前先看 `design/front/index.md` 与 `market-pulse.detail.md`
- 如果改了 API、数据源、compare 默认逻辑或组件结构，同步更新 design

## Frontend API Migration

- Route: `multiple`
- Module: `frontend/src/services/**`
- Detail: `./frontend-api-migration.md`
- Data Source: old Flask/Python APIs, Java Gateway APIs, Postgres, ClickHouse, local files/model runtime
- APIs: migration inventory for `frontend/src/lib/api.ts` and split service files
- Components: N/A
