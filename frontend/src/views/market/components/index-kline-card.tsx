import { useEffect, useMemo, useRef } from "react"
import { Loader2 } from "lucide-react"
import * as echarts from "echarts/core"
import { BarChart, LineChart } from "echarts/charts"
import { GridComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

import type { StockIntradayPoint } from "../../stock-chart/lib/types"

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer])

export interface IndexTimeshareItem {
  ok: boolean
  code: string
  name: string
  tradeDate: string | null
  previousClose: number | null
  source?: string
  timeshare: StockIntradayPoint[]
  error?: string
}

interface Props {
  item: IndexTimeshareItem
  loading: boolean
  directionTone: "up" | "down" | "flat"
}

function formatClose(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return value.toFixed(2)
}

function formatPct(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

function formatVolume(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—"
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`
  return value.toFixed(0)
}

function computePriceDomain(values: number[]) {
  if (!values.length) return [0, 1] as const
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, max * 0.003, 0.1)
  return [min - spread * 0.18, max + spread * 0.18] as const
}

function isValidAverageLine(points: Array<Pick<StockIntradayPoint, "price" | "avg_price">>) {
  const priceValues = points.map((point) => point.price).filter((value) => Number.isFinite(value) && value > 0)
  const avgValues = points
    .map((point) => point.avg_price)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0)

  if (avgValues.length === 0) return false
  if (priceValues.length === 0) return false
  if (avgValues.length < Math.max(5, Math.ceil(points.length * 0.25))) return false

  const priceMin = Math.min(...priceValues)
  const priceMax = Math.max(...priceValues)
  const lowerBound = priceMin * 0.7
  const upperBound = priceMax * 1.3
  const inBandCount = avgValues.filter((value) => value >= lowerBound && value <= upperBound).length
  if (inBandCount / avgValues.length < 0.8) return false

  const avgMin = Math.min(...avgValues)
  const avgMax = Math.max(...avgValues)
  const flatSpread = Math.max(priceMax * 0.0005, 0.01)
  if (avgMax - avgMin <= flatSpread && (avgMin < lowerBound || avgMax > upperBound)) return false

  return true
}

function buildXAxisLabels(points: StockIntradayPoint[]) {
  return points.map((point) => point.time_label)
}

function buildTickLabels(points: StockIntradayPoint[]) {
  const visibleTicks = new Set(["09:31", "10:30", "11:30", "13:00", "14:00", "15:00"])
  return points.map((point) => (visibleTicks.has(point.time_label) ? point.time_label : ""))
}

export function IndexKlineCard({ item, loading, directionTone }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  const lastPoint = item.timeshare[item.timeshare.length - 1] ?? null
  const firstPoint = item.timeshare[0] ?? null
  const previousClose = item.previousClose
  const referenceClose =
    previousClose != null && Number.isFinite(previousClose) && previousClose > 0
      ? previousClose
      : firstPoint?.price ?? null
  const lastPrice = lastPoint?.price ?? null
  const pct =
    lastPrice != null && referenceClose != null && referenceClose > 0
      ? ((lastPrice - referenceClose) / referenceClose) * 100
      : null

  const averageLineEnabled = useMemo(() => isValidAverageLine(item.timeshare), [item.timeshare])
  const basePriceValues = useMemo(
    () => item.timeshare.map((point) => point.price).filter((value) => Number.isFinite(value) && value > 0),
    [item.timeshare],
  )
  const avgPrice = averageLineEnabled ? lastPoint?.avg_price ?? null : null
  const totalVolume = useMemo(
    () => item.timeshare.reduce((sum, point) => sum + (point.volume || 0), 0),
    [item.timeshare],
  )

  const chartModel = useMemo(() => {
    const xAxisData = buildXAxisLabels(item.timeshare)
    const tickLabels = buildTickLabels(item.timeshare)
    const priceSeries = item.timeshare.map((point) => point.price)
    const avgSeries = item.timeshare.map((point) => (averageLineEnabled ? point.avg_price ?? null : null))
    const volumeSeries = item.timeshare.map((point, index) => {
      const prev = item.timeshare[index - 1]?.price ?? point.price
      return {
        value: point.volume || 0,
        itemStyle: { color: point.price >= prev ? "rgba(220, 38, 38, 0.42)" : "rgba(22, 163, 74, 0.42)" },
      }
    })

    const priceValues = [...priceSeries]
    if (averageLineEnabled) {
      avgSeries.forEach((value) => {
        if (typeof value === "number" && Number.isFinite(value) && value > 0) priceValues.push(value)
      })
    }
    if (referenceClose != null && basePriceValues.length > 0) {
      const priceMin = Math.min(...basePriceValues)
      const priceMax = Math.max(...basePriceValues)
      if (referenceClose >= priceMin * 0.7 && referenceClose <= priceMax * 1.3) {
        priceValues.push(referenceClose)
      }
    }
    const priceDomain = computePriceDomain(priceValues.filter((value) => Number.isFinite(value) && value > 0))

    return {
      xAxisData,
      tickLabels,
      priceSeries,
      avgSeries,
      volumeSeries,
      priceDomain,
    }
  }, [averageLineEnabled, basePriceValues, item.timeshare, referenceClose])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    const rafId = requestAnimationFrame(() => {
      try {
        chart.resize()
      } catch {}
    })

    let resizeTimer: number | null = null
    const ro = new ResizeObserver(() => {
      if (resizeTimer != null) window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => chart.resize(), 80)
    })
    ro.observe(chartRef.current)

    const handleResize = () => chart.resize()
    window.addEventListener("resize", handleResize)

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener("resize", handleResize)
      ro.disconnect()
      if (resizeTimer != null) window.clearTimeout(resizeTimer)
      chart.dispose()
      instanceRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    if (item.timeshare.length === 0) {
      chart.clear()
      return
    }

    chart.setOption({
      animation: false,
      backgroundColor: "#ffffff",
      grid: [
        { left: 6, right: 48, top: 18, height: "68%" },
        { left: 6, right: 48, top: "79%", height: "14%" },
      ],
      axisPointer: {
        link: [{ xAxisIndex: [0, 1] }],
      },
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
          lineStyle: { color: "#94a3b8", width: 1, type: "dashed" },
        },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "transparent",
        textStyle: { color: "#f8fafc", fontSize: 12 },
        extraCssText: "border-radius: 12px; box-shadow: 0 12px 28px rgba(15,23,42,.22);",
        formatter: (params: unknown) => {
          const rows = params as Array<{ seriesName: string; data: number | { value: number } | null; dataIndex: number }>
          const dataIndex = rows?.[0]?.dataIndex ?? 0
          const point = item.timeshare[dataIndex]
          if (!point) return ""
          return [
            `<div style="font-weight:700;margin-bottom:6px">${[point.trade_date || "", point.time_label || ""].filter(Boolean).join(" ")}</div>`,
            `<div>价格：<b>${formatClose(point.price)}</b></div>`,
            averageLineEnabled ? `<div>均价：<b>${formatClose(point.avg_price ?? null)}</b></div>` : "",
            `<div>分时量：<b>${formatVolume(point.volume)}</b></div>`,
          ]
            .filter(Boolean)
            .join("")
        },
      },
      xAxis: [
        {
          type: "category",
          boundaryGap: false,
          data: chartModel.xAxisData,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 11,
            formatter: (_value: string, index: number) => chartModel.tickLabels[index] || "",
          },
          splitLine: { show: false },
        },
        {
          type: "category",
          boundaryGap: true,
          gridIndex: 1,
          data: chartModel.xAxisData,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          type: "value",
          min: chartModel.priceDomain[0],
          max: chartModel.priceDomain[1],
          scale: true,
          axisLine: { show: false },
          axisTick: { show: false },
          splitNumber: 4,
          splitLine: { lineStyle: { color: "#e2e8f0", type: "dashed" } },
          axisLabel: {
            color: "#64748b",
            fontSize: 11,
            formatter: (value: number) => value.toFixed(0),
          },
        },
        {
          type: "value",
          gridIndex: 1,
          scale: true,
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
        },
      ],
      series: [
        {
          name: "价格",
          type: "line",
          data: chartModel.priceSeries,
          showSymbol: false,
          smooth: true,
          lineStyle: { color: "#0f172a", width: 2 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(15, 23, 42, 0.10)" },
                { offset: 1, color: "rgba(15, 23, 42, 0.01)" },
              ],
            },
          },
        },
        {
          name: "均价",
          type: "line",
          data: chartModel.avgSeries,
          showSymbol: false,
          smooth: true,
          lineStyle: { color: "#f59e0b", width: 1.5 },
          connectNulls: false,
          silent: true,
        },
        {
          name: "分时量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: chartModel.volumeSeries,
          barWidth: "45%",
        },
      ],
    })
  }, [averageLineEnabled, chartModel, item.timeshare])

  const heroTone =
    directionTone === "up"
      ? "text-red-600"
      : directionTone === "down"
        ? "text-emerald-600"
        : "text-slate-900"

  return (
    <section className="flex h-full flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <div className="text-sm font-semibold text-slate-900">{item.name}</div>
        <div className={`text-2xl font-bold tabular-nums ${heroTone}`}>
          {formatClose(lastPrice)}
        </div>
        <div className={`text-xs font-semibold tabular-nums ${heroTone}`}>
          {formatPct(pct)}
        </div>
        {item.source ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            {item.source}
          </span>
        ) : null}
      </div>

      <div className="relative h-[460px] w-full overflow-hidden bg-white">
        {loading && item.timeshare.length === 0 ? (
          <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
            <Loader2 className="mr-1 size-3.5 animate-spin" />
            加载分时…
          </div>
        ) : item.timeshare.length === 0 ? (
          <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
            暂无 {item.name} 分时数据
            {item.error ? <span className="ml-1 text-red-400">({item.error})</span> : null}
          </div>
        ) : (
          <div ref={chartRef} className="h-full w-full" />
        )}
      </div>

      <div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500">
        <div className="flex flex-col">
          <span className="text-slate-400">开盘</span>
          <span className="mt-0.5 font-mono font-semibold tabular-nums text-slate-700">
            {formatClose(firstPoint?.price ?? null)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-slate-400">均价</span>
          <span className="mt-0.5 font-mono font-semibold tabular-nums text-slate-700">
            {averageLineEnabled ? formatClose(avgPrice) : "—"}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-slate-400">总量</span>
          <span className="mt-0.5 font-mono font-semibold tabular-nums text-slate-700">
            {formatVolume(totalVolume)}
          </span>
        </div>
      </div>
    </section>
  )
}
