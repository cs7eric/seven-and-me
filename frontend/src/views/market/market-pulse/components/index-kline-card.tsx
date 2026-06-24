import { useEffect, useMemo, useRef } from "react"
import { Loader2 } from "lucide-react"
import * as echarts from "echarts/core"
import { BarChart, CustomChart, LineChart } from "echarts/charts"
import { GridComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

import type { StockIntradayPoint } from "../../stock-chart/lib/types"

echarts.use([LineChart, BarChart, CustomChart, GridComponent, TooltipComponent, CanvasRenderer])

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

function formatSignedPoint(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}`
}

function formatVolume(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—"
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`
  return value.toFixed(0)
}

function computeDeltaDomain(values: number[]) {
  if (!values.length) return [-1, 1] as const
  const min = Math.min(...values)
  const max = Math.max(...values)
  const limit = Math.max(Math.abs(min), Math.abs(max), 0.1)
  return [-limit * 1.18, limit * 1.18] as const
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
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

function toSessionMinute(timeLabel: string, fallback: number) {
  const match = /^(\d{2}):(\d{2})$/.exec(timeLabel || "")
  if (!match) return fallback
  const minutes = Number(match[1]) * 60 + Number(match[2])
  if (minutes <= 11 * 60 + 30) return clamp(minutes - (9 * 60 + 30), 0, 120)
  return clamp(120 + minutes - 13 * 60, 120, 240)
}

function formatSessionTick(value: number) {
  const rounded = Math.round(value)
  const labels: Record<number, string> = {
    0: "09:30",
    30: "10:00",
    90: "11:00",
    120: "11:30",
    180: "14:00",
    240: "15:00",
  }
  return labels[rounded] ?? ""
}

type SignedSegment = {
  side: "up" | "down"
  values: [number, number, number, number]
  startIntensity: number
  endIntensity: number
}

type SignedSliceRenderApi = {
  value: (dimension: number) => unknown
  coord: (data: [number, number]) => [number, number]
}

function buildSignedSegments(
  points: StockIntradayPoint[],
  xValues: number[],
  referenceClose: number | null,
  maxAbsDelta: number,
) {
  if (referenceClose == null || points.length === 0) return { up: [], down: [] } as const

  const up: SignedSegment[] = []
  const down: SignedSegment[] = []
  const append = (segment: SignedSegment) => {
    const [x1, y1, x2, y2] = segment.values
    if (x1 === x2) return
    if (y1 === 0 && y2 === 0) return
    if (segment.side === "up") up.push(segment)
    else down.push(segment)
  }

  const pushSegment = (side: "up" | "down", start: [number, number], end: [number, number]) => {
    append({
      side,
      values: [start[0], start[1], end[0], end[1]],
      startIntensity: clamp(Math.abs(start[1]) / Math.max(maxAbsDelta, 0.1), 0, 1),
      endIntensity: clamp(Math.abs(end[1]) / Math.max(maxAbsDelta, 0.1), 0, 1),
    })
  }

  for (let i = 1; i < points.length; i++) {
    const prevX = xValues[i - 1] ?? i - 1
    const curX = xValues[i] ?? i
    const prevDelta = points[i - 1].price - referenceClose
    const curDelta = points[i].price - referenceClose

    if (prevDelta === 0 && curDelta === 0) continue

    if (prevDelta >= 0 && curDelta >= 0 && (prevDelta > 0 || curDelta > 0)) {
      pushSegment("up", [prevX, prevDelta], [curX, curDelta])
      continue
    }

    if (prevDelta <= 0 && curDelta <= 0 && (prevDelta < 0 || curDelta < 0)) {
      pushSegment("down", [prevX, prevDelta], [curX, curDelta])
      continue
    }

    if (prevDelta === curDelta) continue
    const ratio = prevDelta / (prevDelta - curDelta)
    const crossX = prevX + (curX - prevX) * clamp(ratio, 0, 1)
    const cross: [number, number] = [crossX, 0]
    const firstSide = prevDelta > 0 ? "up" : "down"
    const secondSide = firstSide === "up" ? "down" : "up"
    pushSegment(firstSide, [prevX, prevDelta], cross)
    pushSegment(secondSide, cross, [curX, curDelta])
  }

  return { up, down } as const
}

export function IndexKlineCard({ item, loading, directionTone }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  const lastPoint = item.timeshare[item.timeshare.length - 1] ?? null
  const firstPoint = item.timeshare[0] ?? null
  const previousClose = item.previousClose
  // 修复: previousClose 缺失时 fallback 优先用今开 (firstPoint.open), 退到 firstPoint.price.
  // 之前用 price (= 09:31 close), 离 09:30 集合竞价价较远, 涨幅虚高.
  // 真无 referenceClose 时, 不计算涨幅 / 不画 0 线 (避免 0 线穿心错位).
  const fallbackClose =
    firstPoint && firstPoint.open != null && firstPoint.open > 0
      ? firstPoint.open
      : firstPoint?.price ?? null
  const referenceClose =
    previousClose != null && Number.isFinite(previousClose) && previousClose > 0
      ? previousClose
      : fallbackClose
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
  // 总量: 用原始 timeshare (含 09:30 合成点 volume=0, 累加结果不变) 即可
  const totalVolume = useMemo(
    () => item.timeshare.reduce((sum, point) => sum + (point.volume || 0), 0),
    [item.timeshare],
  )

  const chartModel = useMemo(() => {
    // 9:30 开盘占位: eltdx 1m bar 的 time_label 是 bar 的结束时间 (09:31 那根代表 09:30:00→09:31:00).
    // X 轴 0 位置标签是 "09:30" 但没数据 → 视觉上 09:30 缺失.
    // 修法: 首根是 09:31 时, 注入一根合成的 09:30 (price=开票价, volume=0, avg=开票价),
    //       渲染出 09:30 开盘点, 跟 09:31 之间的水平短线即"开盘价线" (同花顺/东财约定).
    let timeshare = item.timeshare
    if (timeshare.length > 0 && timeshare[0]?.time_label === "09:31") {
      const first = timeshare[0]
      // 09:30 今开占位: 优先用 1m bar 的 open (真实今开), 退到 first.price (eltdx 无 open 字段时).
      // 之前用 first.price 把 09:31 close 误当开盘, 导致开盘价线和图表"基线"错位.
      const openPrice = (first.open != null && first.open > 0) ? first.open : first.price
      const openPoint: StockIntradayPoint = {
        ...first,
        price: openPrice,
        time_label: "09:30",
        timestamp: (first.timestamp ?? 0) - 60_000,
        volume: 0,
      }
      timeshare = [openPoint, ...timeshare]
    }
    const xValues = timeshare.map((point, index) => toSessionMinute(point.time_label, index))
    const priceSeries = timeshare.map((point, index) => [
      xValues[index] ?? index,
      referenceClose != null ? point.price - referenceClose : point.price,
    ] as [number, number])
    const avgSeries = timeshare.map((point, index) =>
      averageLineEnabled && referenceClose != null && point.avg_price != null
        ? [xValues[index] ?? index, point.avg_price - referenceClose]
        : [xValues[index] ?? index, null],
    )
    const referenceSeries = referenceClose != null ? [[0, 0], [240, 0]] : []
    const volumeSeries = timeshare.map((point, index) => {
      const prev = timeshare[index - 1]?.price ?? point.price
      return {
        value: [xValues[index] ?? index, point.volume || 0],
        itemStyle: { color: point.price >= prev ? "rgba(220, 38, 38, 0.42)" : "rgba(22, 163, 74, 0.42)" },
      }
    })

    const priceValues = timeshare.map((point) => point.price)
    if (averageLineEnabled) {
      avgSeries.forEach((value) => {
        const y = Array.isArray(value) ? value[1] : null
        if (typeof y === "number" && Number.isFinite(y) && referenceClose != null) {
          priceValues.push(y + referenceClose)
        }
      })
    }
    if (referenceClose != null && basePriceValues.length > 0) {
      const priceMin = Math.min(...basePriceValues)
      const priceMax = Math.max(...basePriceValues)
      if (referenceClose >= priceMin * 0.7 && referenceClose <= priceMax * 1.3) {
        priceValues.push(referenceClose)
      }
    }
    const deltaValues = referenceClose != null
      ? priceValues.filter((value) => Number.isFinite(value)).map((value) => value - referenceClose)
      : priceValues.filter((value) => Number.isFinite(value))
    const deltaDomain = computeDeltaDomain(deltaValues)
    const maxAbsDelta = Math.max(...deltaValues.map((value) => Math.abs(value)), 0.1)
    const segments = buildSignedSegments(timeshare, xValues, referenceClose, maxAbsDelta)

    return {
      xValues,
      // 暴露处理后的 timeshare (含 09:30 合成点) 给 tooltip 用, 跟 xValues / segments 对齐
      timeshare,
      priceSeries,
      avgSeries,
      referenceSeries,
      upSegments: segments.up,
      downSegments: segments.down,
      volumeSeries,
      deltaDomain,
    }
  }, [averageLineEnabled, basePriceValues, item.timeshare, referenceClose])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    const rafId = requestAnimationFrame(() => {
      try {
        chart.resize()
      } catch {
        return
      }
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

    const renderSignedSlice = (side: "up" | "down") => (_params: unknown, api: SignedSliceRenderApi) => {
      const x1 = Number(api.value(0))
      const y1 = Number(api.value(1))
      const x2 = Number(api.value(2))
      const y2 = Number(api.value(3))
      const startIntensity = clamp(Number(api.value(4)) || 0, 0, 1)
      const endIntensity = clamp(Number(api.value(5)) || 0, 0, 1)
      const start = api.coord([x1, y1])
      const end = api.coord([x2, y2])
      const baseEnd = api.coord([x2, 0])
      const baseStart = api.coord([x1, 0])
      const isUp = side === "up"
      const fillAlphaStart = 0.08 + startIntensity * 0.3
      const fillAlphaEnd = 0.08 + endIntensity * 0.3
      const lineAlphaStart = 0.7 + startIntensity * 0.3
      const lineAlphaEnd = 0.7 + endIntensity * 0.3
      const fillColorStart = isUp
        ? `rgba(220, 38, 38, ${fillAlphaStart})`
        : `rgba(22, 163, 74, ${fillAlphaStart})`
      const fillColorEnd = isUp
        ? `rgba(220, 38, 38, ${fillAlphaEnd})`
        : `rgba(22, 163, 74, ${fillAlphaEnd})`
      const lineColorStart = isUp
        ? `rgba(220, 23, 23, ${lineAlphaStart})`
        : `rgba(5, 148, 71, ${lineAlphaStart})`
      const lineColorEnd = isUp
        ? `rgba(220, 23, 23, ${lineAlphaEnd})`
        : `rgba(5, 148, 71, ${lineAlphaEnd})`
      const gradientBase = {
        type: "linear" as const,
        x: start[0],
        y: 0,
        x2: end[0],
        y2: 0,
        global: true,
      }
      const fillColor = {
        ...gradientBase,
        colorStops: [
          { offset: 0, color: fillColorStart },
          { offset: 1, color: fillColorEnd },
        ],
      }
      const lineColor = {
        ...gradientBase,
        colorStops: [
          { offset: 0, color: lineColorStart },
          { offset: 1, color: lineColorEnd },
        ],
      }

      return {
        type: "group",
        children: [
          {
            type: "polygon",
            shape: { points: [baseStart, start, end, baseEnd] },
            style: { fill: fillColor, stroke: "none" },
            silent: true,
          },
          {
            type: "polyline",
            shape: { points: [start, end] },
            style: {
              fill: "none",
              stroke: lineColor,
              lineWidth: 3.2,
              lineCap: "butt",
              lineJoin: "round",
            },
            silent: true,
          },
        ],
      }
    }

    chart.setOption(
      {
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
            const rows = params as Array<{
              seriesName: string
              data: [number, number] | number | { value: number[] } | null
              dataIndex: number
            }>
            const row = rows.find((item) => item.seriesName === "价格")
              ?? rows.find((item) => item.seriesName !== "昨收")
              ?? rows[0]
            const rawData = row?.data
            const x =
              Array.isArray(rawData)
                ? rawData[0]
                : rawData && typeof rawData === "object" && "value" in rawData && Array.isArray(rawData.value)
                  ? rawData.value[0]
                  : chartModel.xValues[row?.dataIndex ?? 0]
            const dataIndex = chartModel.xValues.reduce((bestIndex, value, index) => {
              return Math.abs(value - x) < Math.abs(chartModel.xValues[bestIndex] - x) ? index : bestIndex
            }, 0)
            // 关键: 用 chartModel.timeshare (含 09:30 合成点) 而不是 item.timeshare,
            // 避免 dataIndex 因合成点偏移 1 而读错.
            const point = chartModel.timeshare[dataIndex]
            if (!point) return ""
            const change =
              referenceClose != null && Number.isFinite(referenceClose)
                ? point.price - referenceClose
                : null
            const changePct =
              change != null && referenceClose != null && referenceClose > 0
                ? (change / referenceClose) * 100
                : null
            const changeColor =
              change == null || change === 0
                ? "#cbd5e1"
                : change > 0
                  ? "#fca5a5"
                  : "#86efac"
            return [
              `<div style="font-weight:700;margin-bottom:6px">${[point.trade_date || "", point.time_label || ""].filter(Boolean).join(" ")}</div>`,
              `<div>价格：<b>${formatClose(point.price)}</b></div>`,
              `<div>涨跌：<b style="color:${changeColor}">${formatSignedPoint(change)}</b></div>`,
              `<div>涨幅：<b style="color:${changeColor}">${formatPct(changePct)}</b></div>`,
              averageLineEnabled ? `<div>均价：<b>${formatClose(point.avg_price ?? null)}</b></div>` : "",
              `<div>分时量：<b>${formatVolume(point.volume)}</b></div>`,
            ]
              .filter(Boolean)
              .join("")
          },
        },
        xAxis: [
        {
          type: "value",
          boundaryGap: false,
          min: 0,
          max: 240,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 11,
            formatter: (value: number) => formatSessionTick(value),
          },
          splitLine: { show: false },
        },
        {
          type: "value",
          boundaryGap: true,
          gridIndex: 1,
          min: 0,
          max: 240,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          type: "value",
          min: chartModel.deltaDomain[0],
          max: chartModel.deltaDomain[1],
          scale: true,
          axisLine: { show: false },
          axisTick: { show: false },
          splitNumber: 4,
          splitLine: { lineStyle: { color: "#e2e8f0", type: "dashed" } },
          axisLabel: {
            color: "#64748b",
            fontSize: 11,
            formatter: (value: number) =>
              referenceClose != null ? (referenceClose + value).toFixed(0) : value.toFixed(0),
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
        ...(referenceClose != null
          ? [{
              name: "昨收",
              type: "line" as const,
              data: chartModel.referenceSeries,
              showSymbol: false,
              silent: true,
              lineStyle: { color: "#cbd5e1", width: 1, type: "dashed" as const },
              tooltip: { show: false },
              z: 6,
            }]
          : []),
        {
          name: "上涨区域",
          type: "custom",
          coordinateSystem: "cartesian2d",
          clip: true,
          renderItem: renderSignedSlice("up"),
          data: chartModel.upSegments.map((segment) => ({
            value: [...segment.values, segment.startIntensity, segment.endIntensity],
          })),
          tooltip: { show: false },
          z: 9,
        },
        {
          name: "下跌区域",
          type: "custom",
          coordinateSystem: "cartesian2d",
          clip: true,
          renderItem: renderSignedSlice("down"),
          data: chartModel.downSegments.map((segment) => ({
            value: [...segment.values, segment.startIntensity, segment.endIntensity],
          })),
          tooltip: { show: false },
          z: 10,
        },
        {
          name: "价格",
          type: "line",
          data: chartModel.priceSeries,
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 0, opacity: 0 },
          z: 1,
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
      },
      { notMerge: true },
    )
  }, [averageLineEnabled, chartModel, item.timeshare, referenceClose])

  const heroTone =
    directionTone === "up"
      ? "text-red-600"
      : directionTone === "down"
        ? "text-emerald-600"
        : "text-slate-900"

  return (
    <section className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
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

      <div className="relative h-[300px] w-full overflow-hidden bg-white sm:h-[360px] xl:h-[460px]">
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
            {/* 优先读今开 (1m bar open); eltdx 历史分时无 open 字段时退到 first price */}
            {formatClose(
              firstPoint?.open != null && firstPoint.open > 0
                ? firstPoint.open
                : firstPoint?.price ?? null,
            )}
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
