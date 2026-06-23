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
 * 数据链路总览:
 *
 * 1. 页面接口
 *    - 强势板块 / 行业主力净流入 / 行业轮动(日 Top N):
 *      fetchMarketPulse() -> GET /api/stock-chart/market-pulse/all
 *    - 行业轮动历史趋势:
 *      fetchMarketPulseRotationTrend() -> GET /api/stock-chart/market-pulse/rotation-trend
 *    - 调度状态 / 手动触发:
 *      fetchMarketPulseSchedulerStatus() -> GET /api/stock-chart/market-pulse-scheduler/status
 *      triggerMarketPulseSnapshot() -> POST /api/stock-chart/market-pulse-scheduler/trigger
 *
 * 2. 后端 service
 *    - 聚合接口:
 *      backend.services.stock.market_pulse_service.build_market_pulse()
 *    - 历史趋势:
 *      backend.services.stock.market_pulse_service.build_rotation_trend()
 *    - 当日快照读取/刷新入口:
 *      backend.services.stock.market_pulse_service._get_resolved_snapshot()
 *
 * 3. 原始数据源
 *    - 当前主来源: AkShare
 *      ak.stock_fund_flow_industry()
 *    - 字段: 行业涨跌幅 / 流入资金 / 流出资金 / 净额 / 公司家数 / 领涨股 / 领涨股涨跌幅 / 当前价
 *
 * 4. 持久化方式
 *    - 不直接把“趋势表”持久化; 先持久化“交易日行业快照”, 趋势接口再基于历史快照现拼
 *    - Repository:
 *      backend.repositories.market.market_pulse_pg_repo.MarketPulseRepository
 *    - 写入方法:
 *      replace_trade_day_snapshot(...)
 *    - 读方法:
 *      latest_trade_date(), list_trade_dates(), get_trade_day_rows(), get_trade_day_batch()
 *    - 排名生成:
 *      replace_trade_day_snapshot(...) 内按 change_pct desc 排序并写 rank_by_change
 *
 * 5. 行业轮动/历史趋势怎么来的
 *    - 行业轮动(日 Top N):
 *      读取某交易日 Postgres 快照 -> 取前 N 名 -> 返回 rows[]
 *    - 行业轮动历史趋势:
 *      读取最近 N 个交易日快照 -> 每日取 Top N -> 按行业名聚合 ->
 *      产出 appearances / ranks / changePcts / latestRank / bestRank / avgRank
 *
 * 6. 调度与落盘
 *    - backend.services.scheduler.market_pulse_scheduler
 *    - 盘内: 每 10 分钟刷新一次当日 Postgres 快照
 *    - 收盘: 15:30 再落一次当日完整快照
 *    - 15:35: 刷 90 行业成分股(独立链路, 给行业钻取/成分股相关能力用)
 *
 * 7. 历史补数/冷启动
 *    - Repository.ensure_bootstrapped() 会在库空时尝试导入旧数据:
 *      a) DuckDB: market_pulse_sector_daily
 *      b) JSON: reference/stock-universe/market_pulse/rotation/*.json
 */
import { useCallback, useEffect, useMemo, useState } from "react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { notification } from "@/components/ui/notification"
import {
  fetchMarketPulse,
  fetchIndustryFundFlowIndustryList,
  fetchMarketPulseIndustryCompare,
  fetchMarketPulseRotationTrend,
  fetchMarketPulseSchedulerStatus,
  triggerMarketPulseSnapshot,
} from "@/lib/api"

import { CapitalFlow } from "./components/CapitalFlow"
import { IndustryComparePanel } from "./components/IndustryComparePanel"
import { IndustryDetailDrawer } from "./components/IndustryDetailDrawer"
import { IndustryRotation } from "./components/IndustryRotation"
import { PageHeader, SchedulerStatusBar, SummaryStrip } from "./components/PageHeader"
import { RotationTrend } from "./components/RotationTrend"
import { StrongSectors } from "./components/StrongSectors"
import { INSIDE_REFRESH_MS } from "./lib/format"
import type {
  IndustryCompareResponse,
  IndustryFundFlowIndustryOption,
  MarketPulse,
  RotationTrendData,
  SchedulerStatus,
} from "./lib/types"

const ROTATION_TREND_ALL_DAYS = 365
const ROTATION_TREND_TOP_N = 10
const INDUSTRY_COMPARE_ALL_DAYS = 365
const INDUSTRY_COMPARE_DEFAULT_COUNT = 10

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export default function StockOverviewMarketPulsePage() {
  const [data, setData] = useState<MarketPulse | null>(null)
  const [trend, setTrend] = useState<RotationTrendData | null>(null)
  const [industryCompare, setIndustryCompare] = useState<IndustryCompareResponse | null>(null)
  const [industryCompareLoading, setIndustryCompareLoading] = useState(false)
  const [industryOptions, setIndustryOptions] = useState<IndustryFundFlowIndustryOption[]>([])
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([])
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)

  const compareOptions = useMemo(() => {
    const fromDb = industryOptions.map((item) => item.industry)
    const fromCurrentSnapshot = [
      ...(data?.flow?.inflow ?? []).map((item) => item.name),
      ...((data?.rotation?.rows ?? [])[0]?.items ?? []).map((item) => item.name),
      ...(data?.strong?.top ?? []).map((item) => item.name),
      ...(data?.flow?.outflow ?? []).map((item) => item.name),
    ]
    return [...new Set([...fromDb, ...fromCurrentSnapshot])].filter((item): item is string => Boolean(item))
  }, [data, industryOptions])
  const defaultCompareIndustries = useMemo(() => {
    const compositeTop = [...(trend?.industries ?? [])]
      .filter((item) => item.compositeRank != null && compareOptions.includes(item.name))
      .sort((a, b) => {
        const rankDiff = (a.compositeRank ?? Number.MAX_SAFE_INTEGER) - (b.compositeRank ?? Number.MAX_SAFE_INTEGER)
        if (rankDiff !== 0) return rankDiff
        return (b.compositeScore ?? -Infinity) - (a.compositeScore ?? -Infinity)
      })
      .map((item) => item.name)
      .slice(0, INDUSTRY_COMPARE_DEFAULT_COUNT)
    if (compositeTop.length) return compositeTop

    return [
      ...new Set([
        ...(data?.flow?.inflow ?? []).map((item) => item.name),
        ...((data?.rotation?.rows ?? [])[0]?.items ?? []).map((item) => item.name),
        ...(data?.strong?.top ?? []).map((item) => item.name),
      ]),
    ]
      .filter((item): item is string => Boolean(item) && compareOptions.includes(item))
      .slice(0, INDUSTRY_COMPARE_DEFAULT_COUNT)
  }, [compareOptions, data, trend?.industries])
  const effectiveSelectedIndustries = useMemo(() => {
    const kept = selectedIndustries.filter((item) => compareOptions.includes(item))
    return kept.length ? kept : defaultCompareIndustries
  }, [compareOptions, defaultCompareIndustries, selectedIndustries])
  const trendIndustryMeta = useMemo(
    () =>
      new Map(
        (trend?.industries ?? []).map((item) => [item.name, { compositeRank: item.compositeRank, compositeScore: item.compositeScore }]),
      ),
    [trend?.industries],
  )
  const effectiveIndustryCompare = useMemo<IndustryCompareResponse | null>(() => {
    if (!industryCompare) return null
    return {
      ...industryCompare,
      industries: industryCompare.industries.map((item) => ({
        ...item,
        ...trendIndustryMeta.get(item.name),
      })),
    }
  }, [industryCompare, trendIndustryMeta])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [market, trendData, schedulerStatus, industryList] = await Promise.all([
        fetchMarketPulse(),
        fetchMarketPulseRotationTrend(ROTATION_TREND_ALL_DAYS, ROTATION_TREND_TOP_N).catch(() => null),
        fetchMarketPulseSchedulerStatus().catch(() => null),
        fetchIndustryFundFlowIndustryList(INDUSTRY_COMPARE_ALL_DAYS).catch(() => null),
      ])
      setData(market as MarketPulse)
      if (trendData) setTrend(trendData as RotationTrendData)
      if (schedulerStatus) setScheduler(schedulerStatus as SchedulerStatus)
      if (industryList?.ok) setIndustryOptions(industryList.items)
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
      const trendData = await fetchMarketPulseRotationTrend(ROTATION_TREND_ALL_DAYS, ROTATION_TREND_TOP_N).catch(() => null)
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

  useEffect(() => {
    if (!effectiveSelectedIndustries.length) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      if (!cancelled) setIndustryCompareLoading(true)
    }, 0)
    fetchMarketPulseIndustryCompare(effectiveSelectedIndustries, INDUSTRY_COMPARE_ALL_DAYS)
      .then((result) => {
        if (!cancelled) setIndustryCompare(result)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          notification.error(`行业对比数据加载失败: ${getErrorMessage(error)}`)
        }
      })
      .finally(() => {
        if (!cancelled) setIndustryCompareLoading(false)
      })
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [effectiveSelectedIndustries])

  const handleAddIndustries = useCallback(
    (names: string[]) => {
      const validNames = names.filter((item) => compareOptions.includes(item))
      if (!validNames.length) return
      setSelectedIndustries((prev) => {
        const current = (prev.length ? prev : defaultCompareIndustries).filter((item) => compareOptions.includes(item))
        return [...new Set([...current, ...validNames])]
      })
    },
    [compareOptions, defaultCompareIndustries],
  )

  const handleRemoveIndustry = useCallback(
    (name: string) => {
      setSelectedIndustries((prev) => {
        const current = (prev.length ? prev : defaultCompareIndustries).filter((item) => compareOptions.includes(item))
        return current.filter((item) => item !== name)
      })
    },
    [compareOptions, defaultCompareIndustries],
  )

  const handleResetCompareIndustries = useCallback(() => {
    setSelectedIndustries(defaultCompareIndustries)
  }, [defaultCompareIndustries])

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
        <IndustryComparePanel
          options={compareOptions}
          selected={effectiveSelectedIndustries}
          defaultCount={INDUSTRY_COMPARE_DEFAULT_COUNT}
          loading={industryCompareLoading}
          data={effectiveSelectedIndustries.length ? effectiveIndustryCompare : null}
          onAdd={handleAddIndustries}
          onRemove={handleRemoveIndustry}
          onResetDefault={handleResetCompareIndustries}
        />
      </div>
      <IndustryDetailDrawer name={picked} onClose={() => setPicked(null)} />
    </WorkspaceShell>
  )
}
