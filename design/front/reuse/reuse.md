## Page: Market Pulse

### Components

#### PageHeader
- Path: `frontend/src/views/stock-overview/market-pulse/components/PageHeader.tsx`
- Purpose: Render the page hero, refresh controls, and current snapshot metadata.
- Reuse Scope: Current page only
- Props Summary:
  - `onRefresh`: Refresh handler
  - `loading`: Refresh loading state
  - `scheduler`: Scheduler status payload
  - `market`: Market pulse snapshot payload
- Notes: Keeps route-level orchestration out of the page entry file.

#### SummaryStrip
- Path: `frontend/src/views/stock-overview/market-pulse/components/PageHeader.tsx`
- Purpose: Render the four summary cards derived from the current market pulse snapshot.
- Reuse Scope: Same domain pages
- Props Summary:
  - `data`: Market pulse snapshot
- Notes: Reads the first entries from strong-sector and flow lists.

#### SchedulerStatusBar
- Path: `frontend/src/views/stock-overview/market-pulse/components/PageHeader.tsx`
- Purpose: Show scheduler runtime status and expose the manual snapshot trigger.
- Reuse Scope: Same domain pages
- Props Summary:
  - `status`: Scheduler status payload
  - `onTrigger`: Manual trigger handler
- Notes: Useful for other scheduler-backed stock pages with similar controls.

#### StrongSectors
- Path: `frontend/src/views/stock-overview/market-pulse/components/StrongSectors.tsx`
- Purpose: Render strong and weak sector boards from the current snapshot.
- Reuse Scope: Same domain pages
- Props Summary:
  - `data`: Strong-sector block from market pulse payload
  - `onPick`: Drill-down callback
- Notes: Encapsulates the strong/weak sector UI and status badges.

#### CapitalFlow
- Path: `frontend/src/views/stock-overview/market-pulse/components/CapitalFlow.tsx`
- Purpose: Render net inflow and outflow panels for sector capital flow.
- Reuse Scope: Same domain pages
- Props Summary:
  - `data`: Flow block from market pulse payload
  - `onPick`: Drill-down callback
- Notes: Owns the flow bar visualization and per-row metadata.

#### IndustryRotation
- Path: `frontend/src/views/stock-overview/market-pulse/components/IndustryRotation.tsx`
- Purpose: Render the daily top-N rotation matrix by trading date.
- Reuse Scope: Same domain pages
- Props Summary:
  - `data`: Rotation block from market pulse payload
  - `onRefreshSnapshot`: Snapshot refresh handler
  - `onPick`: Drill-down callback
- Notes: Suitable for other rank-matrix pages that follow a date x rank layout.

#### RotationTrend
- Path: `frontend/src/views/stock-overview/market-pulse/components/RotationTrend.tsx`
- Purpose: Render cross-day appearance counts, rank migration, and latest trend state.
- Reuse Scope: Same domain pages
- Props Summary:
  - `data`: Rotation trend payload
  - `onPick`: Drill-down callback
- Notes: Keeps trend-table rendering separate from data fetching.

#### IndustryDetailDrawer
- Path: `frontend/src/views/stock-overview/market-pulse/components/IndustryDetailDrawer.tsx`
- Purpose: Render the sector drill-down drawer with leading-stock detail and mini charts.
- Reuse Scope: Same domain pages
- Props Summary:
  - `name`: Picked industry name
  - `onClose`: Close handler
- Notes: Fetches its own detail payload once opened.

#### IndustryComparePanel
- Path: `frontend/src/views/stock-overview/market-pulse/components/IndustryComparePanel.tsx`
- Purpose: Render the default composite top-10 multi-industry comparison, allow multi-select industry additions, expose a net-flow / rank chart toggle, and show a compact summary table.
- Reuse Scope: Same domain pages
- Props Summary:
  - `options`: Full industry option names
  - `selected`: Currently selected industries
  - `defaultCount`: Default industry count label
  - `loading`: Historical compare loading state
  - `data`: Multi-industry compare payload
  - `onAdd`: Add multiple industries from the select list
  - `onRemove`: Remove one selected industry
  - `onResetDefault`: Reset to the default top industries
- Notes: Encapsulates the page's ECharts setup, composite-default compare presentation, and compact summary table.

### Lib Methods

#### bandColor
- Path: `frontend/src/views/stock-overview/market-pulse/lib/format.ts`
- Purpose: Map change percent to one of the nine pulse color bands.
- Input: `number | null | undefined`
- Output: Hex color string
- Reuse Scope: Same domain pages

#### bandFg
- Path: `frontend/src/views/stock-overview/market-pulse/lib/format.ts`
- Purpose: Pick readable foreground color for a band-colored cell.
- Input: `number | null | undefined`
- Output: Hex color string
- Reuse Scope: Same domain pages

#### fmtPct
- Path: `frontend/src/views/stock-overview/market-pulse/lib/format.ts`
- Purpose: Format change-percent style numbers for display.
- Input: Numeric percent value and optional precision
- Output: Formatted percentage string
- Reuse Scope: Global reusable

#### fmtAmount
- Path: `frontend/src/views/stock-overview/market-pulse/lib/format.ts`
- Purpose: Format numeric amounts into `亿` or `万`.
- Input: Numeric amount
- Output: Readable amount string
- Reuse Scope: Same domain pages

#### fmtYi
- Path: `frontend/src/views/stock-overview/market-pulse/lib/format.ts`
- Purpose: Format a raw yuan value as signed `亿`.
- Input: Numeric amount
- Output: Signed `亿` string
- Reuse Scope: Same domain pages
