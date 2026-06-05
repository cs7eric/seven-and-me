import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { WorkspaceShell } from "@/layout/workspace-shell"
import {
  controlApplicationAnalysisScheduler,
  fetchApplicationAnalysisResult,
  fetchApplicationAnalysisSchedulerStatus,
  fetchApplicationAnalysisTargets,
  fetchStockKlines,
  listApplicationAnalysisRecent30Full,
  refreshApplicationAnalysisRecent30,
  runApplicationAnalysis,
  saveApplicationAnalysisTargets,
  triggerApplicationAnalysis,
  type ApplicationAnalysisDailySnapshotResponse,
  type ApplicationAnalysisRecent30FullItem,
  type ApplicationAnalysisSchedulerStatus,
  type ApplicationAnalysisTarget,
} from "@/lib/api"
import type { ChartPanelSelectionItem } from "../stock-chart/components/chart-panel"
import type {
  ApplicationAnalysisResponse,
  StockAdjust,
  StockKlineBar,
  StockSearchItem,
  StockTargetType,
} from "../stock-chart/lib/types"

import { AIDirectionCard } from "./components/ai-direction-card"
import { Alerts } from "./components/alerts"
import { AnalysisDetail } from "./components/analysis-detail"
import { AuctionTab } from "./components/auction-tab"
import { ChartCard } from "./components/chart-card"
import { ChartHeader } from "./components/chart-header"
import { FundFlowTab } from "./components/fund-flow-tab"
import { IntradayAnalysisDialog } from "./components/intraday-analysis-dialog"
import { SelectionPanel } from "./components/selection-panel"
import { TargetCard, type HorizonPatch } from "./components/target-card"
import { TechnicalIndicatorTab } from "./components/technical-indicator-tab"
import { notification } from "@/components/ui/notification"
import { DEFAULT_HORIZON, SELECTION_COLORS } from "./lib/constants"
import {
  asOverlayAnnotations,
  textList,
} from "./lib/format"

function formatTradeDateFromTimestamp(timestamp?: number | null) {
  if (typeof timestamp !== "number" || !Number.isFinite(timestamp) || timestamp <= 0) return null
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
  return formatter.format(new Date(timestamp))
}

export default function ApplicationAnalysisPage() {
  type MainTab = "chart" | "ai-direction" | "analysis" | "auction" | "ma-support" | "fund-flow"
  const [activeMainTab, setActiveMainTab] = useState<MainTab>("chart")
  const [targets, setTargets] = useState<ApplicationAnalysisTarget[]>([])
  const [horizon, setHorizon] = useState<Record<string, number>>(DEFAULT_HORIZON)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [adjust, setAdjust] = useState<StockAdjust>("qfq")
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [loadingBars, setLoadingBars] = useState(false)
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const persistTimerRef = useRef<number | null>(null)
  const latestTargetsRef = useRef<ApplicationAnalysisTarget[]>([])
  const latestHorizonRef = useRef<Record<string, number>>({ ...DEFAULT_HORIZON })
  const [result, setResult] = useState<ApplicationAnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [scheduler, setScheduler] = useState<ApplicationAnalysisSchedulerStatus | null>(null)
  const [searchKeyword, setSearchKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [targetCardCollapsed, setTargetCardCollapsed] = useState(false)
  const [selectionCardCollapsed, setSelectionCardCollapsed] = useState(false)
  const [dailySnapshotsFull, setDailySnapshotsFull] = useState<ApplicationAnalysisRecent30FullItem[]>([])
  const [dailySnapshotsLoading, setDailySnapshotsLoading] = useState(false)
  const [dailyRefreshing, setDailyRefreshing] = useState(false)
  const [dailyLastRefreshAt, setDailyLastRefreshAt] = useState<string | null>(null)
  const [selectedChartItems, setSelectedChartItems] = useState<ChartPanelSelectionItem[]>([])
  const selectedBarTimestamps: number[] = selectedChartItems
    .filter((item): item is Extract<ChartPanelSelectionItem, { kind: "bar" }> => item.kind === "bar")
    .map((item) => item.bar.timestamp)
  const [analysisFocusKey, setAnalysisFocusKey] = useState<string | null>(null)
  const [intradayDialogOpen, setIntradayDialogOpen] = useState(false)
  const [intradayBar, setIntradayBar] = useState<Extract<ChartPanelSelectionItem, { kind: "bar" }> | null>(null)
  const selectionPanelRef = useRef<HTMLDivElement | null>(null)

  const selected = useMemo(() => targets.find((item) => item.id === selectedId) || null, [targets, selectedId])

  const refreshTargets = useCallback(async () => {
    try {
      const data = await fetchApplicationAnalysisTargets()
      const items = data.items || []
      const configHorizon = (data.config?.horizon as Record<string, number> | undefined) || {}
      setTargets(items)
      latestTargetsRef.current = items
      setHorizon({ ...DEFAULT_HORIZON, ...configHorizon })
      latestHorizonRef.current = { ...DEFAULT_HORIZON, ...configHorizon }
      if (!selectedId && items.length) {
        // 优先默认选中上证指数 000001（symbol 匹配 index-sh000001 / sh000001 / 000001）
        const preferred =
          items.find((item) => {
            const symbol = (item.symbol || "").toLowerCase()
            const id = (item.id || "").toLowerCase()
            return symbol === "000001" || symbol === "sh000001" || id.endsWith("-000001") || id === "sh000001"
          }) || items[0]
        setSelectedId(preferred.id)
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载目标列表失败"
      setError("加载目标列表失败")
      notification.danger({ title: "加载目标列表失败", description: msg })
    }
  }, [selectedId])

  const refreshScheduler = useCallback(async () => {
    try {
      const status = await fetchApplicationAnalysisSchedulerStatus()
      setScheduler(status)
    } catch {
      setScheduler(null)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshTargets()
    void refreshScheduler()
    const id = window.setInterval(() => {
      void refreshScheduler()
    }, 5000)
    return () => {
      window.clearInterval(id)
      if (persistTimerRef.current !== null) {
        window.clearTimeout(persistTimerRef.current)
        persistTimerRef.current = null
      }
      const snapshotTargets = [...latestTargetsRef.current]
      const snapshotHorizon = { ...latestHorizonRef.current }
      void saveApplicationAnalysisTargets({
        horizon: {
          days: Number(snapshotHorizon.days) || 120,
          segments: Number(snapshotHorizon.segments) || 4,
          monthly_keep: Number(snapshotHorizon.monthly_keep) || 6,
          weekly_keep: Number(snapshotHorizon.weekly_keep) || 12,
        },
        items: snapshotTargets,
      }).catch(() => {
        /* 静默吞掉卸载期错误 */
      })
    }
  }, [refreshTargets, refreshScheduler])

  useEffect(() => {
    if (!selected) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBars([])
      return
    }
    let active = true
    setLoadingBars(true)
    void fetchStockKlines({
      targetType: selected.target_type as StockTargetType,
      symbol: selected.symbol,
      name: selected.name,
      period: "1d",
      adjust: (selected.adjust as StockAdjust) || adjust,
    })
      .then((data) => {
        if (active) setBars(data.items)
      })
      .catch(() => {
        if (active) setBars([])
      })
      .finally(() => {
        if (active) setLoadingBars(false)
      })
    return () => {
      active = false
    }
  }, [selected, adjust])

  useEffect(() => {
    if (!selected) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setResult(null)
      setSelectedChartItems([])
      setAnalysisFocusKey(null)
      return
    }
    let active = true
    void fetchApplicationAnalysisResult(selected.id)
      .then((data) => {
        if (!active) return
        setResult(data as unknown as ApplicationAnalysisResponse)
      })
      .catch(() => {
        if (active) {
          setResult(null)
        }
      })
    return () => {
      active = false
    }
  }, [selected, selectedId])

  const analysis = result?.analysis_result
  const dataQuality = (analysis?.data_quality as Record<string, unknown> | undefined) || {}
  const overlays = useMemo(() => asOverlayAnnotations(analysis?.overlay_annotations), [analysis])
  const warnings = textList(dataQuality.warnings)
  const errors = textList(dataQuality.errors)
  const selectionColorMap = useMemo(
    () =>
      Object.fromEntries(
        selectedChartItems.map((item, index) => [item.key, SELECTION_COLORS[index % SELECTION_COLORS.length]]),
      ) as Record<string, string>,
    [selectedChartItems],
  )

  // 用户在 K 线上新增选中时，自动折叠左侧 Watchlist，给右侧更多空间
  const prevSelectionCountRef = useRef(0)
  useEffect(() => {
    if (selectedChartItems.length > prevSelectionCountRef.current) {
      setTargetCardCollapsed(true)
    }
    prevSelectionCountRef.current = selectedChartItems.length
  }, [selectedChartItems])

  const selectedBarPrevClose = useMemo(() => {
    const map: Record<string, number | null> = {}
    selectedChartItems.forEach((item) => {
      if (item.kind !== "bar") {
        map[item.key] = null
        return
      }
      const index = bars.findIndex((bar) => bar.timestamp === item.bar.timestamp)
      const prev = index > 0 ? bars[index - 1] : null
      map[item.key] = prev ? prev.close : null
    })
    return map
  }, [selectedChartItems, bars])

  const selectedBarPrevVolume = useMemo(() => {
    const map: Record<string, number | null> = {}
    selectedChartItems.forEach((item) => {
      if (item.kind !== "bar") {
        map[item.key] = null
        return
      }
      const index = bars.findIndex((bar) => bar.timestamp === item.bar.timestamp)
      const prev = index > 0 ? bars[index - 1] : null
      map[item.key] = prev ? prev.volume : null
    })
    return map
  }, [selectedChartItems, bars])

  const selectedBarPrevTurnover = useMemo(() => {
    const map: Record<string, number | null> = {}
    selectedChartItems.forEach((item) => {
      if (item.kind !== "bar") {
        map[item.key] = null
        return
      }
      const index = bars.findIndex((bar) => bar.timestamp === item.bar.timestamp)
      const prev = index > 0 ? bars[index - 1] : null
      map[item.key] = prev && typeof prev.turnover === "number" ? prev.turnover : null
    })
    return map
  }, [selectedChartItems, bars])

  const handleRemoveSelectionItem = useCallback((item: ChartPanelSelectionItem) => {
    setSelectedChartItems((current) => current.filter((candidate) => candidate.key !== item.key))
    setAnalysisFocusKey((current) => (current === item.key ? null : current))
  }, [])

  const handleClearSelectionItems = useCallback(() => {
    setSelectedChartItems([])
    setAnalysisFocusKey(null)
  }, [])

  const handleRun = async () => {
    if (!selected) return
    try {
      setRunning(true)
      setError(null)
      setInfo(null)
      try {
        const response = await runApplicationAnalysis({
          targetType: selected.target_type as StockTargetType,
          symbol: selected.symbol,
          name: selected.name,
          adjust: (selected.adjust as StockAdjust) || adjust,
        })
        setResult(response)
        setInfo("分析完成（单次 30 日 K 入口，仅用于手动快速验证；定时任务会用 120 日 / 4 段入口）。")
        notification.success({
          title: "Application Analysis 已完成",
          description: `${selected.name} · ${selected.symbol}`,
        })
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Application Analysis 失败"
        setError(msg)
        notification.danger({ title: "Application Analysis 失败", description: msg })
      }
    } finally {
      setRunning(false)
    }
  }

  const refreshDailySnapshots = useCallback(async (targetId: string) => {
    try {
      setDailySnapshotsLoading(true)
      const data = await listApplicationAnalysisRecent30Full(targetId, 60)
      const items = (data.items || []).slice().sort((a, b) => (a.date < b.date ? 1 : -1))
      setDailySnapshotsFull(items)
      if (items.length) {
        setDailyLastRefreshAt(items[0].updated_at)
      } else {
        setDailyLastRefreshAt(null)
      }
    } catch {
      setDailySnapshotsFull([])
      setDailyLastRefreshAt(null)
    } finally {
      setDailySnapshotsLoading(false)
    }
  }, [])

  const handleRefreshDaily = useCallback(async () => {
    if (!selected) return
    try {
      setDailyRefreshing(true)
      setError(null)
      setInfo(null)
      const rawRes = await refreshApplicationAnalysisRecent30(selected.id)
      // 后端刷新接口额外返回 updated / skip_reason 字段，目前 ApplicationAnalysisDailySnapshotResponse
      // 还未包含，这里只在 application-analysis 内做局部增强，不改动共享 api.ts。
      const res = rawRes as ApplicationAnalysisDailySnapshotResponse & {
        updated?: boolean
        skip_reason?: string
      }
      if (!res.ok) {
        const msg = res.error || "刷新当日 AI 整体判断失败"
        setError(msg)
        notification.danger({ title: "刷新当日 AI 整体判断失败", description: msg })
        return
      }
      if (res.updated === false) {
        // AI 报无数据 / 返回字段缺失：不改写文件，沿用旧判断
        const reasonLabel =
          res.skip_reason === "no_new_data"
            ? "AI 未返回有效的整体判断字段"
            : "AI 未返回有效结果"
        setInfo(
          `${selected.name} 今日整体判断已保持原样（${res.date || "今日"}）：${reasonLabel}，未做更新。`,
        )
        notification.info({
          title: "今日判断已保持原样",
          description: `${selected.name} · ${res.date || "今日"}（${reasonLabel}）`,
        })
        await refreshDailySnapshots(selected.id)
        return
      }
      setInfo(`已为 ${selected.name} 重新生成当日 AI 整体判断（${res.date || "今日"}）`)
      notification.success({
        title: "当日 AI 整体判断已刷新",
        description: `${selected.name} · ${res.date || "今日"}`,
      })
      // AI response 已写入对应日期的 JSON；从 JSON 重新拉取列表即可
      await refreshDailySnapshots(selected.id)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "刷新当日 AI 整体判断失败"
      setError(msg)
      notification.danger({ title: "刷新当日 AI 整体判断失败", description: msg })
    } finally {
      setDailyRefreshing(false)
    }
  }, [refreshDailySnapshots, selected])

  useEffect(() => {
    if (!selected) {
      setDailySnapshotsFull([])
      setDailyLastRefreshAt(null)
      return
    }
    void refreshDailySnapshots(selected.id)
  }, [selected, refreshDailySnapshots])

  const handleTriggerTarget = async (targetId: string) => {
    setError(null)
    setInfo(null)
    try {
      const res = await triggerApplicationAnalysis(targetId)
      if (!res.ok) {
        const msg = res.error || "触发失败"
        setError(msg)
        notification.danger({ title: "触发分析失败", description: msg })
        return
      }
      setInfo(`已触发 ${targetId} 的 120 日 / 4 段分析；调度器在后台执行。`)
      notification.info({
        title: "已触发后台分析",
        description: `${targetId} · 120 日 / 4 段`,
      })
      setTimeout(() => void refreshScheduler(), 500)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "触发分析失败"
      setError(msg)
      notification.danger({ title: "触发分析失败", description: msg })
    }
  }

  const flushPersist = useCallback(async () => {
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current)
      persistTimerRef.current = null
    }
    const snapshotTargets = [...latestTargetsRef.current]
    const snapshotHorizon = { ...latestHorizonRef.current }
    try {
      await saveApplicationAnalysisTargets({
        horizon: {
          days: Number(snapshotHorizon.days) || 120,
          segments: Number(snapshotHorizon.segments) || 4,
          monthly_keep: Number(snapshotHorizon.monthly_keep) || 6,
          weekly_keep: Number(snapshotHorizon.weekly_keep) || 12,
        },
        items: snapshotTargets,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "目标列表保存失败")
    }
  }, [])

  const schedulePersist = useCallback(() => {
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current)
    }
    persistTimerRef.current = window.setTimeout(() => {
      void flushPersist()
    }, 300)
  }, [flushPersist])

  const handleAddFromSearch = (item: StockSearchItem) => {
    const id = `${item.target_type}-${item.symbol}`
    if (latestTargetsRef.current.some((t) => t.id === id)) return
    const next: ApplicationAnalysisTarget = {
      id,
      target_type: item.target_type,
      symbol: item.symbol,
      name: item.name,
      adjust: adjust,
      enabled: true,
      interval_minutes: 60,
      tags: ["manual"],
    }
    setTargets((prev) => {
      const updated = [...prev, next]
      latestTargetsRef.current = updated
      return updated
    })
    setSelectedId(id)
    schedulePersist()
  }

  const handleRemove = (id: string) => {
    setTargets((prev) => {
      const updated = prev.filter((item) => item.id !== id)
      latestTargetsRef.current = updated
      return updated
    })
    if (selectedId === id) {
      setSelectedId(null)
    }
    schedulePersist()
  }

  const handleUpdateTarget = (id: string, patch: Partial<ApplicationAnalysisTarget>) => {
    setTargets((prev) => {
      const updated = prev.map((item) => (item.id === id ? { ...item, ...patch } : item))
      latestTargetsRef.current = updated
      return updated
    })
    schedulePersist()
  }

  const handleHorizonChange = (patch: HorizonPatch) => {
    setHorizon((prev) => {
      const updated = { ...prev, ...patch }
      latestHorizonRef.current = updated
      return updated
    })
    schedulePersist()
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setInfo(null)
    try {
      await flushPersist()
      setInfo("目标列表已保存到 reference/application-analysis/targets.json")
      notification.success({
        title: "目标列表已保存",
        description: "reference/application-analysis/targets.json",
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : "保存失败"
      setError(msg)
      notification.danger({ title: "保存目标列表失败", description: msg })
    } finally {
      setSaving(false)
    }
  }

  const handleToggleScheduler = async () => {
    const action = scheduler?.running ? "stop" : "start"
    try {
      const res = await controlApplicationAnalysisScheduler(action)
      setScheduler(res.status)
      notification.info({
        title: action === "start" ? "已启动调度器" : "已停止调度器",
        description: res.status?.running ? "后台自动执行中" : "已暂停",
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : "切换调度器失败"
      notification.danger({ title: "切换调度器失败", description: msg })
    }
  }

  const handleRefreshAll = () => {
    void triggerApplicationAnalysis(null).then((res) => {
      if (res.ok) {
        notification.info({
          title: "已触发全量刷新",
          description: "调度器会在后台依次执行所有启用目标",
        })
      } else {
        notification.danger({
          title: "触发全量刷新失败",
          description: res.error || "请查看后端日志",
        })
      }
    })
  }

  const handleAnalyzeSelection = useCallback((item: ChartPanelSelectionItem) => {
    setAnalysisFocusKey(item.key)
    setActiveMainTab("analysis")
  }, [])

  const handleOpenIntradayDialog = useCallback((item: Extract<ChartPanelSelectionItem, { kind: "bar" }>) => {
    setIntradayBar(item)
    setIntradayDialogOpen(true)
  }, [])

  useEffect(() => {
    if (!analysisFocusKey) return
    if (selectedChartItems.some((item) => item.key === analysisFocusKey)) return
    setAnalysisFocusKey(null)
  }, [analysisFocusKey, selectedChartItems])

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Application Analysis" fullBleed>
      <div className="h-[calc(100svh-4rem)] overflow-hidden rounded-none border-0 bg-[#f6f7f9] p-4 sm:p-6">
        <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          {/* 左侧：信息辅助区 */}
          <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto">
            <TargetCard
              targets={targets}
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
              scheduler={scheduler}
              saving={saving}
              onAddFromSearch={handleAddFromSearch}
              onRemove={handleRemove}
              onUpdateTarget={handleUpdateTarget}
              onTriggerTarget={handleTriggerTarget}
              onSave={() => void handleSave()}
              onToggleScheduler={() => void handleToggleScheduler()}
              onRefreshAll={handleRefreshAll}
            />

            <SelectionPanel
              collapsed={selectionCardCollapsed}
              onToggle={() => setSelectionCardCollapsed((value) => !value)}
              items={selectedChartItems}
              selectionColorMap={selectionColorMap}
              analysisFocusKey={analysisFocusKey}
              prevCloseMap={selectedBarPrevClose}
              prevVolumeMap={selectedBarPrevVolume}
              prevTurnoverMap={selectedBarPrevTurnover}
              panelRef={selectionPanelRef}
              onRemoveItem={handleRemoveSelectionItem}
              onClearAll={handleClearSelectionItems}
              onAnalyzeBar={handleOpenIntradayDialog}
            />

            <Alerts
              error={error}
              info={info}
              warnings={warnings}
              errors={errors}
            />
          </div>

          {/* 右侧：顶部区（标题栏 + Tab 栏） + 主内容区 */}
          <Tabs
            value={activeMainTab}
            onValueChange={(value) => setActiveMainTab(value as MainTab)}
            className="flex h-full min-h-0 flex-col gap-4"
          >
            <header className="flex min-h-0 shrink-0 flex-col gap-3">
              {/* 标题栏：当前目标 + 操作按钮 */}
              <ChartHeader
                target={selected}
                selectedLabel={
                  selected ? `${selected.name} · ${selected.symbol}` : "请选择左侧目标"
                }
                adjust={adjust}
                onAdjustChange={setAdjust}
                running={running}
                canRun={Boolean(selected)}
                onTrigger={() => selected && void handleTriggerTarget(selected.id)}
                onManualRun={() => void handleRun()}
              />

              {/* Tab 栏 */}
              <div className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200/80 bg-white px-3 py-2 shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
                <TabsList>
                  <TabsTrigger value="chart">图表</TabsTrigger>
                  <TabsTrigger value="ai-direction">AI 方向</TabsTrigger>
                  <TabsTrigger value="analysis">分析详情</TabsTrigger>
                  <TabsTrigger value="auction">集合竞价</TabsTrigger>
                  <TabsTrigger value="ma-support">技术指标</TabsTrigger>
                  <TabsTrigger value="fund-flow">资金</TabsTrigger>
                </TabsList>
                <div className="flex items-center gap-3 text-[11px] text-slate-500">
                  <span>K 线 {bars.length}</span>
                  <span className="hidden h-3 w-px bg-slate-200 sm:inline-block" />
                  <span>{running ? "分析中" : result ? "已完成" : "待执行"}</span>
                  <span className="hidden h-3 w-px bg-slate-200 sm:inline-block" />
                  <span>标注 {overlays.length}</span>
                </div>
              </div>
            </header>

            {/* 主内容区：填充剩余高度 */}
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
              <TabsContent
                value="chart"
                className="m-0 flex h-full min-h-0 flex-col overflow-hidden"
              >
                {selected ? (
                  <ChartCard
                    collapsed={false}
                    onToggle={() => {}}
                    selectedSymbol={selected.symbol}
                    bars={bars}
                    overlays={overlays}
                    selectionColors={selectionColorMap}
                    selectedBarTimestamps={selectedBarTimestamps}
                    onSelectionChange={setSelectedChartItems}
                    onAnalyzeSelection={handleAnalyzeSelection}
                    loadingBars={loadingBars}
                  />
                ) : null}
              </TabsContent>

              <TabsContent
                value="ai-direction"
                className="m-0 h-full min-h-0 overflow-auto"
              >
                <AIDirectionCard
                  collapsed={false}
                  onToggle={() => {}}
                  dailySnapshotsFull={dailySnapshotsFull}
                  dailySnapshotsLoading={dailySnapshotsLoading}
                  dailyRefreshing={dailyRefreshing}
                  dailyLastRefreshAt={dailyLastRefreshAt}
                  onRefreshDaily={() => void handleRefreshDaily()}
                />
              </TabsContent>

              <TabsContent
                value="analysis"
                className="m-0 h-full min-h-0 overflow-auto"
              >
                {analysis ? (
                  <AnalysisDetail analysis={analysis} overlays={overlays} />
                ) : null}
              </TabsContent>

              <TabsContent
                value="auction"
                className="m-0 h-full min-h-0 overflow-auto"
              >
                {selected ? (
                  <AuctionTab
                    targetType={selected.target_type as StockTargetType}
                    symbol={selected.symbol}
                    name={selected.name}
                    adjust={(selected.adjust as StockAdjust) || adjust}
                  />
                ) : null}
              </TabsContent>

              <TabsContent
                value="ma-support"
                className="m-0 h-full min-h-0 overflow-auto"
              >
                {selected ? (
                  <TechnicalIndicatorTab
                    targetType={selected.target_type as StockTargetType}
                    symbol={selected.symbol}
                    name={selected.name}
                    period="1d"
                    adjust={(selected.adjust as StockAdjust) || adjust}
                  />
                ) : null}
              </TabsContent>

              <TabsContent
                value="fund-flow"
                className="m-0 h-full min-h-0 overflow-auto"
              >
                {selected ? (
                  <FundFlowTab
                    targetType={selected.target_type as StockTargetType}
                    symbol={selected.symbol}
                    name={selected.name}
                  />
                ) : null}
              </TabsContent>
            </main>
          </Tabs>
        </div>
      </div>
      {selected && intradayBar ? (
        <IntradayAnalysisDialog
          open={intradayDialogOpen}
          onOpenChange={setIntradayDialogOpen}
          targetType={selected.target_type as StockTargetType}
          symbol={selected.symbol}
          name={selected.name}
          adjust={(selected.adjust as StockAdjust) || adjust}
          tradeDate={intradayBar.bar.trade_date || formatTradeDateFromTimestamp(intradayBar.bar.timestamp)}
        />
      ) : null}
    </WorkspaceShell>
  )
}
