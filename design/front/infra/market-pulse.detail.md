# Market Pulse

## Overview

This page presents stock-overview market pulse data as a workspace with strong sectors, capital flow, daily rotation, and cross-day rotation trends.
It keeps the route `/stock-overview/market` while reorganizing the implementation into a semantic page module.

## Route

`/stock-overview/market`

## Module

`frontend/src/views/stock-overview/market-pulse/index.tsx`

## Data Sources

- PostgreSQL market pulse daily snapshots
- Market pulse scheduler status

## APIs

- `/api/stock-chart/market-pulse/all`: Load strong sectors, capital flow, and daily rotation blocks
- `/api/stock-chart/market-pulse/rotation-trend`: Load cross-day rank and change-percent trend data
- `/api/stock-chart/market-pulse/scheduler/status`: Load scheduler runtime state
- `/api/stock-chart/market-pulse/snapshot`: Trigger a manual snapshot refresh
- `/api/stock-chart/market-pulse/industry-detail`: Load drill-down details for one picked industry

## Components

- `PageHeader`: Top summary and refresh controls
- `SchedulerStatusBar`: Scheduler health and manual trigger bar
- `SummaryStrip`: Four quick market summary cards
- `StrongSectors`: Strong and weak sectors board
- `CapitalFlow`: Inflow and outflow panels
- `IndustryRotation`: Daily top-N rotation matrix
- `RotationTrend`: Cross-day ranking trend table
- `IndustryDetailDrawer`: Sector drill-down drawer

## Lib

- `format.ts`: Shared display formatting, band colors, and page constants
- `types.ts`: Page-level TypeScript data contracts

## Data Flow

`/api/stock-chart/market-pulse/all` -> page state in `index.tsx` -> extracted sector/flow/rotation components -> UI rendering.

`/api/stock-chart/market-pulse/rotation-trend` -> page state in `index.tsx` -> `RotationTrend` -> UI rendering.

## Maintenance Notes

Before modifying this page, review:

- `design/front/infra/index.md`
- `design/front/infra/market-pulse.detail.md`
- `design/front/reuse/reuse.md`

After modifying this page, update the related design documentation if route, data source, API usage, component structure, or reusable logic changes.
