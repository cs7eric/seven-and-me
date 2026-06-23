## Market Pulse

- Route: `/stock-overview/market`
- Module: `frontend/src/views/stock-overview/market-pulse/index.tsx`
- Detail: `./market-pulse.detail.md`
- Data Source: Postgres 行业资金流日快照, 手动触发时可先刷新当日快照
- APIs: `/api/stock-chart/market-pulse/all`, `/api/stock-chart/market-pulse/rotation-trend`, `/api/stock-chart/market-pulse/scheduler/status`, `/api/stock-chart/market-pulse/snapshot`
- Components: `PageHeader`, `StrongSectors`, `CapitalFlow`, `IndustryRotation`, `RotationTrend`, `IndustryDetailDrawer`
