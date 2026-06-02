import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, Bot, CheckCircle2, ChevronDown, ChevronRight, Clock, FileJson, LineChart, Plus, RefreshCw, Save, Search, ShieldAlert, Sparkles, Trash2 } from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import AnimatedList from "@/components/AnimatedList"
import {
  controlApplicationAnalysisScheduler,
  fetchApplicationAnalysisResult,
  fetchApplicationAnalysisSchedulerStatus,
  fetchApplicationAnalysisTargets,
  fetchStockKlines,
  runApplicationAnalysis,
  saveApplicationAnalysisTargets,
  triggerApplicationAnalysis,
  type ApplicationAnalysisSchedulerStatus,
  type ApplicationAnalysisTarget,
} from "@/lib/api"
import { ChartPanel } from "../stock-chart/components/chart-panel"
import { SymbolSearch } from "../stock-chart/components/symbol-search"
import type {
  ApplicationAnalysisResponse,
  StockAdjust,
  StockKlineBar,
  StockOverlayAnnotation,
  StockTargetType,
} from "../stock-chart/lib/types"

const DEFAULT_HORIZON = { days: 120, segments: 4, monthly_keep: 6, weekly_keep: 12 }

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? "").trim()).filter(Boolean)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asOverlayAnnotations(value: unknown): StockOverlayAnnotation[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is StockOverlayAnnotation =>
    Boolean(item && typeof item === "object" && Array.isArray((item as StockOverlayAnnotation).points)),
  )
}

function fmt(value: unknown) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

function MetricCard({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Bot }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-950">{value}</div>
    </div>
  )
}

function SummaryList({ title, items, tone }: { title: string; items: string[]; tone: "success" | "danger" | "neutral" }) {
  const toneClass = tone === "success" ? "border-l-emerald-500" : tone === "danger" ? "border-l-red-500" : "border-l-slate-500"
  return (
    <div className={`rounded-2xl border border-slate-200 border-l-4 bg-white p-4 ${toneClass}`}>
      <div className="mb-3 text-sm font-semibold text-slate-800">{title}</div>
      <div className="space-y-2">
        {items.length ? items.map((item) => (
          <div key={item} className="rounded-xl bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">{item}</div>
        )) : <div className="text-sm text-slate-400">暂无内容</div>}
      </div>
    </div>
  )
}

function TrendBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        <Badge className="rounded-full border-slate-200 bg-slate-50 text-slate-700" variant="outline">{fmt(data.state)}</Badge>
      </div>
      <div className="grid gap-2 text-sm text-slate-600">
        <div>趋势分：{fmt(data.score)} · 置信度：{fmt(data.confidence)}</div>
        <div>均线：{fmt(data.ma_structure)}</div>
        <div>价格结构：{fmt(data.price_structure)}</div>
        <div>量能：{fmt(data.volume_state)}</div>
        <div>换手：{fmt(data.turnover_state)}</div>
      </div>
    </div>
  )
}

function OverlayTable({ items }: { items: StockOverlayAnnotation[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700">AI 可渲染标注 · {items.length}</div>
      <div className="divide-y divide-slate-100">
        {items.length ? items.map((item, index) => (
          <div key={`${item.overlay_type}-${index}`} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[160px_1fr_120px]">
            <Badge className="w-fit rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{item.overlay_type}</Badge>
            <div className="text-slate-700">{item.text || "未命名标注"}</div>
            <div className="text-slate-400">{item.points.length} points</div>
          </div>
        )) : <div className="px-4 py-8 text-sm text-slate-400">AI 没有返回可渲染标注。</div>}
      </div>
    </div>
  )
}

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
  const [resultPath, setResultPath] = useState<string | null>(null)
  const [history, setHistory] = useState<{ filename: string; path: string; updated_at: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [scheduler, setScheduler] = useState<ApplicationAnalysisSchedulerStatus | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)

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
        setSelectedId(items[0].id)
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
      setResultPath(null)
      setHistory([])
      return
    }
    let active = true
    void fetchApplicationAnalysisResult(selected.id)
      .then((data) => {
        if (!active) return
        setResult(data as unknown as ApplicationAnalysisResponse)
        setResultPath(data._meta_result_path)
        setHistory(data._meta_history || [])
      })
      .catch(() => {
        if (active) {
          setResult(null)
          setResultPath(null)
          setHistory([])
        }
      })
    return () => {
      active = false
    }
  }, [selected, selectedId])

  const analysis = result?.analysis_result
  const summary = (analysis?.summary as Record<string, unknown> | undefined) || {}
  const dataQuality = (analysis?.data_quality as Record<string, unknown> | undefined) || {}
  const trendState = asRecord(analysis?.trend_state)
  const overlays = useMemo(() => asOverlayAnnotations(analysis?.overlay_annotations), [analysis])
  const warnings = textList(dataQuality.warnings)
  const errors = textList(dataQuality.errors)

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

  const handleAddFromSearch = (item: { target_type: StockTargetType; symbol: string; name: string }) => {
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

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Application Analysis">
      <div className="relative -mx-2 -my-4 rounded-3xl border border-slate-200 bg-[#f6f7f9] p-3 sm:p-5 xl:p-6">
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">分析目标</CardTitle>
                  <CardDescription>参考 reference/application-analysis/targets.json</CardDescription>
                </div>
                <Button className="rounded-xl" size="sm" variant="outline" onClick={() => setShowAddForm((value) => !value)}>
                  <Plus className="mr-1 size-3.5" />新增
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {showAddForm ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                  <SymbolSearch
                    onSelect={handleAddFromSearch}
                    knownIds={targets.map((item) => item.id)}
                  />
                </div>
              ) : null}
              <div className="space-y-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
                  <input
                    type="search"
                    value={searchKeyword}
                    onChange={(event) => setSearchKeyword(event.target.value)}
                    placeholder="搜索目标 · 名称 / 代码 / 标签"
                    className="w-full rounded-xl border border-slate-200 bg-white pl-7 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
                  />
                </div>
                <AnimatedList
                  items={filteredTargets}
                  selectedIndex={filteredTargets.findIndex((item) => item.id === selectedId)}
                  onItemSelect={(_item, index) => {
                    const target = filteredTargets[index]
                    if (!target) return
                    setSelectedId(target.id)
                    setExpandedId((current) => (current === target.id ? null : target.id))
                  }}
                  renderItem={(item, index) => {
                    const target = item as ApplicationAnalysisTarget
                    if (!target?.id) return null
                    const isExpanded = expandedId === target.id
                    const isSelected = target.id === selectedId
                    return (
                      <div
                        className={`rounded-2xl border transition ${
                          isSelected ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white hover:border-slate-400"
                        }`}
                      >
                        <div className="flex w-full items-center justify-between gap-2 px-3 py-3 text-left">
                          <div className="flex min-w-0 items-center gap-2">
                            {isExpanded ? <ChevronDown className="size-3.5 text-slate-500" /> : <ChevronRight className="size-3.5 text-slate-500" />}
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                                <span className="truncate">{target.name}</span>
                                <span className="text-slate-400">· {target.symbol}</span>
                              </div>
                              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                                <Clock className="size-3" />每 {target.interval_minutes} 分钟
                                {target.enabled ? <Badge className="rounded-full border-emerald-200 bg-emerald-50 text-emerald-700" variant="outline">启用</Badge> : <Badge className="rounded-full border-slate-200 bg-slate-100 text-slate-500" variant="outline">停用</Badge>}
                                {target.last_updated_at ? <span>· 最近 {new Date(target.last_updated_at).toLocaleString()}</span> : null}
                              </div>
                            </div>
                          </div>
                          <Badge className="rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{target.target_type}</Badge>
                        </div>
                        {isExpanded ? (
                          <div className="space-y-3 border-t border-slate-100 bg-slate-50/60 px-3 py-3" onClick={(event) => event.stopPropagation()}>
                            <div className="grid grid-cols-2 gap-2 text-xs">
                              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                                调整
                                <Select value={target.adjust} onValueChange={(value) => handleUpdateTarget(target.id, { adjust: value })}>
                                  <SelectTrigger className="h-7 w-20"><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="qfq">前复权</SelectItem>
                                    <SelectItem value="none">不复权</SelectItem>
                                    <SelectItem value="hfq">后复权</SelectItem>
                                  </SelectContent>
                                </Select>
                              </label>
                              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                                周期
                                <Select
                                  value={target.interval_minutes.toString()}
                                  onValueChange={(value) => handleUpdateTarget(target.id, { interval_minutes: Number(value) })}
                                >
                                  <SelectTrigger className="h-7 w-24"><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="15">15 分钟</SelectItem>
                                    <SelectItem value="30">30 分钟</SelectItem>
                                    <SelectItem value="60">1 小时</SelectItem>
                                    <SelectItem value="120">2 小时</SelectItem>
                                    <SelectItem value="240">4 小时</SelectItem>
                                    <SelectItem value="1440">1 天</SelectItem>
                                  </SelectContent>
                                </Select>
                              </label>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 text-xs">
                              <Button size="sm" variant="outline" className="rounded-xl" onClick={() => handleUpdateTarget(target.id, { enabled: !target.enabled })}>
                                {target.enabled ? "停用" : "启用"}
                              </Button>
                              <Button size="sm" variant="outline" className="rounded-xl" onClick={() => void handleTriggerTarget(target.id)}>
                                <RefreshCw className="mr-1 size-3.5" />立即刷新
                              </Button>
                              <Button size="sm" variant="ghost" className="rounded-xl text-slate-500" onClick={() => handleRemove(target.id)}>
                                <Trash2 className="mr-1 size-3.5" />删除
                              </Button>
                            </div>
                          </div>
                        ) : null}
                        <div className="sr-only">{index}</div>
                      </div>
                    )
                  }}
                  emptyMessage={targets.length === 0 ? "还没有目标，点击右上角新增。" : "没有匹配的目标。"}
                  maxHeight="max-h-[60vh]"
                  className=""
                  itemClassName=""
                />
              </div>
              <div className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold text-slate-600">数据范围（horizon）</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                    天数<input
                      type="number"
                      min={30}
                      value={horizon.days}
                      onChange={(event) => {
                        const value = Number(event.target.value) || 120
                        setHorizon((prev) => {
                          const updated = { ...prev, days: value }
                          latestHorizonRef.current = updated
                          return updated
                        })
                        schedulePersist()
                      }}
                      className="w-16 rounded-md border border-slate-200 px-1 text-right"
                    />
                  </label>
                  <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                    段数<input
                      type="number"
                      min={1}
                      value={horizon.segments}
                      onChange={(event) => {
                        const value = Number(event.target.value) || 4
                        setHorizon((prev) => {
                          const updated = { ...prev, segments: value }
                          latestHorizonRef.current = updated
                          return updated
                        })
                        schedulePersist()
                      }}
                      className="w-16 rounded-md border border-slate-200 px-1 text-right"
                    />
                  </label>
                  <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                    月 K<input
                      type="number"
                      min={1}
                      value={horizon.monthly_keep}
                      onChange={(event) => {
                        const value = Number(event.target.value) || 6
                        setHorizon((prev) => {
                          const updated = { ...prev, monthly_keep: value }
                          latestHorizonRef.current = updated
                          return updated
                        })
                        schedulePersist()
                      }}
                      className="w-16 rounded-md border border-slate-200 px-1 text-right"
                    />
                  </label>
                  <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                    周 K<input
                      type="number"
                      min={1}
                      value={horizon.weekly_keep}
                      onChange={(event) => {
                        const value = Number(event.target.value) || 12
                        setHorizon((prev) => {
                          const updated = { ...prev, weekly_keep: value }
                          latestHorizonRef.current = updated
                          return updated
                        })
                        schedulePersist()
                      }}
                      className="w-16 rounded-md border border-slate-200 px-1 text-right"
                    />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button className="rounded-xl" size="sm" disabled={saving} onClick={() => void handleSave()}>
                    <Save className="mr-1 size-3.5" />{saving ? "保存中" : "保存配置"}
                  </Button>
                  <Button
                    className="rounded-xl"
                    size="sm"
                    variant={scheduler?.running ? "destructive" : "default"}
                    onClick={() => void handleToggleScheduler()}
                  >
                    {scheduler?.running ? "停止调度" : "启动调度"}
                  </Button>
                  <Button className="rounded-xl" size="sm" variant="outline" onClick={() => void triggerApplicationAnalysis(null)}>
                    全部刷新
                  </Button>
                </div>
                <div className="text-xs text-slate-500">
                  {scheduler
                    ? `调度器 ${scheduler.running ? "运行中" : "已停止"} · 累计 ${scheduler.runs_count ?? 0} 次 · 启用 ${scheduler.enabled_target_count ?? 0}/${scheduler.total_target_count ?? 0}`
                    : "调度器状态未知"}
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-6">
            {error ? (
              <Alert variant="destructive" className="rounded-2xl border-red-200 bg-red-50">
                <ShieldAlert className="size-4" />
                <AlertTitle>分析失败</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {info ? (
              <Alert className="rounded-2xl border-emerald-200 bg-emerald-50 text-emerald-900">
                <CheckCircle2 className="size-4" />
                <AlertTitle>提示</AlertTitle>
                <AlertDescription>{info}</AlertDescription>
              </Alert>
            ) : null}
            {warnings.length || errors.length ? (
              <Alert className="rounded-2xl border-amber-200 bg-amber-50 text-amber-900">
                <AlertTriangle className="size-4" />
                <AlertTitle>数据质量 / 错误</AlertTitle>
                <AlertDescription>{[...warnings, ...errors].join("；")}</AlertDescription>
              </Alert>
            ) : null}

            <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
              <CardHeader>
                <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
                  <div className="space-y-2">
                    <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
                      <Sparkles className="size-3.5" />
                      {selected ? `${selected.name} · ${selected.symbol}` : "请选择左侧目标"}
                    </div>
                    <CardTitle className="text-3xl font-semibold tracking-[-0.05em] text-slate-950">AI K 线结构标注分析</CardTitle>
                    <CardDescription className="max-w-3xl">
                      默认 120 个交易日 / 4 段 / 每月 / 周 K 加成交；定时任务和立即刷新都用 120 天/4 段入口，单次 30 天入口仅用于手动快速验证。
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Select value={adjust} onValueChange={(value) => setAdjust(value as StockAdjust)}>
                      <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="qfq">前复权</SelectItem>
                        <SelectItem value="none">不复权</SelectItem>
                        <SelectItem value="hfq">后复权</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      className="rounded-xl bg-slate-950 text-white hover:bg-slate-800"
                      onClick={() => selected && void handleTriggerTarget(selected.id)}
                      disabled={!selected || running}
                    >
                      <RefreshCw className={`mr-2 size-4 ${running ? "animate-spin" : ""}`} />120 日 / 4 段刷新
                    </Button>
                    <Button
                      className="rounded-xl"
                      variant="outline"
                      onClick={() => void handleRun()}
                      disabled={!selected || running}
                    >
                      手动单次
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <MetricCard icon={LineChart} label="当前目标" value={selected ? `${selected.name} · ${selected.symbol}` : "—"} />
                  <MetricCard icon={FileJson} label="日 K 数量" value={String(bars.length)} />
                  <MetricCard icon={Bot} label="AI 状态" value={running ? "分析中" : result ? "已完成" : "待执行"} />
                  <MetricCard icon={CheckCircle2} label="可渲染标注" value={String(overlays.length)} />
                </div>
                {resultPath ? (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                    持久化路径：<span className="font-mono">{resultPath}</span>
                  </div>
                ) : null}
                {history.length ? (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                    历史快照（最近 {history.length} 份）：
                    <div className="mt-1 flex flex-wrap gap-2">
                      {history.map((item) => (
                        <span key={item.path} className="rounded-md bg-white px-2 py-1 font-mono text-[10px] text-slate-500">
                          {item.filename}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            {selected ? (
              <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                <CardHeader>
                  <CardTitle>{selected.name} · {selected.symbol}</CardTitle>
                  <CardDescription>
                    {loadingBars ? "正在加载真实 K 线..." : "AI overlay_annotations 会直接叠加到 K 线图。"}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ChartPanel
                    bars={bars}
                    annotations={[]}
                    overlayAnnotations={overlays}
                    bsSignals={[]}
                    manualSignalMode={null}
                    onManualSignalCreate={() => undefined}
                    symbol={selected.symbol}
                    period="1d"
                    indicators={["MA", "AMOUNT"]}
                    maLines={[5, 10, 20, 60]}
                  />
                </CardContent>
              </Card>
            ) : null}

            {analysis ? (
              <>
                {trendState && Object.keys(trendState).length ? (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {Object.entries(trendState).map(([key, value]) => (
                      <TrendBlock key={key} title={`段 ${key.replace("segment_", "")} 趋势`} data={asRecord(value)} />
                    ))}
                  </div>
                ) : null}

                <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                  <CardHeader>
                    <CardTitle>结构摘要</CardTitle>
                    <CardDescription>仅展示 AI JSON 中的摘要字段，不额外编造结论。</CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4 md:grid-cols-2">
                    <SummaryList title="主要支撑" tone="success" items={textList(summary.main_support)} />
                    <SummaryList title="主要压力" tone="danger" items={textList(summary.main_resistance)} />
                    <SummaryList title="主要风险" tone="danger" items={textList(summary.main_risks)} />
                    <SummaryList title="主要观察" tone="neutral" items={textList(summary.main_observations)} />
                  </CardContent>
                </Card>

                <OverlayTable items={overlays} />

                <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                  <CardHeader>
                    <CardTitle>严格 JSON 结果</CardTitle>
                    <CardDescription>用于核对 AI 返回是否符合 annotation.md schema。</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <pre className="max-h-[520px] overflow-auto rounded-2xl border border-slate-200 bg-slate-950 p-4 text-xs leading-5 text-slate-100">
                      {JSON.stringify(analysis, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </WorkspaceShell>
  )
}
