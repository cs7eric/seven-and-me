/**
 * Design entry:
 * - Data/API: application-analysis targets, results, scheduler, stock-chart klines/intraday/annotations/auction
 * - Front design: design/front/application-analysis.md
 * - Backend design: design/backend/application-analysis-target-sync.md
 * - Change rule: modify code only after reviewing design; sync design if data flow/API/module responsibility changes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Eye, Plus } from "lucide-react"

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
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
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeMainTab, setActiveMainTab] = useState<MainTab>("chart")
  const [targets, setTargets] = useState<ApplicationAnalysisTarget[]>([])
  const [horizon, setHorizon] = useState<Record<string, number>>(DEFAULT_HORIZON)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 临时预览态：从自选页跳过来时 ?symbol=... 不直接持久化，先用 previewTarget
  // 渲染分析面板。点「加入应用分析」后才写入 Postgres target 主表。
  const [previewTarget, setPreviewTarget] = useState<ApplicationAnalysisTarget | null>(null)
  const [adjust, setAdjust] = useState<StockAdjust>("qfq")
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [loadingBars, setLoadingBars] = useState(false)
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const persistTimerRef = useRef<number | null>(null)
  const latestTargetsRef = useRef<ApplicationAnalysisTarget[]>([])
  const latestHorizonRef = useRef<Record<string, number>>({ ...DEFAULT_HORIZON })
  // 是否有未持久化的本地修改。cleanup 仅在 loaded && dirty 时才回写，避免打开页面瞬间
  // (latestTargetsRef 还没被 fetch 赋值) 误把后端真实数据清空。
  const dirtyRef = useRef(false)
  const targetsLoadedRef = useRef(false)
  const [result, setResult] = useState<ApplicationAnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [scheduler, setScheduler] = useState<ApplicationAnalysisSchedulerStatus | null>(null)
  const [searchKeyword, setSearchKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [targetCardCollapsed, setTargetCardCollapsed] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(max-width: 1023px)").matches : false,
  )
  const [selectionCardCollapsed, setSelectionCardCollapsed] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(max-width: 1023px)").matches : false,
  )
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
  // 渲染的目标：优先 preview（临时态），否则走 selected
  const displayedTarget = previewTarget ?? selected

  const refreshTargets = useCallback(async () => {
    try {
      const data = await fetchApplicationAnalysisTargets()
      const items = data.items || []
      const configHorizon = (data.config?.horizon as Record<string, number> | undefined) || {}
      setHorizon({ ...DEFAULT_HORIZON, ...configHorizon })
      latestHorizonRef.current = { ...DEFAULT_HORIZON, ...configHorizon }

      // URL query：?target_type=stock&symbol=600021&name=上海电力&market=SH
      // 注意：只做预览，不主动写入 Postgres target 主表（用户需要的话点「加入应用分析」按钮）
      // 1) symbol 已在 items → 直接选中，并清掉 query
      // 2) 不在 → 设 previewTarget（临时态），让面板能渲染它的 K 线 / 分时
      const symbol = searchParams.get("symbol")
      const targetType = searchParams.get("target_type") || "stock"
      const queryName = searchParams.get("name") || symbol || ""
      let queryTargetId: string | null = null
      let previewObj: ApplicationAnalysisTarget | null = null
      if (symbol) {
        const id = `${targetType}-${symbol}`
        const existing = items.find(
          (t) => t.id === id || (t.symbol || "").toLowerCase() === symbol.toLowerCase(),
        )
        if (existing) {
          queryTargetId = existing.id
        } else {
          previewObj = {
            id,
            target_type: targetType,
            symbol,
            name: queryName || symbol,
            adjust,
            enabled: true,
            interval_minutes: 60,
            tags: ["from-self-selected"],
          }
        }
      }

      setTargets(items)
      latestTargetsRef.current = items
      targetsLoadedRef.current = true
      if (previewObj) {
        setPreviewTarget(previewObj)
        // 预览态不写 selectedId（避免在用户从 targets 列表选其它时被覆盖；render 时走 displayedTarget 优先级）
      } else if (queryTargetId) {
        setSelectedId(queryTargetId)
        setPreviewTarget(null)
      } else {
        // 决定最终选中的 target
        let resolvedId: string | null = null
        if (!selectedId && items.length) {
          const preferred =
            items.find((item) => {
              const s = (item.symbol || "").toLowerCase()
              const i = (item.id || "").toLowerCase()
              return s === "000001" || s === "sh000001" || i.endsWith("-000001") || i === "sh000001"
            }) || items[0]
          resolvedId = preferred.id
        } else {
          resolvedId = selectedId
        }
        if (resolvedId) setSelectedId(resolvedId)
      }

      // 始终清掉 query，避免 refreshTargets 被重复触发时再处理
      if (symbol) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev)
            next.delete("target_type")
            next.delete("symbol")
            next.delete("name")
            next.delete("market")
            return next
          },
          { replace: true },
        )
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载目标列表失败"
      setError("加载目标列表失败")
      notification.danger({ title: "加载目标列表失败", description: msg })
    }
  }, [selectedId, adjust, searchParams, setSearchParams])

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
      // 只有「加载过 targets」且「用户做过未持久化修改」时才回写。
      // 否则会在打开页面瞬间 cleanup 把 latestTargetsRef.current=[] 写回后端。
      if (!targetsLoadedRef.current || !dirtyRef.current) {
        return
      }
      const snapshotTargets = [...latestTargetsRef.current]
      const snapshotHorizon = { ...latestHorizonRef.current }
      dirtyRef.current = false
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
    // K 线 / 分时 / 技术指标都按 displayedTarget 走：预览态也能渲染
    if (!displayedTarget) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBars([])
      return
    }
    let active = true
    setLoadingBars(true)
    void fetchStockKlines({
      targetType: displayedTarget.target_type as StockTargetType,
      symbol: displayedTarget.symbol,
      name: displayedTarget.name,
      period: "1d",
      adjust: (displayedTarget.adjust as StockAdjust) || adjust,
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
  }, [displayedTarget, adjust])

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
      // 持久化成功后清掉 dirty 标记，避免 cleanup 重复写。
      dirtyRef.current = false
    } catch (err) {
      setError(err instanceof Error ? err.message : "目标列表保存失败")
    }
  }, [])

  const schedulePersist = useCallback(() => {
    dirtyRef.current = true
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

  // 把预览态的 target 写入 Postgres，同时切到持久态选中
  const handleAddPreview = async () => {
    if (!previewTarget) return
    setSaving(true)
    try {
      const next: ApplicationAnalysisTarget = {
        ...previewTarget,
        // 去掉「from-self-selected」标签，标成正式分析标的
        tags: previewTarget.tags?.filter((t) => t !== "from-self-selected") || [],
      }
      const updated = [...latestTargetsRef.current, next]
      setTargets(updated)
      latestTargetsRef.current = updated
      // 立刻写回（不走 300ms debounce），避免用户立刻点 Run 时找不到 target
      await flushPersist()
      setSelectedId(next.id)
      setPreviewTarget(null)
      notification.success({
        title: "已加入应用分析",
        description: `${next.name} · ${next.symbol} 现在可以做 AI 分析了`,
      })
    } catch (err) {
      notification.danger({
        title: "加入失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
    } finally {
      setSaving(false)
    }
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
      setInfo("目标列表已保存到 Postgres，并已同步 target 系统分组。")
      notification.success({
        title: "目标列表已保存",
        description: "Application Analysis targets / Self-Selected target group",
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
      <div className="min-h-[calc(100svh-4rem)] w-full max-w-[100vw] overflow-x-hidden rounded-none border-0 bg-[#f6f7f9] p-0 sm:p-4 2xl:p-6 lg:h-[calc(100svh-4rem)] lg:overflow-hidden">
        <div className="grid w-full min-w-0 max-w-full grid-cols-1 gap-2 sm:gap-3 lg:h-full lg:min-h-0 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] xl:grid-cols-[minmax(0,400px)_minmax(0,1fr)] 2xl:grid-cols-[minmax(0,440px)_minmax(0,1fr)] 2xl:gap-4">
          {/* 左侧：信息辅助区。手机端放到工作区下方，避免打开页面先看到一整屏配置。 */}
          <div className={`${displayedTarget ? "order-2" : "order-1"} flex min-h-0 min-w-0 flex-col gap-3 overflow-visible lg:order-1 lg:h-full lg:overflow-y-auto 2xl:gap-4`}>
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
            className="order-1 flex min-w-0 flex-col gap-3 lg:order-2 lg:h-full lg:min-h-0 2xl:gap-4"
          >
            <header className="flex min-h-0 shrink-0 flex-col gap-2 lg:gap-3">
              {/* 预览态 banner：从自选跳过来、还没加入 targets 时浮在最上方 */}
              {previewTarget ? (
                <div className="flex flex-col gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-amber-800 sm:flex-row sm:items-center sm:px-4">
                  <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-amber-700">
                    <Eye className="size-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="break-words text-sm font-semibold sm:truncate">
                      正在预览 {previewTarget.name} · {previewTarget.symbol}
                    </div>
                    <div className="text-xs text-amber-700/80">
                      仅渲染图表 / 分时 / 技术指标，AI 分析结果要「加入」后才会保存
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="default"
                    className="h-8 w-full gap-1.5 bg-amber-600 text-white hover:bg-amber-700 sm:h-7 sm:w-auto"
                    onClick={() => void handleAddPreview()}
                    disabled={saving}
                  >
                    <Plus className="size-3.5" />
                    加入应用分析
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 w-full text-amber-800 hover:bg-amber-500/20 hover:text-amber-900 sm:h-7 sm:w-auto"
                    onClick={() => setPreviewTarget(null)}
                  >
                    取消预览
                  </Button>
                </div>
              ) : null}

              {/* 标题栏：当前目标 + 操作按钮 */}
              <ChartHeader
                target={displayedTarget}
                selectedLabel={
                  displayedTarget
                    ? `${displayedTarget.name} · ${displayedTarget.symbol}`
                    : "请选择左侧目标"
                }
                adjust={adjust}
                onAdjustChange={setAdjust}
                running={running}
                // 预览态不允许 Run / Trigger：必须先「加入」落盘
                canRun={Boolean(selected) && !previewTarget}
                onTrigger={() => selected && void handleTriggerTarget(selected.id)}
                onManualRun={() => void handleRun()}
              />

              {/* Tab 栏 */}
              <div className="sticky top-0 z-20 flex min-w-0 flex-col gap-2 border-y border-slate-200/80 bg-white px-2 py-2 shadow-[0_1px_0_rgba(15,23,42,0.04)] sm:static sm:rounded-2xl sm:border sm:px-3 sm:shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)] lg:flex-row lg:items-center lg:justify-between lg:gap-3">
                <div className="min-w-0 overflow-x-auto sm:overflow-visible">
                  <TabsList className="grid h-auto w-full min-w-0 grid-cols-3 gap-1 sm:inline-flex sm:h-9 sm:w-fit sm:min-w-max">
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="chart">图表</TabsTrigger>
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="ai-direction">AI 方向</TabsTrigger>
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="analysis">分析详情</TabsTrigger>
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="auction">集合竞价</TabsTrigger>
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="ma-support">技术指标</TabsTrigger>
                    <TabsTrigger className="h-8 text-xs sm:h-[calc(100%-1px)] sm:text-sm" value="fund-flow">资金</TabsTrigger>
                  </TabsList>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11px] text-slate-500 sm:px-0">
                  <span>K 线 {bars.length}</span>
                  <span className="hidden h-3 w-px bg-slate-200 sm:inline-block" />
                  <span>{running ? "分析中" : result ? "已完成" : previewTarget ? "预览中" : "待执行"}</span>
                  <span className="hidden h-3 w-px bg-slate-200 sm:inline-block" />
                  <span>标注 {overlays.length}</span>
                  {selectedChartItems.length ? (
                    <>
                      <span className="hidden h-3 w-px bg-slate-200 sm:inline-block" />
                      <button
                        type="button"
                        className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-medium text-slate-700"
                        onClick={() => {
                          setSelectionCardCollapsed(false)
                          window.setTimeout(() => selectionPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0)
                        }}
                      >
                        已选 {selectedChartItems.length}
                      </button>
                    </>
                  ) : null}
                </div>
              </div>
            </header>

            {/* 主内容区：填充剩余高度 */}
            <main className="min-w-0 lg:min-h-0 lg:flex-1 lg:overflow-hidden">
              <TabsContent
                value="chart"
                className="m-0 min-w-0 lg:flex lg:h-full lg:min-h-0 lg:flex-col lg:overflow-hidden"
              >
                {displayedTarget ? (
                  <ChartCard
                    collapsed={false}
                    onToggle={() => {}}
                    selectedSymbol={displayedTarget.symbol}
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
                className="m-0 min-w-0 lg:h-full lg:min-h-0 lg:overflow-auto"
              >
                {previewTarget ? (
                  <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-500">
                    预览模式暂不展示 AI 方向记录，请先加入应用分析。
                  </div>
                ) : (
                  <AIDirectionCard
                    collapsed={false}
                    onToggle={() => {}}
                    dailySnapshotsFull={dailySnapshotsFull}
                    dailySnapshotsLoading={dailySnapshotsLoading}
                    dailyRefreshing={dailyRefreshing}
                    dailyLastRefreshAt={dailyLastRefreshAt}
                    onRefreshDaily={() => void handleRefreshDaily()}
                  />
                )}
              </TabsContent>

              <TabsContent
                value="analysis"
                className="m-0 min-w-0 lg:h-full lg:min-h-0 lg:overflow-auto"
              >
                {previewTarget ? (
                  <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-500">
                    预览模式暂不展示分析详情，请先加入应用分析。
                  </div>
                ) : analysis ? (
                  <AnalysisDetail analysis={analysis} overlays={overlays} />
                ) : null}
              </TabsContent>

              <TabsContent
                value="auction"
                className="m-0 min-w-0 lg:h-full lg:min-h-0 lg:overflow-auto"
              >
                {displayedTarget ? (
                  <AuctionTab
                    targetType={displayedTarget.target_type as StockTargetType}
                    symbol={displayedTarget.symbol}
                    name={displayedTarget.name}
                    adjust={(displayedTarget.adjust as StockAdjust) || adjust}
                  />
                ) : null}
              </TabsContent>

              <TabsContent
                value="ma-support"
                className="m-0 min-w-0 lg:h-full lg:min-h-0 lg:overflow-auto"
              >
                {displayedTarget ? (
                  <TechnicalIndicatorTab
                    targetType={displayedTarget.target_type as StockTargetType}
                    symbol={displayedTarget.symbol}
                    name={displayedTarget.name}
                    period="1d"
                    adjust={(displayedTarget.adjust as StockAdjust) || adjust}
                  />
                ) : null}
              </TabsContent>

              <TabsContent
                value="fund-flow"
                className="m-0 min-w-0 lg:h-full lg:min-h-0 lg:overflow-auto"
              >
                {displayedTarget ? (
                  <FundFlowTab
                    targetType={displayedTarget.target_type as StockTargetType}
                    symbol={displayedTarget.symbol}
                    name={displayedTarget.name}
                  />
                ) : null}
              </TabsContent>
            </main>
          </Tabs>
        </div>
      </div>
      {displayedTarget && intradayBar ? (
        <IntradayAnalysisDialog
          open={intradayDialogOpen}
          onOpenChange={setIntradayDialogOpen}
          targetType={displayedTarget.target_type as StockTargetType}
          symbol={displayedTarget.symbol}
          name={displayedTarget.name}
          adjust={(displayedTarget.adjust as StockAdjust) || adjust}
          tradeDate={intradayBar.bar.trade_date || formatTradeDateFromTimestamp(intradayBar.bar.timestamp)}
        />
      ) : null}
    </WorkspaceShell>
  )
}
