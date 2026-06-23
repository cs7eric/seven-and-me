import { useEffect, useMemo, useRef, useState, type RefObject } from "react"
import { BarChart3, GitCompareArrows, ListPlus, RotateCcw, TrendingUp, X } from "lucide-react"
import * as echarts from "echarts/core"
import { LineChart } from "echarts/charts"
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ScrollArea } from "@/components/ui/scroll-area"

import { bandColor, bandFg, cardChrome, fmtPct } from "../lib/format"
import type { IndustryCompareResponse } from "../lib/types"

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const SERIES_COLORS = [
  "#2563eb",
  "#dc2626",
  "#0891b2",
  "#7c3aed",
  "#ea580c",
  "#059669",
  "#d97706",
  "#be123c",
  "#0f766e",
  "#4f46e5",
  "#9333ea",
  "#16a34a",
]

function formatNetYi(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}亿`
}

function formatAxisNet(value: number): string {
  if (!Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  if (abs >= 100) return `${value.toFixed(0)}`
  if (abs >= 10) return `${value.toFixed(1)}`
  return `${value.toFixed(2)}`
}

function percentile(sortedValues: number[], ratio: number): number {
  if (!sortedValues.length) return 0
  const index = Math.min(sortedValues.length - 1, Math.max(0, Math.floor((sortedValues.length - 1) * ratio)))
  return sortedValues[index]
}

function buildNetFlowAxisRange(series: IndustryCompareResponse["industries"]): { min: number; max: number } | null {
  const values = series
    .flatMap((item) => item.points.map((point) => point.mainNet))
    .filter((value): value is number => value != null && Number.isFinite(value))
    .sort((a, b) => a - b)

  if (!values.length) return null

  const low = percentile(values, 0.1)
  const high = percentile(values, 0.9)
  const paddedLow = Math.min(low, 0)
  const paddedHigh = Math.max(high, 0)
  const range = paddedHigh - paddedLow
  const padding = Math.max(range * 0.12, 2)
  const min = paddedLow - padding
  const max = paddedHigh + padding

  if (min === max) {
    return { min: min - 2, max: max + 2 }
  }

  return { min, max }
}

function useLineChart(ref: RefObject<HTMLDivElement | null>, option: echarts.EChartsCoreOption | null) {
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })
    chartRef.current = chart
    const resize = () => chart.resize()
    window.addEventListener("resize", resize)
    return () => {
      window.removeEventListener("resize", resize)
      chart.dispose()
      chartRef.current = null
    }
  }, [ref])

  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option, true)
    chartRef.current.resize()
  }, [option])
}

function ChartBody({ option }: { option: echarts.EChartsCoreOption | null }) {
  const ref = useRef<HTMLDivElement | null>(null)
  useLineChart(ref, option)

  return <div ref={ref} className="h-[340px] w-full" />
}

export function IndustryComparePanel({
  options,
  selected,
  defaultCount,
  loading,
  data,
  onAdd,
  onRemove,
  onResetDefault,
}: {
  options: string[]
  selected: string[]
  defaultCount: number
  loading: boolean
  data: IndustryCompareResponse | null
  onAdd: (names: string[]) => void
  onRemove: (name: string) => void
  onResetDefault: () => void
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pendingAdd, setPendingAdd] = useState<string[]>([])
  const [chartMode, setChartMode] = useState<"netFlow" | "rank">("netFlow")
  const series = useMemo(() => data?.industries ?? [], [data?.industries])
  const sortedSeries = useMemo(
    () =>
      [...series].sort((a, b) => {
        const rankDiff = (a.compositeRank ?? Number.MAX_SAFE_INTEGER) - (b.compositeRank ?? Number.MAX_SAFE_INTEGER)
        if (rankDiff !== 0) return rankDiff
        const scoreDiff = (b.compositeScore ?? -Infinity) - (a.compositeScore ?? -Infinity)
        if (scoreDiff !== 0) return scoreDiff
        return a.name.localeCompare(b.name, "zh-CN")
      }),
    [series],
  )
  const dates = useMemo(() => data?.dates ?? [], [data?.dates])
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const addableOptions = useMemo(() => options.filter((item) => !selectedSet.has(item)), [options, selectedSet])

  const togglePending = (name: string) => {
    setPendingAdd((prev) => (prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]))
  }

  const commitAdd = () => {
    if (!pendingAdd.length) return
    onAdd(pendingAdd)
    setPendingAdd([])
    setPickerOpen(false)
  }

  const chartZoom = useMemo(
    () =>
      dates.length > 80
        ? [
            { type: "inside", throttle: 80 },
            { type: "slider", height: 18, bottom: 12, borderColor: "#e2e8f0" },
          ]
        : [{ type: "inside", throttle: 80 }],
    [dates.length],
  )
  const netFlowAxisRange = useMemo(() => buildNetFlowAxisRange(sortedSeries), [sortedSeries])

  const netFlowOption = useMemo<echarts.EChartsCoreOption | null>(() => {
    if (!series.length || !dates.length) return null
    return {
      color: SERIES_COLORS,
      grid: { left: 56, right: 24, top: 52, bottom: dates.length > 80 ? 58 : 44 },
      legend: { type: "scroll", top: 8, textStyle: { color: "#475569", fontSize: 11 } },
      dataZoom: chartZoom,
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.94)",
        borderWidth: 0,
        textStyle: { color: "#e2e8f0" },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params : []
          const first = rows[0] as { axisValueLabel?: string } | undefined
          const body = rows
            .map((row) => {
              const item = row as { seriesName?: string; data?: number | null; color?: string }
              return `<div style="display:flex;justify-content:space-between;gap:16px;"><span><span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${item.color};margin-right:6px;"></span>${item.seriesName ?? "—"}</span><b>${formatNetYi(item.data)}</b></div>`
            })
            .join("")
          return `<div style="min-width:180px"><div style="margin-bottom:6px;font-weight:600;">${first?.axisValueLabel ?? "—"}</div>${body}</div>`
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: {
          color: "#64748b",
          formatter: (value: string) => value.slice(5),
        },
      },
      yAxis: {
        type: "value",
        min: netFlowAxisRange?.min,
        max: netFlowAxisRange?.max,
        axisLabel: {
          color: "#64748b",
          formatter: (value: number) => formatAxisNet(value),
        },
        splitLine: { lineStyle: { color: "#e2e8f0" } },
      },
      series: sortedSeries.map((item) => ({
        name: item.name,
        type: "line",
        smooth: false,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        emphasis: { focus: "series" },
        data: item.points.map((point) => point.mainNet),
      })),
    }
  }, [chartZoom, dates, netFlowAxisRange, sortedSeries])

  const rankOption = useMemo<echarts.EChartsCoreOption | null>(() => {
    if (!series.length || !dates.length) return null
    const maxRank = Math.max(10, ...series.flatMap((item) => item.points.map((point) => point.rank ?? 0)))
    return {
      color: SERIES_COLORS,
      grid: { left: 56, right: 24, top: 52, bottom: dates.length > 80 ? 58 : 44 },
      legend: { type: "scroll", top: 8, textStyle: { color: "#475569", fontSize: 11 } },
      dataZoom: chartZoom,
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.94)",
        borderWidth: 0,
        textStyle: { color: "#e2e8f0" },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params : []
          const first = rows[0] as { axisValueLabel?: string } | undefined
          const body = rows
            .map((row) => {
              const item = row as { seriesName?: string; data?: number | null; color?: string }
              const rank = item.data == null ? "未上榜" : `#${item.data}`
              return `<div style="display:flex;justify-content:space-between;gap:16px;"><span><span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${item.color};margin-right:6px;"></span>${item.seriesName ?? "—"}</span><b>${rank}</b></div>`
            })
            .join("")
          return `<div style="min-width:180px"><div style="margin-bottom:6px;font-weight:600;">${first?.axisValueLabel ?? "—"}</div>${body}</div>`
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: {
          color: "#64748b",
          formatter: (value: string) => value.slice(5),
        },
      },
      yAxis: {
        type: "value",
        inverse: true,
        min: 1,
        max: maxRank,
        interval: Math.max(1, Math.floor(maxRank / 6)),
        axisLabel: { color: "#64748b" },
        splitLine: { lineStyle: { color: "#e2e8f0" } },
      },
      series: sortedSeries.map((item) => ({
        name: item.name,
        type: "line",
        smooth: false,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        emphasis: { focus: "series" },
        data: item.points.map((point) => point.rank),
      })),
    }
  }, [chartZoom, dates, sortedSeries])

  return (
    <Card className={cardChrome}>
      <CardHeader className="border-b border-slate-100 pb-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M5</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <GitCompareArrows className="mr-2 inline-block size-5 text-indigo-500" />
              行业净流 / 排名对比分析
            </CardTitle>
            <CardDescription className="mt-1 text-sm text-slate-500">
              默认展示近 30 日综合 Top 10 行业，支持切换查看主力净流趋势或排名趋势，并汇总关键对比指标
            </CardDescription>
          </div>
          <Badge variant="outline" className="w-fit rounded-full px-3 py-1 text-xs text-slate-500">
            已选 {selected.length}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap gap-2">
              {selected.map((name) => (
                <span
                  key={name}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm"
                >
                  <span className="truncate">{name}</span>
                  <button
                    type="button"
                    onClick={() => onRemove(name)}
                    className="rounded-full p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    aria-label={`移除 ${name}`}
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onResetDefault}
              className="h-8 rounded-full border-slate-200 bg-white px-3 text-xs text-slate-600"
            >
              <RotateCcw className="mr-1.5 size-3.5" />
              恢复综合 Top {defaultCount}
            </Button>
            <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
              <DropdownMenuTrigger asChild>
                <Button type="button" size="sm" className="h-8 rounded-full bg-slate-900 px-3 text-xs text-white hover:bg-slate-800">
                  <ListPlus className="mr-1.5 size-3.5" />
                  添加行业
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72 p-0">
                <DropdownMenuLabel className="flex items-center justify-between px-3 py-2">
                  <span className="text-xs font-semibold text-slate-600">可选行业</span>
                  <span className="text-[11px] font-normal text-slate-400">{addableOptions.length} 个</span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="m-0" />
                <ScrollArea className="h-72">
                  <div className="p-1">
                    {addableOptions.length ? (
                      addableOptions.map((name) => (
                        <DropdownMenuCheckboxItem
                          key={name}
                          checked={pendingAdd.includes(name)}
                          onCheckedChange={() => togglePending(name)}
                          onSelect={(event) => event.preventDefault()}
                          className="rounded-md text-sm text-slate-700"
                        >
                          {name}
                        </DropdownMenuCheckboxItem>
                      ))
                    ) : (
                      <div className="px-3 py-8 text-center text-xs text-slate-400">没有可追加行业</div>
                    )}
                  </div>
                </ScrollArea>
                <DropdownMenuSeparator className="m-0" />
                <div className="flex items-center justify-between gap-2 p-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setPendingAdd([])}
                    className="h-8 px-2 text-xs text-slate-500"
                    disabled={!pendingAdd.length}
                  >
                    清空
                  </Button>
                  <Button type="button" size="sm" onClick={commitAdd} className="h-8 px-3 text-xs" disabled={!pendingAdd.length}>
                    加入 {pendingAdd.length || ""}
                  </Button>
                </div>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {!selected.length ? (
          <div className="rounded-2xl border border-dashed border-slate-200 p-10 text-center text-sm text-slate-500">
            请选择至少一个行业
          </div>
        ) : loading ? (
          <div className="rounded-2xl border border-dashed border-slate-200 p-10 text-center text-sm text-slate-500">
            正在加载历史对比数据...
          </div>
        ) : !series.length ? (
          <div className="rounded-2xl border border-dashed border-slate-200 p-10 text-center text-sm text-slate-500">
            暂无可用历史数据
          </div>
        ) : (
          <>
            <Card className="rounded-2xl border-slate-200">
              <CardHeader className="gap-3 pb-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle className="text-sm font-semibold text-slate-900">
                    {chartMode === "netFlow" ? "多行业历史净流趋势图" : "多行业排名趋势图"}
                  </CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    {chartMode === "netFlow" ? `近 ${dates.length} 个交易日 · 单位: 亿` : "排名越靠上数值越小，未上榜日期保持断点"}
                  </CardDescription>
                </div>
                <div className="inline-flex rounded-full border border-slate-200 bg-slate-50 p-1">
                  <button
                    type="button"
                    onClick={() => setChartMode("netFlow")}
                    className={`rounded-full px-3 py-1 text-xs font-medium ${chartMode === "netFlow" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
                  >
                    净流趋势
                  </button>
                  <button
                    type="button"
                    onClick={() => setChartMode("rank")}
                    className={`rounded-full px-3 py-1 text-xs font-medium ${chartMode === "rank" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
                  >
                    排名趋势
                  </button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="mb-3 text-xs text-slate-500">默认组合：综合 Top {defaultCount}（近 30 日）</div>
                <ChartBody option={chartMode === "netFlow" ? netFlowOption : rankOption} />
              </CardContent>
            </Card>

            <Card className="rounded-2xl border-slate-200">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <BarChart3 className="size-4 text-indigo-500" />
                  综合 Top 行业摘要
                </CardTitle>
                <CardDescription className="text-xs text-slate-500">
                  综合排名优先展示，10 日均值用于衡量持续资金强度
                </CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs text-slate-500">
                      <th className="px-3 py-2 text-left font-semibold">行业</th>
                      <th className="px-3 py-2 text-right font-semibold">综合排名</th>
                      <th className="px-3 py-2 text-right font-semibold">最新净流</th>
                      <th className="px-3 py-2 text-right font-semibold">10 日均值</th>
                      <th className="px-3 py-2 text-right font-semibold">上榜天数</th>
                      <th className="px-3 py-2 text-right font-semibold">最新排名</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedSeries.map((item) => (
                      <tr key={item.name} className="border-b border-slate-50">
                        <td className="px-3 py-3">
                          <div className="font-medium text-slate-900">{item.name}</div>
                          {item.latestChangePct != null ? (
                            <div
                              className="mt-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
                              style={{
                                background: bandColor(item.latestChangePct),
                                color: bandFg(item.latestChangePct),
                              }}
                            >
                              {fmtPct(item.latestChangePct)}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums text-slate-700">
                          {item.compositeRank == null ? "—" : `#${item.compositeRank}`}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums text-slate-700">{formatNetYi(item.latestMainNet)}</td>
                        <td className="px-3 py-3 text-right tabular-nums text-slate-700">{formatNetYi(item.averages["10"])}</td>
                        <td className="px-3 py-3 text-right tabular-nums text-slate-500">
                          <span className="inline-flex items-center gap-1">
                            <TrendingUp className="size-3 text-slate-400" />
                            {item.appearances}/{dates.length}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums text-slate-700">
                          {item.latestRank == null ? "—" : `#${item.latestRank}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </>
        )}
      </CardContent>
    </Card>
  )
}
