/**
 * 行业 / 概念 应用面分析
 *
 * 布局与 application-analysis 1:1 对齐：左侧 target 列表，右侧顶部 ChartHeader + 6 个 Tab。
 * 复用 application-analysis 的 chart 组件：
 *  - ChartCard (K 线) — 同样的 SVG 渲染
 *  - ChartHeader (顶部) — 同样的样式 + 同样的 button 风格
 *  - TechnicalIndicatorPanel (技术指标 Tab) — 同样的面板
 *
 * 区别只在数据：source = eltdx bars.get(kind="index")，persistence 跟 application-analysis 物理隔离。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Building2, ChevronDown, ChevronRight, Eye, Plus, RefreshCw, Search, Sparkles, Target, Trash2 } from "lucide-react"

import AnimatedList from "@/components/AnimatedList"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { WorkspaceShell } from "@/layout/workspace-shell"
import { notification } from "@/components/ui/notification"
import {
  fetchIndustryApplicationKline,
  fetchIndustryApplicationResult,
  fetchIndustryApplicationTargetCodes,
  fetchIndustryApplicationTargets,
  fetchMarketHeatmap,
  refreshIndustryApplication,
  saveIndustryApplicationTargets,
} from "@/lib/api"
import type { HeatmapKind } from "@/lib/api"
import type { ApplicationAnalysisTarget } from "@/lib/api"
import type { StockKlineBar } from "../stock-chart/lib/types"
import type {
  IndustryApplicationIndexBar,
  IndustryApplicationTarget,
  IndustryApplicationTargetCode,
  MarketHeatmapResponse,
} from "./lib/types"

// 共用的 application-analysis 组件
import { ChartCard } from "../application-analysis/components/chart-card"
import { TechnicalIndicatorPanel } from "../stock-chart/components/technical-indicator-panel"

import { NotApplicableCard } from "./components/not-applicable-card"
import { SectorHeatmap } from "./components/sector-heatmap"
import { IndustryFundFlowTable } from "./components/industry-fund-flow-table"

const DEFAULT_HORIZON = { days: 120, segments: 4 }

// =============================================================================
// 数据适配：把 eltdx bar / industry target 转成 application-analysis 期望的格式
// =============================================================================

function eltdxBarToStockBar(bar: IndustryApplicationIndexBar): StockKlineBar {
  const ts = Date.parse(bar.time)
  return {
    timestamp: Number.isFinite(ts) ? ts : Date.now(),
    trade_date: bar.time?.slice(0, 10),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    // eltdx 字段约定: volume_lots = 成交量 (手), amount = 成交额 (元)
    volume: bar.volume_lots,
    turnover: bar.amount,
  }
}

function industryTargetToAppTarget(
  item: IndustryApplicationTarget,
  lastUpdatedAt?: string,
): ApplicationAnalysisTarget {
  return {
    id: item.id,
    target_type: item.target_type as unknown as ApplicationAnalysisTarget["target_type"],
    symbol: item.symbol,
    name: item.name,
    adjust: "qfq", // 行业/概念 无复权概念
    enabled: item.enabled ?? true,
    interval_minutes: item.interval_minutes ?? 60,
    last_updated_at: lastUpdatedAt,
    tags: item.tags,
  }
}

// =============================================================================
// Tab 配置
// =============================================================================

type MainTab = "overview" | "chart" | "ai-direction" | "analysis-detail" | "auction" | "indicator" | "fund-flow"

const TABS: Array<{ value: MainTab; label: string }> = [
  { value: "overview", label: "总览" },
  { value: "chart", label: "K 线" },
  { value: "ai-direction", label: "AI 方向" },
  { value: "analysis-detail", label: "分析详情" },
  { value: "auction", label: "分时" },
  { value: "indicator", label: "技术指标" },
  { value: "fund-flow", label: "资金流" },
]

// =============================================================================
// 主页面
// =============================================================================

export default function IndustryApplicationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeMainTab, setActiveMainTab] = useState<MainTab>("overview")
  const [horizon, setHorizon] = useState<Record<string, number>>(DEFAULT_HORIZON)
  const [targets, setTargets] = useState<IndustryApplicationTarget[]>([])
  const [targetCodes, setTargetCodes] = useState<IndustryApplicationTargetCode[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [previewTarget, setPreviewTarget] = useState<{
    code: string
    target_type: "industry" | "concept"
    name: string
  } | null>(null)

  // 渲染时用的 target (preview 优先)
  const displayedTarget = useMemo(() => {
    if (previewTarget) {
      return {
        id: `${previewTarget.target_type}-${previewTarget.code}`,
        target_type: previewTarget.target_type,
        symbol: previewTarget.code,
        name: previewTarget.name,
        adjust: "qfq" as const,
        enabled: true,
        interval_minutes: 60,
        tags: ["from-self-selected"],
      } as ApplicationAnalysisTarget
    }
    const found = targets.find((t) => t.id === selectedId)
    if (!found) return null
    return industryTargetToAppTarget(found)
  }, [previewTarget, targets, selectedId])

  const [kline, setKline] = useState<IndustryApplicationIndexBar[]>([])
  const [loadingBars, setLoadingBars] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState("")
  const [targetCardCollapsed, setTargetCardCollapsed] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Overview Tab state
  const [heatmapData, setHeatmapData] = useState<MarketHeatmapResponse | null>(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [heatmapAutoRefresh, setHeatmapAutoRefresh] = useState(false)
  // industry / concept / style 三个独立屏, 默认 "industries"
  const [heatmapKind, setHeatmapKind] = useState<HeatmapKind>("industries")

  const latestTargetsRef = useRef<IndustryApplicationTarget[]>([])
  latestTargetsRef.current = targets

  // K 线 拉取 (预览态/已加入都从 eltdx 拉)
  useEffect(() => {
    const target = displayedTarget
    if (!target) {
      setKline([])
      return
    }
    let active = true
    setLoadingBars(true)
    void fetchIndustryApplicationKline(
      target.target_type as "industry" | "concept",
      target.symbol,
      { period: "day", count: 240 },
    )
      .then((data) => {
        if (!active) return
        setKline(data.kline || [])
      })
      .catch(() => {
        if (active) setKline([])
      })
      .finally(() => {
        if (active) setLoadingBars(false)
      })
    return () => {
      active = false
    }
  }, [displayedTarget])

  // 加载 targets + codes
  const loadAll = useCallback(async () => {
    try {
      const [cfg, codes] = await Promise.all([
        fetchIndustryApplicationTargets(),
        fetchIndustryApplicationTargetCodes(),
      ])
      const items = cfg.items || []
      setTargets(items)
      setHorizon({ ...DEFAULT_HORIZON, ...(cfg.horizon || {}) })
      setTargetCodes(codes.items || [])
      if (!selectedId && items.length) {
        setSelectedId(items[0].id)
      }
    } catch (err) {
      notification.danger({
        title: "加载失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
    }
  }, [selectedId])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  // Overview Tab: 拉全市场行业 + 个股热力图
  const loadHeatmap = useCallback(async (kind: HeatmapKind = heatmapKind) => {
    setHeatmapLoading(true)
    try {
      const data = await fetchMarketHeatmap(kind)
      setHeatmapData(data)
    } catch (err) {
      notification.danger({
        title: "热力图加载失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
    } finally {
      setHeatmapLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeMainTab === "overview" && !heatmapData && !heatmapLoading) {
      void loadHeatmap()
    }
  }, [activeMainTab, heatmapData, heatmapLoading, loadHeatmap])

  // kind 切换时主动重拉 (覆盖已有的 heatmapData)
  useEffect(() => {
    if (activeMainTab === "overview") {
      void loadHeatmap(heatmapKind)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatmapKind])

  useEffect(() => {
    if (!heatmapAutoRefresh || activeMainTab !== "overview") return
    const timer = window.setInterval(() => {
      void loadHeatmap(heatmapKind)
    }, 15_000)
    return () => window.clearInterval(timer)
  }, [activeMainTab, heatmapAutoRefresh, heatmapKind, loadHeatmap])

  // URL query: ?target_type=industry&symbol=sh880301 → 预览
  useEffect(() => {
    const symbol = searchParams.get("symbol")
    if (!symbol) return
    const targetType = (searchParams.get("target_type") || "industry") as "industry" | "concept"
    const matchedCode = targetCodes.find((c) => c.code.toLowerCase() === symbol.toLowerCase())
    setPreviewTarget({
      code: symbol,
      target_type: targetType,
      name: matchedCode?.name || symbol,
    })
    setSearchParams((prev) => {
      const sp = new URLSearchParams(prev)
      sp.delete("target_type")
      sp.delete("symbol")
      sp.delete("name")
      return sp
    }, { replace: true })
  }, [searchParams, targetCodes, setSearchParams])

  // ---------------------------------------------------------------------------
  // target 操作
  // ---------------------------------------------------------------------------

  const persist = useCallback(
    async (next: IndustryApplicationTarget[]) => {
      setSaving(true)
      try {
        const updated = await saveIndustryApplicationTargets({
          horizon: { days: horizon.days ?? 120, segments: horizon.segments ?? 4 },
          items: next,
        })
        setTargets(updated.items || [])
        return updated.items || []
      } catch (err) {
        notification.danger({
          title: "保存失败",
          description: err instanceof Error ? err.message : "未知错误",
        })
        throw err
      } finally {
        setSaving(false)
      }
    },
    [horizon],
  )

  const handleAddFromCode = useCallback(
    async (code: IndustryApplicationTargetCode) => {
      const id = `${code.kind}-${code.code}`
      if (latestTargetsRef.current.some((t) => t.id === id)) {
        setSelectedId(id)
        return
      }
      const next: IndustryApplicationTarget = {
        id,
        target_type: code.kind,
        symbol: code.code,
        name: code.name,
        enabled: true,
        interval_minutes: 60,
        tags: ["manual"],
      }
      const updated = [...latestTargetsRef.current, next]
      await persist(updated)
      setSelectedId(next.id)
      notification.success({
        title: "已加入",
        description: `${code.name} · ${code.code}`,
      })
    },
    [persist],
  )

  const handleAddPreview = useCallback(async () => {
    if (!previewTarget) return
    setSaving(true)
    try {
      const next: IndustryApplicationTarget = {
        id: `${previewTarget.target_type}-${previewTarget.code}`,
        target_type: previewTarget.target_type,
        symbol: previewTarget.code,
        name: previewTarget.name,
        enabled: true,
        interval_minutes: 60,
        tags: [],
      }
      const updated = [...latestTargetsRef.current, next]
      await persist(updated)
      setSelectedId(next.id)
      setPreviewTarget(null)
      notification.success({
        title: "已加入应用分析",
        description: `${next.name} · ${next.symbol}`,
      })
    } catch (err) {
      notification.danger({
        title: "加入失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
    } finally {
      setSaving(false)
    }
  }, [previewTarget, persist])

  const handleRemove = useCallback(
    async (id: string) => {
      const next = latestTargetsRef.current.filter((t) => t.id !== id)
      await persist(next)
      if (selectedId === id) {
        setSelectedId(next[0]?.id ?? null)
      }
    },
    [persist, selectedId],
  )

  const handleUpdateTarget = useCallback(
    async (id: string, patch: Partial<IndustryApplicationTarget>) => {
      const next = latestTargetsRef.current.map((t) =>
        t.id === id ? { ...t, ...patch } : t,
      )
      await persist(next)
    },
    [persist],
  )

  const handleTriggerTarget = useCallback(
    async (targetId: string) => {
      setRefreshing(true)
      try {
        const res = await refreshIndustryApplication(targetId)
        if (res.ok) {
          notification.success({
            title: "已刷新",
            description: `1 个标的已落盘`,
          })
          if (displayedTarget?.id === targetId) {
            try {
              const result = await fetchIndustryApplicationResult(targetId)
              const mapped = (result.kline || []).map((b) => ({
                ...b,
                time: b.time,
              })) as IndustryApplicationIndexBar[]
              setKline(mapped)
            } catch {
              // ignore
            }
          }
        } else {
          notification.danger({
            title: "刷新失败",
            description: res.error || "未知错误",
          })
        }
      } finally {
        setRefreshing(false)
      }
    },
    [displayedTarget],
  )

  const handleRefreshAll = useCallback(async () => {
    setRefreshing(true)
    try {
      const res = await refreshIndustryApplication(null)
      if (res.ok) {
        notification.success({
          title: "已刷新",
          description: `${res.count ?? 0} 个标的已落盘`,
        })
        if (displayedTarget) {
          try {
            const result = await fetchIndustryApplicationResult(displayedTarget.id)
            const mapped = (result.kline || []).map((b) => ({
              ...b,
              time: b.time,
            })) as IndustryApplicationIndexBar[]
            setKline(mapped)
          } catch {
            // ignore
          }
        }
      } else {
        notification.danger({
          title: "刷新失败",
          description: res.error || "未知错误",
        })
      }
    } finally {
      setRefreshing(false)
    }
  }, [displayedTarget])

  const handleHorizonChange = useCallback((patch: { days?: number; segments?: number }) => {
    setHorizon((prev) => ({ ...prev, ...patch }))
  }, [])

  // ---------------------------------------------------------------------------
  // 派生
  // ---------------------------------------------------------------------------

  const filteredTargets = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase()
    if (!keyword) return targets
    return targets.filter(
      (t) =>
        t.id.toLowerCase().includes(keyword) ||
        t.symbol.toLowerCase().includes(keyword) ||
        t.name.toLowerCase().includes(keyword) ||
        t.target_type.toLowerCase().includes(keyword),
    )
  }, [targets, searchKeyword])

  const availableCodes = useMemo(() => {
    const targetIdSet = new Set(targets.map((t) => t.id))
    return targetCodes.filter((c) => !targetIdSet.has(`${c.kind}-${c.code}`))
  }, [targetCodes, targets])

  const stockBars: StockKlineBar[] = useMemo(() => kline.map(eltdxBarToStockBar), [kline])
  const selectionColorMap = useMemo<Record<string, string>>(() => ({}), [])

  // ---------------------------------------------------------------------------
  // 渲染
  // ---------------------------------------------------------------------------

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Industry / Concept Application" fullBleed>
      <div className="h-[calc(100svh-4rem)] overflow-hidden rounded-none border-0 bg-[#f6f7f9] p-1 sm:p-1.5">
      <Tabs
        value={activeMainTab}
        onValueChange={(value) => setActiveMainTab(value as MainTab)}
        className="flex h-full min-h-0 flex-col gap-4"
      >
          <header className="flex min-h-0 shrink-0 flex-col gap-2">
            {previewTarget ? (
              <div className="flex items-center gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-amber-800">
                <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-amber-700">
                  <Eye className="size-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">
                    正在预览 {previewTarget.name} · {previewTarget.code}
                  </div>
                  <div className="text-xs text-amber-700/80">
                    仅渲染图表 / 技术指标，AI 分析结果要「加入」后才会保存
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="default"
                  className="h-7 gap-1.5 bg-amber-600 text-white hover:bg-amber-700"
                  onClick={() => void handleAddPreview()}
                  disabled={saving}
                >
                  <Plus className="size-3.5" />
                  加入应用分析
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-amber-800 hover:bg-amber-500/20 hover:text-amber-900"
                  onClick={() => setPreviewTarget(null)}
                >
                  取消预览
                </Button>
              </div>
            ) : null}

            <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
              <TabsList className="bg-transparent p-0">
                {TABS.map((t) => (
                  <TabsTrigger
                    key={t.value}
                    value={t.value}
                    className="data-[state=active]:bg-slate-950 data-[state=active]:text-white"
                  >
                    {t.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
          </header>

          <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
            <TabsContent value="overview" className="m-0 h-full min-h-0 overflow-hidden">
              <SectorHeatmap
                data={heatmapData}
                loading={heatmapLoading}
                onRefresh={() => void loadHeatmap(heatmapKind)}
                autoRefresh={heatmapAutoRefresh}
                onAutoRefreshChange={setHeatmapAutoRefresh}
                kind={heatmapKind}
                onKindChange={setHeatmapKind}
              />
            </TabsContent>

            <div className={activeMainTab === "overview" ? "hidden" : "grid h-full min-h-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]"}>
              <aside className="min-h-0 overflow-y-auto">
                <div className="space-y-4">
                  <IndustryTargetCard
                    targets={filteredTargets}
                    allTargetCount={targets.length}
                    searchKeyword={searchKeyword}
                    setSearchKeyword={setSearchKeyword}
                    selectedId={selectedId}
                    setSelectedId={setSelectedId}
                    expandedId={expandedId}
                    setExpandedId={setExpandedId}
                    collapsed={targetCardCollapsed}
                    setCollapsed={setTargetCardCollapsed}
                    horizon={horizon}
                    onHorizonChange={handleHorizonChange}
                    saving={saving || refreshing}
                    onUpdate={handleUpdateTarget}
                    onRemove={handleRemove}
                    onTrigger={handleTriggerTarget}
                    onRefreshAll={handleRefreshAll}
                  />
                  <IndustryAddCard codes={availableCodes} onAdd={(code) => void handleAddFromCode(code)} />
                </div>
              </aside>

              <div className="min-h-0 min-w-0 overflow-hidden">
                <TabsContent value="chart" className="m-0 h-full min-h-0 overflow-hidden">
                  {displayedTarget ? (
                    <ChartCard
                      collapsed={false}
                      onToggle={() => undefined}
                      selectedSymbol={displayedTarget.symbol}
                      bars={stockBars}
                      overlays={[]}
                      selectionColors={selectionColorMap}
                      selectedBarTimestamps={[]}
                      onSelectionChange={() => undefined}
                      onAnalyzeSelection={() => undefined}
                      loadingBars={loadingBars}
                    />
                  ) : (
                    <EmptyHint />
                  )}
                </TabsContent>

                <TabsContent value="ai-direction" className="m-0 h-full min-h-0 overflow-auto">
                  <NotApplicableCard
                    title="AI 方向"
                    description="板块 / 概念指数没有个股层面的舆情 / 产业链关联数据, 暂不做 AI 方向分析。"
                  />
                </TabsContent>

                <TabsContent value="analysis-detail" className="m-0 h-full min-h-0 overflow-auto">
                  <NotApplicableCard
                    title="分析详情"
                    description="板块 / 概念指数的 LLM 综合分析由后续接入, 当前先用技术指标 + K 线即可判读。"
                  />
                </TabsContent>

                <TabsContent value="auction" className="m-0 h-full min-h-0 overflow-auto">
                  <NotApplicableCard
                    title="分时"
                    description="板块指数本身没有日内分时, 当前 tab 仅对个股有意义。"
                  />
                </TabsContent>

                <TabsContent value="indicator" className="m-0 h-full min-h-0 overflow-auto">
                  {displayedTarget && stockBars.length > 0 ? (
                    <TechnicalIndicatorPanel
                      bars={stockBars}
                      indexBarsMap={null}
                      breadth={null}
                      breadthSeries={null}
                      stockMeta={null}
                    />
                  ) : (
                    <NotApplicableCard
                      title="技术指标"
                      description={
                        displayedTarget
                          ? "暂无 K 线数据, 请先刷新。"
                          : "请先选择左侧行业 / 概念。"
                      }
                    />
                  )}
                </TabsContent>

                <TabsContent value="fund-flow" className="m-0 h-full min-h-0 overflow-auto">
                  <IndustryFundFlowTable />
                </TabsContent>
              </div>
            </div>
            </main>
          </Tabs>
      </div>
    </WorkspaceShell>
  )
}

// =============================================================================
// Tabs 组件导入 (放末尾, 因为下面要用)
// =============================================================================

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

// =============================================================================
// 左侧 target 列表卡 (复用 TargetCard 的视觉风格, 不带 stock search)
// =============================================================================

interface IndustryTargetCardProps {
  targets: IndustryApplicationTarget[]
  allTargetCount: number
  searchKeyword: string
  setSearchKeyword: (value: string) => void
  selectedId: string | null
  setSelectedId: (id: string) => void
  expandedId: string | null
  setExpandedId: React.Dispatch<React.SetStateAction<string | null>>
  collapsed: boolean
  setCollapsed: React.Dispatch<React.SetStateAction<boolean>>
  horizon: Record<string, number>
  onHorizonChange: (patch: { days?: number; segments?: number }) => void
  saving: boolean
  onUpdate: (id: string, patch: Partial<IndustryApplicationTarget>) => void | Promise<void>
  onRemove: (id: string) => void | Promise<void>
  onTrigger: (id: string) => void | Promise<void>
  onRefreshAll: () => void
}

function IndustryTargetCard(props: IndustryTargetCardProps) {
  const {
    targets,
    allTargetCount,
    searchKeyword,
    setSearchKeyword,
    selectedId,
    setSelectedId,
    expandedId,
    setExpandedId,
    collapsed,
    setCollapsed,
    horizon,
    onHorizonChange,
    saving,
    onUpdate,
    onRemove,
    onTrigger,
    onRefreshAll,
  } = props

  return (
    <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Target className="size-4 text-slate-600" />
              Watchlist
            </CardTitle>
            <CardDescription>reference/industry-application/targets.json</CardDescription>
          </div>
          <Button
            className="rounded-xl"
            size="icon-sm"
            variant="ghost"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "展开 Watchlist" : "折叠 Watchlist"}
          >
            {collapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              placeholder="搜索行业 / 概念 · 名称 / 代码"
              className="w-full rounded-xl border border-slate-200 bg-white pl-7 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
            />
          </div>
          {collapsed && !searchKeyword.trim() ? null : (
            <AnimatedList
              items={targets.map((t) => ({ data: t }))}
              selectedIndex={targets.findIndex((t) => t.id === selectedId)}
              onItemSelect={(item) => {
                setSelectedId(item.data.id)
                if (!collapsed) {
                  setExpandedId((current) => (current === item.data.id ? null : item.data.id))
                }
              }}
              renderItem={(item) => {
                const target = item.data
                const isExpanded = !collapsed && expandedId === target.id
                const isSelected = target.id === selectedId
                const Icon = target.target_type === "industry" ? Building2 : Sparkles
                return (
                  <div
                    className={`rounded-2xl border transition ${
                      isSelected ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white hover:border-slate-400"
                    }`}
                  >
                    <div className="flex w-full items-center justify-between gap-2 px-3 py-3 text-left">
                      <div className="flex min-w-0 items-center gap-2">
                        {!collapsed ? (
                          isExpanded ? (
                            <ChevronDown className="size-3.5 text-slate-500" />
                          ) : (
                            <ChevronRight className="size-3.5 text-slate-500" />
                          )
                        ) : null}
                        <span
                          className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${
                            target.target_type === "industry"
                              ? "bg-blue-500/10 text-blue-700"
                              : "bg-violet-500/10 text-violet-700"
                          }`}
                        >
                          <Icon className="size-3.5" />
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                            <span className="truncate">{target.name}</span>
                            <span className="text-slate-400">· {target.symbol}</span>
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                            每 {target.interval_minutes ?? 60} 分钟
                            {target.enabled !== false ? (
                              <Badge className="rounded-full border-emerald-200 bg-emerald-50 text-emerald-700" variant="outline">
                                启用
                              </Badge>
                            ) : (
                              <Badge className="rounded-full border-slate-200 bg-slate-100 text-slate-500" variant="outline">
                                停用
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                      <Badge className="rounded-full border-slate-200 bg-white text-slate-700" variant="outline">
                        {target.target_type === "industry" ? "行业" : "概念"}
                      </Badge>
                    </div>
                    {isExpanded ? (
                      <div
                        className="space-y-3 border-t border-slate-100 bg-slate-50/60 px-3 py-3"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <Button
                            size="sm"
                            variant="outline"
                            className="rounded-xl"
                            onClick={() =>
                              void onUpdate(target.id, { enabled: !(target.enabled ?? true) })
                            }
                          >
                            {target.enabled !== false ? "停用" : "启用"}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => void onTrigger(target.id)}
                          >
                            <RefreshCw className="mr-1 size-3.5" />
                            立即刷新
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="rounded-xl text-slate-500"
                            onClick={() => void onRemove(target.id)}
                          >
                            <Trash2 className="mr-1 size-3.5" />
                            删除
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                )
              }}
              emptyMessage={
                searchKeyword.trim()
                  ? "没有匹配的行业 / 概念。"
                  : allTargetCount === 0
                    ? "还没有目标, 从右侧「加入新标的」添加。"
                    : "没有匹配的目标。"
              }
              maxHeight={collapsed ? "max-h-[28vh]" : "max-h-[40vh]"}
              className=""
              itemClassName=""
            />
          )}
        </div>
        {!collapsed ? (
          <div className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="text-xs font-semibold text-slate-600">数据范围（horizon）</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                天数
                <input
                  type="number"
                  min={30}
                  value={horizon.days}
                  onChange={(event) => onHorizonChange({ days: Number(event.target.value) || 120 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                段数
                <input
                  type="number"
                  min={1}
                  value={horizon.segments}
                  onChange={(event) => onHorizonChange({ segments: Number(event.target.value) || 4 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                className="rounded-xl"
                size="sm"
                disabled={saving}
                onClick={() => void onRefreshAll()}
              >
                全部刷新
              </Button>
            </div>
            <div className="text-xs text-slate-500">
              注: 行业 / 概念 暂无调度器, 数据由「全部刷新」/「立即刷新」手动落盘
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

// =============================================================================
// 加入新标的卡 (industry/concept 代码表)
// =============================================================================

interface IndustryAddCardProps {
  codes: IndustryApplicationTargetCode[]
  onAdd: (code: IndustryApplicationTargetCode) => void
}

function IndustryAddCard({ codes, onAdd }: IndustryAddCardProps) {
  const [filter, setFilter] = useState("")
  const industry = useMemo(
    () =>
      codes.filter(
        (c) =>
          c.kind === "industry" &&
          (filter.trim() === "" ||
            c.name.toLowerCase().includes(filter.trim().toLowerCase()) ||
            c.code.toLowerCase().includes(filter.trim().toLowerCase())),
      ),
    [codes, filter],
  )
  const concept = useMemo(
    () =>
      codes.filter(
        (c) =>
          c.kind === "concept" &&
          (filter.trim() === "" ||
            c.name.toLowerCase().includes(filter.trim().toLowerCase()) ||
            c.code.toLowerCase().includes(filter.trim().toLowerCase())),
      ),
    [codes, filter],
  )
  return (
    <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Plus className="size-4 text-slate-600" />
          加入新标的
        </CardTitle>
        <CardDescription>来自 index_codes.py 静态全集</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Input
          placeholder="搜索名称 / 代码"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8 text-xs"
        />
        <ScrollArea className="max-h-[260px]">
          <div className="space-y-3 p-1">
            {industry.length > 0 ? (
              <Group
                title={`行业 (${industry.length})`}
                icon={<Building2 className="size-3" />}
                tone="text-blue-700"
                items={industry}
                onAdd={onAdd}
              />
            ) : null}
            {concept.length > 0 ? (
              <Group
                title={`概念 (${concept.length})`}
                icon={<Sparkles className="size-3" />}
                tone="text-violet-700"
                items={concept}
                onAdd={onAdd}
              />
            ) : null}
            {industry.length === 0 && concept.length === 0 ? (
              <div className="px-2 py-4 text-center text-xs text-slate-400">无可加入的标的</div>
            ) : null}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

function Group({
  title,
  icon,
  tone,
  items,
  onAdd,
}: {
  title: string
  icon: React.ReactNode
  tone: string
  items: IndustryApplicationTargetCode[]
  onAdd: (c: IndustryApplicationTargetCode) => void
}) {
  return (
    <div>
      <div
        className={`mb-1 flex items-center gap-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider ${tone}`}
      >
        {icon} {title}
      </div>
      <div className="space-y-0.5">
        {items.map((c) => (
          <button
            key={c.code}
            onClick={() => onAdd(c)}
            className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left transition hover:border-slate-200 hover:bg-slate-50"
          >
            <Plus className="size-3 shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-slate-800">{c.name}</div>
              <div className="truncate font-mono text-[10px] text-slate-400">{c.code}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function EmptyHint() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
      <Building2 className="size-10 opacity-30" />
      <div className="text-sm">请从左侧加入一个行业 / 概念</div>
      <div className="text-xs">数据源: eltdx · 持久化: reference/industry-application/</div>
    </div>
  )
}
