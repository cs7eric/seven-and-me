/**
 * Maintenance Notice:
 * Before modifying this page, review the related documentation under:
 * - design/front/infra/index.md
 * - design/front/infra/market-pulse.detail.md
 * - design/front/reuse/reuse.md
 *
 * If this page's route, data source, API usage, component structure,
 * or reusable logic changes, update the corresponding design documents.
 */

/**
 * Stock Overview · 行情 (Market Pulse) 页面.
 *
 * 数据源说明:
 *  1. 强势板块 / 行业主力净流入 / 行业轮动
 *     - 前端: fetchMarketPulse() -> GET /api/stock-chart/market-pulse/all
 *     - 后端: backend.services.stock.market_pulse_service.build_market_pulse()
 *     - 数据形态: 读 Postgres 行业资金流日快照
 *
 *  2. 行业轮动历史趋势
 *     - 前端: fetchMarketPulseRotationTrend()
 *     - 接口: GET /api/stock-chart/market-pulse/rotation-trend
 *     - 后端: backend.services.stock.market_pulse_service.build_rotation_trend()
 *     - 数据形态: 基于 Postgres 历史快照拼跨日序列
 */
import { useCallback, useEffect, useState } from "react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { notification } from "@/components/ui/notification"
import {
  fetchMarketPulse,
  fetchMarketPulseRotationTrend,
  fetchMarketPulseSchedulerStatus,
  triggerMarketPulseSnapshot,
} from "@/lib/api"

import { CapitalFlow } from "./components/CapitalFlow"
import { IndustryDetailDrawer } from "./components/IndustryDetailDrawer"
import { IndustryRotation } from "./components/IndustryRotation"
import { PageHeader, SchedulerStatusBar, SummaryStrip } from "./components/PageHeader"
import { RotationTrend } from "./components/RotationTrend"
import { StrongSectors } from "./components/StrongSectors"
import { INSIDE_REFRESH_MS } from "./lib/format"
import type { MarketPulse, RotationTrendData, SchedulerStatus } from "./lib/types"

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export default function StockOverviewMarketPulsePage() {
  const [data, setData] = useState<MarketPulse | null>(null)
  const [trend, setTrend] = useState<RotationTrendData | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [market, trendData, schedulerStatus] = await Promise.all([
        fetchMarketPulse(),
        fetchMarketPulseRotationTrend(10, 10).catch(() => null),
        fetchMarketPulseSchedulerStatus().catch(() => null),
      ])
      setData(market as MarketPulse)
      if (trendData) setTrend(trendData as RotationTrendData)
      if (schedulerStatus) setScheduler(schedulerStatus as SchedulerStatus)
    } catch (error: unknown) {
      notification.error(`行情数据加载失败: ${getErrorMessage(error)}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshSnapshot = useCallback(async () => {
    setLoading(true)
    try {
      const market = await fetchMarketPulse({ refreshRotation: true })
      setData(market as MarketPulse)
      notification.success("今日 Top 快照已落盘")
      const trendData = await fetchMarketPulseRotationTrend(10, 10).catch(() => null)
      if (trendData) setTrend(trendData as RotationTrendData)
    } catch (error: unknown) {
      notification.error(`刷新快照失败: ${getErrorMessage(error)}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const triggerScheduler = useCallback(async () => {
    setLoading(true)
    try {
      await triggerMarketPulseSnapshot()
      notification.success("已手动触发今日 snapshot")
      await load()
    } catch (error: unknown) {
      notification.error(`手动 snapshot 失败: ${getErrorMessage(error)}`)
    } finally {
      setLoading(false)
    }
  }, [load])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    if (!scheduler?.isTradeTime) return
    const timer = window.setInterval(() => {
      void load()
    }, INSIDE_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [scheduler?.isTradeTime, load])

  return (
    <WorkspaceShell sectionLabel="Stock Overview" sectionUrl="/stock-overview" pageTitle="market pulse">
      <div className="h-[calc(100svh-4rem)] space-y-4 overflow-y-auto p-3 sm:p-4">
        <PageHeader
          onRefresh={load}
          loading={loading}
          fetchedAt={data?.strong?.fetchedAt}
          flowElapsedMs={data?.flow?.elapsedMs}
          scheduler={scheduler}
          market={data}
        />
        <SchedulerStatusBar status={scheduler} onTrigger={triggerScheduler} />
        {data ? <SummaryStrip data={data} /> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <StrongSectors data={data?.strong} onPick={setPicked} />
          <CapitalFlow data={data?.flow} onPick={setPicked} />
        </div>
        <IndustryRotation data={data?.rotation} onRefreshSnapshot={refreshSnapshot} onPick={setPicked} />
        <RotationTrend data={trend} onPick={setPicked} />
      </div>
      <IndustryDetailDrawer name={picked} onClose={() => setPicked(null)} />
    </WorkspaceShell>
  )
}
