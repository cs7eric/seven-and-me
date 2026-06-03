import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { WorkspaceShell } from "@/components/workspace-shell"
import {
  controlApplicationAnalysisScheduler,
  fetchApplicationAnalysisResult,
  fetchApplicationAnalysisSchedulerStatus,
  fetchApplicationAnalysisTargets,
  fetchStockKlines,
  listApplicationAnalysisRecent30,
  readApplicationAnalysisRecent30,
  refreshApplicationAnalysisRecent30,
  runApplicationAnalysis,
  saveApplicationAnalysisTargets,
  triggerApplicationAnalysis,
  type ApplicationAnalysisDailySnapshotFile,
  type ApplicationAnalysisDailySnapshotResponse,
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
import { ChartCard } from "./components/chart-card"
import { ChartHeader } from "./components/chart-header"
import { OverviewCard } from "./components/overview-card"
import { SelectionPanel } from "./components/selection-panel"
import { TargetCard, type HorizonPatch } from "./components/target-card"
import { DEFAULT_HORIZON, SELECTION_COLORS } from "./lib/constants"
import {
  asOverlayAnnotations,
  asRecord,
  textList,
} from "./lib/format"
import type { ApplicationAnalysisDailySnapshot } from "./lib/types"

export default function ApplicationAnalysisPage() {
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
  const [showAddForm, setShowAddForm] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [targetCardCollapsed, setTargetCardCollapsed] = useState(true)
  const [overviewCardCollapsed, setOverviewCardCollapsed] = useState(false)
  const [selectionCardCollapsed, setSelectionCardCollapsed] = useState(false)
  const [chartCardCollapsed, setChartCardCollapsed] = useState(false)
  const [directionCardCollapsed, setDirectionCardCollapsed] = useState(false)
  const [dailySnapshots, setDailySnapshots] = useState<ApplicationAnalysisDailySnapshotFile[]>([])
  const [dailySnapshotsLoading, setDailySnapshotsLoading] = useState(false)
  const [dailyRefreshing, setDailyRefreshing] = useState(false)
  const [dailyLastRefreshAt, setDailyLastRefreshAt] = useState<string | null>(null)
  const [dailySelectedDate, setDailySelectedDate] = useState<string | null>(null)
  const [dailySelectedSnapshot, setDailySelectedSnapshot] = useState<ApplicationAnalysisDailySnapshot | null>(null)
  const [selectedChartItems, setSelectedChartItems] = useState<ChartPanelSelectionItem[]>([])
  const [analysisFocusKey, setAnalysisFocusKey] = useState<string | null>(null)
  const selectionPanelRef = useRef<HTMLDivElement | null>(null)

  const selected = useMemo(() => targets.find((item) => item.id === selectedId) || null, [targets, selectedId])

  const filteredTargets = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase()
    if (!keyword) return targets
    return targets.filter((item) => {
      const haystack = `${item.id} ${item.symbol} ${item.name} ${item.target_type} ${(item.tags || []).join(" ")}`.toLowerCase()
      return haystack.includes(keyword)
    })
  }, [targets, searchKeyword])

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
    } catch {
      setError("加载目标列表失败")
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
  const shortTermTrend = useMemo(() => asRecord(analysis?.short_term_trend), [analysis])
  const currentSituation = useMemo(() => asRecord(analysis?.current_situation), [analysis])
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
      } catch (err) {
        setError(err instanceof Error ? err.message : "Application Analysis 失败")
      }
    } finally {
      setRunning(false)
    }
  }

  const refreshDailySnapshots = useCallback(async (targetId: string) => {
    try {
      setDailySnapshotsLoading(true)
      const data = await listApplicationAnalysisRecent30(targetId, 60)
      const items = (data.snapshots || []).slice().sort((a, b) => (a.date < b.date ? 1 : -1))
      setDailySnapshots(items)
      if (items.length) {
        if (!dailySelectedDate || !items.some((item) => item.date === dailySelectedDate)) {
          setDailySelectedDate(items[0].date)
        }
      } else {
        setDailySelectedDate(null)
        setDailySelectedSnapshot(null)
      }
    } catch {
      setDailySnapshots([])
    } finally {
      setDailySnapshotsLoading(false)
    }
  }, [dailySelectedDate])

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
        setError(res.error || "刷新当日 AI 整体判断失败")
        return
      }
      setDailyLastRefreshAt(new Date().toISOString())
      if (res.updated === false) {
        // AI 报无数据 / 返回字段缺失：不改写文件，沿用旧判断
        const reasonLabel =
          res.skip_reason === "no_new_data"
            ? "AI 未返回有效的整体判断字段"
            : "AI 未返回有效结果"
        setInfo(
          `${selected.name} 今日整体判断已保持原样（${res.date || "今日"}）：${reasonLabel}，未做更新。`,
        )
        await refreshDailySnapshots(selected.id)
        if (res.date) {
          setDailySelectedDate(res.date)
        }
        return
      }
      setInfo(`已为 ${selected.name} 重新生成当日 AI 整体判断（${res.date || "今日"}）`)
      // 同步把 daily 的 analysis_result 写回 result，保证顶部 短期趋势/当前情况 也用最新值
      if (res.short_term_trend || res.current_situation) {
        const baseResult = (result as Record<string, unknown> | null) || {}
        const analysisResult = (baseResult.analysis_result as Record<string, unknown> | undefined) || {}
        setResult({
          ...(baseResult as Record<string, unknown>),
          analysis_result: {
            ...analysisResult,
            short_term_trend: res.short_term_trend || null,
            current_situation: res.current_situation || null,
          },
        } as unknown as typeof result)
      }
      await refreshDailySnapshots(selected.id)
      if (res.date) {
        setDailySelectedDate(res.date)
        setDailySelectedSnapshot({
          short_term_trend: res.short_term_trend || null,
          current_situation: res.current_situation || null,
          updated_at: new Date().toISOString(),
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新当日 AI 整体判断失败")
    } finally {
      setDailyRefreshing(false)
    }
  }, [refreshDailySnapshots, result, selected])

  useEffect(() => {
    if (!selected) {
      setDailySnapshots([])
      setDailySelectedDate(null)
      setDailySelectedSnapshot(null)
      return
    }
    void refreshDailySnapshots(selected.id)
  }, [selected, refreshDailySnapshots])

  useEffect(() => {
    if (!selected || !dailySelectedDate) {
      setDailySelectedSnapshot(null)
      return
    }
    const cached = dailySnapshots.find((item) => item.date === dailySelectedDate)
    if (!cached) {
      setDailySelectedSnapshot(null)
      return
    }
    // 本地快照仅含 meta 字段，要再读一次详细 JSON
    let cancelled = false
    void (async () => {
      const data = await readApplicationAnalysisRecent30(selected.id, dailySelectedDate)
      if (cancelled) return
      if (data?.ok && data.snapshot) {
        setDailySelectedSnapshot({
          short_term_trend: data.snapshot.short_term_trend || null,
          current_situation: data.snapshot.current_situation || null,
          summary: data.snapshot.summary || null,
          updated_at: data.snapshot.updated_at,
        })
      }
    })().catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [dailySelectedDate, dailySnapshots, selected])

  const handleTriggerTarget = async (targetId: string) => {
    setError(null)
    setInfo(null)
    const res = await triggerApplicationAnalysis(targetId)
    if (!res.ok) {
      setError(res.error || "触发失败")
      return
    }
    setInfo(`已触发 ${targetId} 的 120 日 / 4 段分析；调度器在后台执行。`)
    setTimeout(() => void refreshScheduler(), 500)
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
    setShowAddForm(false)
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const handleToggleScheduler = async () => {
    const action = scheduler?.running ? "stop" : "start"
    const res = await controlApplicationAnalysisScheduler(action)
    setScheduler(res.status)
  }

  const handleRefreshAll = () => {
    void triggerApplicationAnalysis(null)
  }

  const handleAnalyzeSelection = useCallback((item: ChartPanelSelectionItem) => {
    setAnalysisFocusKey(item.key)
    window.requestAnimationFrame(() => {
      selectionPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
    })
  }, [])

  useEffect(() => {
    if (!analysisFocusKey) return
    if (selectedChartItems.some((item) => item.key === analysisFocusKey)) return
    setAnalysisFocusKey(null)
  }, [analysisFocusKey, selectedChartItems])

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Application Analysis">
      <div className="relative -mx-2 -my-4 rounded-3xl border border-slate-200 bg-[#f6f7f9] p-3 sm:p-5 xl:p-6">
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-4 xl:sticky xl:top-6 xl:self-start xl:max-h-[calc(100svh-7rem)] xl:overflow-y-auto xl:pr-1">
            <TargetCard
              targets={targets}
              filteredTargets={filteredTargets}
              searchKeyword={searchKeyword}
              setSearchKeyword={setSearchKeyword}
              selectedId={selectedId}
              setSelectedId={setSelectedId}
              expandedId={expandedId}
              setExpandedId={setExpandedId}
              collapsed={targetCardCollapsed}
              setCollapsed={setTargetCardCollapsed}
              showAddForm={showAddForm}
              setShowAddForm={setShowAddForm}
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

            <OverviewCard
              collapsed={overviewCardCollapsed}
              onToggle={() => setOverviewCardCollapsed((value) => !value)}
              selectedName={selected?.name ?? null}
              selectedSymbol={selected?.symbol ?? null}
              barsCount={bars.length}
              running={running}
              resultReady={Boolean(result)}
              overlayCount={overlays.length}
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
            />

            <AIDirectionCard
              shortTermTrend={shortTermTrend}
              currentSituation={currentSituation}
              collapsed={directionCardCollapsed}
              onToggle={() => setDirectionCardCollapsed((value) => !value)}
              dailySnapshots={dailySnapshots}
              dailySnapshotsLoading={dailySnapshotsLoading}
              dailyRefreshing={dailyRefreshing}
              dailyLastRefreshAt={dailyLastRefreshAt}
              onRefreshDaily={() => void handleRefreshDaily()}
              dailySelectedDate={dailySelectedDate}
              onSelectDailyDate={setDailySelectedDate}
              dailySelectedSnapshot={dailySelectedSnapshot}
            />
          </div>

          <div className="space-y-6">
            <Alerts
              error={error}
              info={info}
              warnings={warnings}
              errors={errors}
            />

            <ChartHeader
              selectedLabel={selected ? `${selected.name} · ${selected.symbol}` : "请选择左侧目标"}
              adjust={adjust}
              onAdjustChange={setAdjust}
              running={running}
              canRun={Boolean(selected)}
              onTrigger={() => selected && void handleTriggerTarget(selected.id)}
              onManualRun={() => void handleRun()}
            />

            {selected ? (
              <ChartCard
                collapsed={chartCardCollapsed}
                onToggle={() => setChartCardCollapsed((value) => !value)}
                selectedSymbol={selected.symbol}
                bars={bars}
                overlays={overlays}
                selectionColors={selectionColorMap}
                onSelectionChange={setSelectedChartItems}
                onAnalyzeSelection={handleAnalyzeSelection}
                loadingBars={loadingBars}
              />
            ) : null}

            {analysis ? <AnalysisDetail analysis={analysis} overlays={overlays} /> : null}
          </div>
        </div>
      </div>
    </WorkspaceShell>
  )
}
