import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { createStockAnnotation, deleteStockAnnotation, fetchStockIntraday, listStockAnnotations, runApplicationAnalysis } from "@/lib/api"
import { notification } from "@/components/ui/notification"
import { Skeleton } from "@/components/ui/skeleton"
import DogLoader from "@/components/loader/dog-loader"

import type {
  ApplicationAnalysisResponse,
  StockAdjust,
  StockAnnotation,
  StockIntradayResponse,
  StockKlineBar,
  StockSignalPoint,
  StockTargetType,
} from "../../stock-chart/lib/types"

type MinutePeriod = "1m" | "5m" | "15m" | "30m"
type IntradayTab = "timeshare" | "kline"
type MarkerMode = "none" | "B" | "S"
const REQUESTED_PERIODS: MinutePeriod[] = ["5m", "15m", "30m", "1m"]
// B/S 标记复用已有 annotation 通道，统一存到 "bs_signals" 周期下，跨 period 共享
const BS_SIGNALS_PERIOD = "bs_signals"

function annotationToSignal(annotation: StockAnnotation): StockSignalPoint | null {
  if (annotation.overlay_type !== "bs_point") return null
  const point = annotation.points?.[0]
  if (!point) return null
  const text = annotation.text || ""
  const side = text.startsWith("S") ? "S" : text.startsWith("B") ? "B" : null
  if (!side) return null
  return {
    id: annotation.id,
    timestamp: point.timestamp,
    price: point.value,
    side,
    label: side,
    reason: text.slice(2) || "manual",
    source: "manual",
    period: BS_SIGNALS_PERIOD,
  }
}

function buildTimeshareKey(item: { trade_date?: string | null; timestamp: number }) {
  return `${item.trade_date || "unknown"}__${item.timestamp}`
}

function formatPrice(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—"
}

function formatPct(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—"
}

function formatAmount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value).toLocaleString("en-US") : "—"
}

function buildMinuteChartData(items: StockKlineBar[]) {
  const maxVolume = items.reduce((max, item) => Math.max(max, item.volume || 0), 0)
  const volumeScale = maxVolume > 0 ? maxVolume : 1
  return items.map((item) => ({
    ...item,
    time_label: new Date(item.timestamp).toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" }),
    candleTop: Math.max(item.open, item.close),
    candleBottom: Math.min(item.open, item.close),
    isUp: item.close >= item.open,
    volumeRatioVisual: item.volume / volumeScale,
  }))
}

function computePriceDomain(values: number[]) {
  if (!values.length) return [0, 1] as const
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, max * 0.01, 0.1)
  return [min - spread * 0.12, max + spread * 0.12] as const
}

function CandleOverlay({
  bars,
  yMin,
  yMax,
}: {
  bars: Array<ReturnType<typeof buildMinuteChartData>[number]>
  yMin: number
  yMax: number
}) {
  const width = 1400
  const height = 440
  const margin = { top: 12, right: 18, bottom: 36, left: 58 }
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  if (!bars.length || yMax <= yMin) return null

  const usableWidth = width - margin.left - margin.right
  const usableHeight = 300
  const volumeTop = margin.top + usableHeight + 20
  const volumeHeight = height - volumeTop - margin.bottom
  const step = bars.length > 1 ? usableWidth / (bars.length - 1) : usableWidth
  const candleWidth = Math.max(4, Math.min(14, step * 0.66))

  const yForPrice = (price: number) => margin.top + ((yMax - price) / (yMax - yMin)) * usableHeight
  const volumeScale = Math.max(...bars.map((bar) => bar.volume || 0), 1)
  const labelStep = Math.max(1, Math.ceil(bars.length / 6))

  const centerXAt = (index: number) => margin.left + (bars.length > 1 ? step * index : usableWidth / 2)
  const hoverBar = hoverIndex !== null ? bars[hoverIndex] : null
  const hoverX = hoverIndex !== null ? centerXAt(hoverIndex) : null
  const hoverPrevClose = hoverIndex !== null && hoverIndex > 0 ? bars[hoverIndex - 1].close : hoverBar?.open
  const hoverChange = hoverBar ? hoverBar.close - (hoverPrevClose ?? hoverBar.open) : 0
  const hoverChangePct = hoverBar && (hoverPrevClose ?? hoverBar.open)
    ? (hoverChange / (hoverPrevClose ?? hoverBar.open)) * 100
    : 0
  const changeColor = hoverChange >= 0 ? "#fca5a5" : "#86efac"

  return (
    <div className="relative h-full w-full">
      <svg viewBox={`0 0 ${width} ${height}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
        <rect x="0" y="0" width={width} height={height} fill="#ffffff" />
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const lineY = margin.top + usableHeight * ratio
          return <line key={ratio} x1={margin.left} x2={width - margin.right} y1={lineY} y2={lineY} stroke="#e2e8f0" strokeDasharray="4 4" />
        })}
        <line x1={margin.left} x2={width - margin.right} y1={volumeTop - 8} y2={volumeTop - 8} stroke="#cbd5e1" strokeDasharray="4 4" />
        {[yMax, (yMax + yMin) / 2, yMin].map((value) => {
          const labelY = yForPrice(value)
          return (
            <text key={value} x={10} y={labelY + 4} fontSize="11" fill="#64748b">
              {value.toFixed(2)}
            </text>
          )
        })}
        {bars.map((bar, index) => {
          const centerX = centerXAt(index)
          const wickTop = yForPrice(bar.high)
          const wickBottom = yForPrice(bar.low)
          const bodyTop = yForPrice(bar.candleTop)
          const bodyBottom = yForPrice(bar.candleBottom)
          const bodyHeight = Math.max(bodyBottom - bodyTop, 1.5)
          const color = bar.isUp ? "#dc2626" : "#16a34a"
          const volumeY = volumeTop + (1 - (bar.volume || 0) / volumeScale) * Math.max(volumeHeight - 4, 12)
          const volumeBottom = volumeTop + volumeHeight
          const isHover = hoverIndex === index

          return (
            <g
              key={bar.timestamp}
              onMouseEnter={() => setHoverIndex(index)}
              onMouseLeave={() => setHoverIndex((current) => (current === index ? null : current))}
              onFocus={() => setHoverIndex(index)}
              onBlur={() => setHoverIndex((current) => (current === index ? null : current))}
              style={{ cursor: "crosshair" }}
            >
              {/* 透明命中区域，避免线段之间难以悬停 */}
              <rect
                x={centerX - Math.max(step / 2, candleWidth / 2 + 4)}
                y={margin.top}
                width={Math.max(step, candleWidth + 8)}
                height={Math.max(usableHeight + (volumeHeight + 8), 80)}
                fill="transparent"
                pointerEvents="all"
              />
              <line
                x1={centerX}
                x2={centerX}
                y1={wickTop}
                y2={wickBottom}
                stroke={color}
                strokeWidth={isHover ? 1.8 : 1.2}
              />
              <rect
                x={centerX - candleWidth / 2}
                y={bodyTop}
                width={candleWidth}
                height={bodyHeight}
                fill={bar.isUp ? "#fee2e2" : "#dcfce7"}
                stroke={color}
                strokeWidth={isHover ? 2 : 1.2}
                rx={1}
              />
              <rect
                x={centerX - Math.max(candleWidth * 0.42, 2)}
                y={volumeY}
                width={Math.max(candleWidth * 0.84, 4)}
                height={Math.max(volumeBottom - volumeY, 2)}
                fill={color}
                fillOpacity={isHover ? 0.55 : 0.25}
                rx={1}
              />
              {index % labelStep === 0 || index === bars.length - 1 ? (
                <text x={centerX} y={height - 10} textAnchor="middle" fontSize="11" fill="#64748b">
                  {bar.time_label}
                </text>
              ) : null}
            </g>
          )
        })}

        {hoverBar && hoverX !== null ? (
          <g pointerEvents="none">
            {/* 悬停竖线 */}
            <line
              x1={hoverX}
              x2={hoverX}
              y1={margin.top}
              y2={volumeTop + volumeHeight}
              stroke="#0f172a"
              strokeWidth={1}
              strokeDasharray="3 3"
              opacity={0.55}
            />
            {/* 悬停 K 柱外框高亮 */}
            {(() => {
              const wickTop = yForPrice(hoverBar.high)
              const wickBottom = yForPrice(hoverBar.low)
              const color = hoverBar.isUp ? "#dc2626" : "#16a34a"
              return (
                <rect
                  x={hoverX - candleWidth / 2 - 2}
                  y={wickTop - 2}
                  width={candleWidth + 4}
                  height={wickBottom - wickTop + 4}
                  fill="none"
                  stroke={color}
                  strokeWidth={1}
                  strokeDasharray="2 2"
                  opacity={0.7}
                  rx={2}
                />
              )
            })()}
          </g>
        ) : null}
      </svg>

      {hoverBar ? (
        <div className="pointer-events-none absolute right-3 top-3 z-10 w-[200px] rounded-lg border border-slate-700/40 bg-slate-900/95 px-3 py-2 text-xs text-slate-100 shadow-lg">
          <div className="mb-1.5 text-[13px] font-semibold text-white">
            {hoverBar.trade_date ? `${hoverBar.trade_date} ` : ""}{hoverBar.time_label}
          </div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
            <dt className="text-slate-400">开</dt>
            <dd className="text-right tabular-nums text-slate-100">{formatPrice(hoverBar.open)}</dd>
            <dt className="text-slate-400">高</dt>
            <dd className="text-right tabular-nums text-rose-300">{formatPrice(hoverBar.high)}</dd>
            <dt className="text-slate-400">低</dt>
            <dd className="text-right tabular-nums text-emerald-300">{formatPrice(hoverBar.low)}</dd>
            <dt className="text-slate-400">收</dt>
            <dd className="text-right tabular-nums text-slate-100">{formatPrice(hoverBar.close)}</dd>
            <dt className="text-slate-400">涨跌</dt>
            <dd className="text-right tabular-nums" style={{ color: changeColor }}>
              {hoverChange >= 0 ? "+" : ""}
              {formatPrice(hoverChange)}
            </dd>
            <dt className="text-slate-400">涨跌幅</dt>
            <dd className="text-right tabular-nums" style={{ color: changeColor }}>
              {hoverChange >= 0 ? "+" : ""}
              {formatPct(hoverChangePct)}
            </dd>
            <dt className="text-slate-400">成交量</dt>
            <dd className="text-right tabular-nums text-slate-100">{formatAmount(hoverBar.volume)}</dd>
            <dt className="text-slate-400">换手率</dt>
            <dd className="text-right tabular-nums text-slate-100">{formatPct(hoverBar.turnover_rate)}</dd>
          </dl>
        </div>
      ) : null}
    </div>
  )
}

export function IntradayAnalysisDialog({
  open,
  onOpenChange,
  targetType,
  symbol,
  name,
  adjust,
  tradeDate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  targetType: StockTargetType
  symbol: string
  name: string
  adjust: StockAdjust
  tradeDate?: string | null
}) {
  const [period, setPeriod] = useState<MinutePeriod>("5m")
  const [tab, setTab] = useState<IntradayTab>("timeshare")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<StockIntradayResponse | null>(null)
  const [aiAnalysis, setAiAnalysis] = useState<ApplicationAnalysisResponse | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)
  const [reviewNote, setReviewNote] = useState("")
  const [markerMode, setMarkerMode] = useState<MarkerMode>("none")
  const [markers, setMarkers] = useState<StockSignalPoint[]>([])
  const [chartSize, setChartSize] = useState({ width: 0, height: 0 })
  const chartWrapperRef = useRef<HTMLDivElement | null>(null)
  const markersRef = useRef<StockSignalPoint[]>([])
  markersRef.current = markers

  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true)
    setError(null)
    void fetchStockIntraday({ targetType, symbol, name, adjust, tradeDate: tradeDate || undefined, periods: REQUESTED_PERIODS })
      .then((data) => {
        if (active) setPayload(data)
      })
      .catch((err) => {
        if (active) {
          const msg = err instanceof Error ? err.message : "加载当日分时失败"
          setPayload(null)
          setError(msg)
          notification.danger({ title: "加载当日分时失败", description: msg })
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [adjust, name, open, symbol, targetType, tradeDate])

  useEffect(() => {
    if (!payload) return
    const candidates: MinutePeriod[] = ["5m", "15m", "30m", "1m"]
    const next = candidates.find((item) => (payload.minute_bars?.[item] || []).length > 0)
    if (next && (!payload.minute_bars?.[period] || payload.minute_bars[period].length === 0)) {
      setPeriod(next)
    }
  }, [payload, period])

  const minuteBars = payload?.minute_bars?.[period] || []
  const minuteChartData = useMemo(() => buildMinuteChartData(minuteBars), [minuteBars])
  const minutePriceDomain = useMemo(
    () => computePriceDomain(minuteBars.flatMap((item) => [item.low, item.high]).filter((value) => Number.isFinite(value))),
    [minuteBars],
  )

  const intradayPriceDomain = useMemo(
    () =>
      computePriceDomain(
        (payload?.timeshare || []).flatMap((item) => [item.price, item.avg_price ?? item.price]).filter((value) => Number.isFinite(value)),
      ),
    [payload],
  )

  const timeshareVolumeMax = useMemo(
    () => (payload?.timeshare || []).reduce((max, item) => Math.max(max, item.volume || 0), 0),
    [payload],
  )
  const timeshareVolumeDomain = useMemo<[number, number]>(
    () => [0, Math.max(timeshareVolumeMax * 2.6, 1)],
    [timeshareVolumeMax],
  )

  const timeshareTickFormatter = useCallback(
    (value: string) => {
      const point = (payload?.timeshare || []).find((item) => buildTimeshareKey(item) === value)
      if (!point) return value
      return point.time_label || value
    },
    [payload],
  )

  const handleRunAiAnalysis = useCallback(async () => {
    setAiLoading(true)
    setAiError(null)
    try {
      const result = await runApplicationAnalysis({ targetType, symbol, name, adjust })
      setAiAnalysis(result)
      notification.success({
        title: "AI 逻辑分析完成",
        description: `${name} · ${symbol}`,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : "AI 逻辑分析失败"
      setAiError(msg)
      setAiAnalysis(null)
      notification.danger({ title: "AI 逻辑分析失败", description: msg })
    } finally {
      setAiLoading(false)
    }
  }, [adjust, name, symbol, targetType])

  const aiSummary = aiAnalysis?.analysis_result?.summary
  const aiWarnings = (aiAnalysis?.analysis_result?.data_quality?.warnings as string[] | undefined) || []
  const aiTrend = (aiAnalysis?.analysis_result?.trend_state as Record<string, unknown> | undefined) || null
  const aiSentiment = (aiAnalysis?.analysis_result?.market_sentiment as Record<string, unknown> | undefined) || null

  // 进入对话框 / 切换股票时，从后端加载已有的 B/S 标记
  useEffect(() => {
    if (!open) return
    let active = true
    void (async () => {
      try {
        const annotations = await listStockAnnotations(targetType, symbol, BS_SIGNALS_PERIOD)
        if (!active) return
        const signals = annotations
          .map(annotationToSignal)
          .filter((item): item is StockSignalPoint => Boolean(item))
        setMarkers(signals)
      } catch (err) {
        // 静默失败：标记加载失败不影响主流程
        if (active) setMarkers([])
        const msg = err instanceof Error ? err.message : "读取已有 B/S 标记失败"
        notification.warn({ title: "读取已有标记失败", description: msg })
      }
    })()
    return () => {
      active = false
    }
  }, [open, symbol, targetType])

  // 数据回来时不再清空标记（标记跨日期共享），仅复位工具状态
  useEffect(() => {
    setMarkerMode("none")
  }, [payload])

  // 通过 wrapper 容器的 click 事件 + 几何反推落点 index（Recharts 的 chart onClick 在背景上不可靠）
  const handleChartWrapperClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (markerMode === "none" || tab !== "timeshare") return
      const container = chartWrapperRef.current
      const points = payload?.timeshare
      if (!container || !points || points.length === 0) return

      const rect = container.getBoundingClientRect()
      // Recharts 图表内的左 YAxis width=52 + chart margin left=-14 → plot 起点 ~38
      // 右 margin=8
      const LEFT_OFFSET = 38
      const RIGHT_OFFSET = 8
      const clickX = event.clientX - rect.left
      if (clickX < LEFT_OFFSET || clickX > rect.width - RIGHT_OFFSET) return

      const plotWidth = rect.width - LEFT_OFFSET - RIGHT_OFFSET
      const step = plotWidth / Math.max(points.length - 1, 1)
      const index = Math.round((clickX - LEFT_OFFSET) / step)
      if (index < 0 || index >= points.length) return
      const point = points[index]
      if (!point) return

      const optimistic: StockSignalPoint = {
        id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        timestamp: point.timestamp,
        trade_date: point.trade_date ?? undefined,
        price: point.price,
        side: markerMode,
        source: "manual",
        period: BS_SIGNALS_PERIOD,
      }
      setMarkers((prev) => [...prev, optimistic])
      setMarkerMode("none")

      // 持久化：复用 annotation 接口，overlay_type=bs_point
      void (async () => {
        try {
          const annotation = await createStockAnnotation({
            target_type: targetType,
            symbol,
            period: BS_SIGNALS_PERIOD,
            overlay_type: "bs_point",
            points: [{ timestamp: point.timestamp, value: point.price }],
            text: `${markerMode}:manual`,
            styles: { side: markerMode, source: "manual", trade_date: point.trade_date ?? null },
          })
          const persisted = annotationToSignal(annotation)
          if (persisted) {
            setMarkers((prev) => prev.map((m) => (m.id === optimistic.id ? persisted : m)))
            notification.success({
              title: `${markerMode === "B" ? "买入" : "卖出"}点已保存`,
              description: `${point.trade_date || ""} @ ${formatPrice(point.price)}`,
            })
          }
        } catch (err) {
          // 持久化失败：把乐观标记回滚
          setMarkers((prev) => prev.filter((m) => m.id !== optimistic.id))
          const msg = err instanceof Error ? err.message : "保存分时标记失败"
          notification.danger({ title: "保存分时标记失败", description: msg })
        }
      })()
    },
    [markerMode, payload, symbol, tab, targetType],
  )

  const handleRemoveMarker = useCallback(
    (id: string) => {
      setMarkers((prev) => prev.filter((m) => m.id !== id))
      void deleteStockAnnotation(targetType, symbol, BS_SIGNALS_PERIOD, id).catch((err) => {
        // 失败时回滚
        const rollback = markersRef.current.find((m) => m.id === id)
        if (rollback) setMarkers((prev) => [...prev, rollback].sort((a, b) => a.timestamp - b.timestamp))
        const msg = err instanceof Error ? err.message : "删除分时标记失败"
        notification.danger({ title: "删除分时标记失败", description: msg })
      })
    },
    [symbol, targetType],
  )

  const handleClearMarkers = useCallback(() => {
    const targets = [...markersRef.current]
    setMarkers([])
    void Promise.all(
      targets.map((m) => deleteStockAnnotation(targetType, symbol, BS_SIGNALS_PERIOD, m.id)),
    ).catch((err) => {
      // 失败时回滚
      setMarkers(targets)
      const msg = err instanceof Error ? err.message : "清空分时标记失败"
      notification.danger({ title: "清空分时标记失败", description: msg })
    })
  }, [symbol, targetType])

  // 监听图表容器尺寸，喂给下面的 marker 像素定位
  useEffect(() => {
    if (!open || tab !== "timeshare") return
    const container = chartWrapperRef.current
    if (!container) return
    const update = () => {
      const rect = container.getBoundingClientRect()
      setChartSize((prev) =>
        prev.width === rect.width && prev.height === rect.height
          ? prev
          : { width: rect.width, height: rect.height },
      )
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(container)
    return () => observer.disconnect()
  }, [open, tab])

  // 计算每个 marker 在屏幕上的 (x, y) 像素坐标
  const visibleMarkers = useMemo(() => {
    const points = payload?.timeshare
    if (!points || points.length === 0) return []
    if (chartSize.width <= 0 || chartSize.height <= 0) return []
    if (intradayPriceDomain[0] === intradayPriceDomain[1]) return []

    const LEFT_OFFSET = 38
    const RIGHT_OFFSET = 8
    const TOP_OFFSET = 18
    const BOTTOM_OFFSET = 0
    const plotWidth = chartSize.width - LEFT_OFFSET - RIGHT_OFFSET
    const plotHeight = chartSize.height - TOP_OFFSET - BOTTOM_OFFSET
    if (plotWidth <= 0 || plotHeight <= 0) return []
    const step = plotWidth / Math.max(points.length - 1, 1)
    const [yMin, yMax] = intradayPriceDomain
    const ySpan = yMax - yMin

    const result: Array<{ id: string; side: "B" | "S"; x: number; y: number; price: number }> = []
    for (const marker of markers) {
      const index = points.findIndex((p) => p.timestamp === marker.timestamp)
      if (index < 0) continue
      const x = LEFT_OFFSET + step * index
      const y = TOP_OFFSET + ((yMax - marker.price) / ySpan) * plotHeight
      if (Number.isNaN(x) || Number.isNaN(y)) continue
      result.push({ id: marker.id, side: marker.side, x, y, price: marker.price })
    }
    return result
  }, [chartSize, intradayPriceDomain, markers, payload])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[92vh] !max-w-[96vw] flex-col overflow-hidden rounded-2xl border-slate-200 bg-white p-0 shadow-[0_24px_80px_rgba(15,23,42,0.18)]">
        <DialogHeader className="border-b border-slate-200 px-6 py-5">
          <DialogTitle className="pr-10 text-xl text-slate-900">{name} · 当日分时分析</DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-3 text-slate-500">
            <span>{symbol}</span>
            <span>交易日 {payload?.trade_date || "—"}</span>
            <span>数据源 {payload?.source || "—"}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Tabs value={tab} onValueChange={(value) => value && setTab(value as IntradayTab)}>
              <TabsList className="rounded-lg border border-slate-200 bg-slate-50 p-1">
                <TabsTrigger value="timeshare" className="rounded-md px-4 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
                  分时
                </TabsTrigger>
                <TabsTrigger value="kline" className="rounded-md px-4 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
                  K线
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                {tab === "timeshare" ? (
                  <>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-slate-900" />分时</span>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-400" />均价</span>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-rose-500" />上涨量</span>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />下跌量</span>
                  </>
                ) : (
                  <>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-rose-500" />上涨K</span>
                    <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />下跌K</span>
                  </>
                )}
              </div>
              {tab === "kline" ? (
                <ToggleGroup type="single" value={period} onValueChange={(value) => value && setPeriod(value as MinutePeriod)} className="rounded-lg border border-slate-200 bg-slate-50 p-1">
                  <ToggleGroupItem value="1m" className="rounded-md px-3 text-xs">1m</ToggleGroupItem>
                  <ToggleGroupItem value="5m" className="rounded-md px-3 text-xs">5m</ToggleGroupItem>
                  <ToggleGroupItem value="15m" className="rounded-md px-3 text-xs">15m</ToggleGroupItem>
                  <ToggleGroupItem value="30m" className="rounded-md px-3 text-xs">30m</ToggleGroupItem>
                </ToggleGroup>
              ) : null}
            </div>
          </div>

          {loading ? (
            <DogLoader overlay size={25} label="正在加载当日分时和分钟 K..." />
          ) : error ? (
            <div className="grid min-h-0 flex-1 place-items-center rounded-2xl border border-rose-200 bg-rose-50 px-6 text-sm text-rose-600">
              {error}
            </div>
          ) : (
            <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,3fr)]">
              <section className="flex min-h-0 flex-col rounded-2xl border border-slate-200 bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">
                      {tab === "timeshare" ? "分时图" : `分钟 K (${period})`}
                    </div>
                    <div className="text-xs text-slate-500">
                      {tab === "timeshare"
                        ? "黑线为即时价，黄线为均价，下方柱体为分时量"
                        : "下方浅色柱体为成交量"}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {tab === "timeshare" ? (
                      <>
                        <div className="text-xs text-slate-500">标记</div>
                        <ToggleGroup
                          type="single"
                          value={markerMode}
                          onValueChange={(value) => {
                            if (value === "B" || value === "S") {
                              setMarkerMode(value)
                            } else {
                              setMarkerMode("none")
                            }
                          }}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-0.5"
                        >
                          <ToggleGroupItem value="B" className="rounded-md px-2.5 text-xs data-[state=on]:bg-rose-500 data-[state=on]:text-white">
                            B
                          </ToggleGroupItem>
                          <ToggleGroupItem value="S" className="rounded-md px-2.5 text-xs data-[state=on]:bg-emerald-500 data-[state=on]:text-white">
                            S
                          </ToggleGroupItem>
                        </ToggleGroup>
                        {markers.length > 0 ? (
                          <Button size="sm" variant="ghost" onClick={handleClearMarkers} className="h-7 px-2 text-xs text-slate-500 hover:text-slate-900">
                            清空 ({markers.length})
                          </Button>
                        ) : null}
                        {markerMode !== "none" ? (
                          <div className="text-xs text-rose-500">点击分时图落点标记 {markerMode}</div>
                        ) : null}
                      </>
                    ) : (
                      <div className="text-xs text-slate-400">支持全天收盘回看</div>
                    )}
                  </div>
                </div>
                <div
                  ref={chartWrapperRef}
                  onClick={handleChartWrapperClick}
                  className={`relative min-h-0 flex-1 ${markerMode !== "none" && tab === "timeshare" ? "cursor-crosshair" : ""}`}
                >
                  {tab === "timeshare" ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart
                        data={(payload?.timeshare || []).map((item) => ({
                          ...item,
                          _key: buildTimeshareKey(item),
                          volumeDirection: item.price >= (item.avg_price ?? item.price) ? "up" : "down",
                        }))}
                        margin={{ top: 18, right: 8, left: -14, bottom: 0 }}
                      >
                        <CartesianGrid stroke="#e2e8f0" strokeDasharray="4 4" vertical={false} />
                        <XAxis
                          dataKey="_key"
                          tick={{ fontSize: 11, fill: "#64748b" }}
                          minTickGap={28}
                          tickFormatter={timeshareTickFormatter}
                        />
                        <YAxis
                          yAxisId="price"
                          domain={intradayPriceDomain as [number, number]}
                          tick={{ fontSize: 11, fill: "#64748b" }}
                          tickFormatter={(value) => Number(value).toFixed(2)}
                          width={52}
                        />
                        <YAxis
                          yAxisId="volume"
                          orientation="right"
                          domain={timeshareVolumeDomain}
                          hide
                        />
                        <Tooltip
                          formatter={(value, key) => {
                            if (key === "price") return [formatPrice(value), "价格"]
                            if (key === "avg_price") return [formatPrice(value), "均价"]
                            if (key === "volume") return [formatAmount(value), "分时量"]
                            return [String(value ?? "—"), String(key)]
                          }}
                          labelFormatter={(_, tooltipPayload) => {
                            const point = tooltipPayload && tooltipPayload[0] && tooltipPayload[0].payload
                            if (!point) return ""
                            return `${point.trade_date || ""} ${point.time_label || ""}`
                          }}
                          contentStyle={{ fontSize: 12 }}
                        />
                        <Bar
                          yAxisId="volume"
                          dataKey="volume"
                          isAnimationActive={false}
                          barSize={3}
                          fill="#dc2626"
                          shape={(props: { x?: number; y?: number; width?: number; height?: number; payload?: { volumeDirection?: "up" | "down" } }) => {
                            const { x, y, width, height, payload } = props
                            if (x === undefined || y === undefined || width === undefined || height === undefined) return null
                            const isUp = payload?.volumeDirection === "up"
                            return (
                              <rect
                                x={x}
                                y={y}
                                width={width}
                                height={height}
                                fill={isUp ? "#dc2626" : "#16a34a"}
                                fillOpacity={0.55}
                                rx={0.5}
                              />
                            )
                          }}
                        />
                        <Line
                          yAxisId="price"
                          type="monotone"
                          dataKey="price"
                          stroke="#0f172a"
                          dot={false}
                          strokeWidth={1.9}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="price"
                          type="monotone"
                          dataKey="avg_price"
                          stroke="#fbbf24"
                          dot={false}
                          strokeWidth={1.6}
                          connectNulls={false}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  ) : minuteChartData.length ? (
                    <CandleOverlay bars={minuteChartData} yMin={minutePriceDomain[0]} yMax={minutePriceDomain[1]} />
                  ) : (
                    <div className="grid h-full place-items-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
                      当前周期暂无可用分钟 K 数据
                    </div>
                  )}
                  {tab === "timeshare" && visibleMarkers.length > 0 ? (
                    <svg
                      className="pointer-events-none absolute inset-0 h-full w-full"
                      width={chartSize.width}
                      height={chartSize.height}
                    >
                      {visibleMarkers.map((m) => {
                        const isUp = m.side === "B"
                        const color = isUp ? "#dc2626" : "#16a34a"
                        return (
                          <g key={m.id}>
                            <line
                              x1={m.x}
                              x2={m.x}
                              y1={0}
                              y2={chartSize.height}
                              stroke={color}
                              strokeWidth={1}
                              strokeDasharray="3 3"
                              opacity={0.45}
                            />
                            <circle cx={m.x} cy={m.y} r={5} fill={color} stroke="#ffffff" strokeWidth={2} />
                            <rect
                              x={m.x - 9}
                              y={m.y + (isUp ? -22 : 8)}
                              width={18}
                              height={14}
                              rx={3}
                              fill={color}
                            />
                            <text
                              x={m.x}
                              y={m.y + (isUp ? -9 : 19)}
                              textAnchor="middle"
                              fontSize="10"
                              fontWeight="700"
                              fill="#ffffff"
                            >
                              {m.side}
                            </text>
                          </g>
                        )
                      })}
                    </svg>
                  ) : null}
                </div>
                {tab === "timeshare" && markers.length > 0 ? (
                  <div className="mt-3 flex max-h-20 flex-wrap items-center gap-1.5 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50/60 px-2 py-1.5">
                    <div className="text-xs text-slate-500">标记列表：</div>
                    {markers
                      .slice()
                      .sort((a, b) => a.timestamp - b.timestamp)
                      .map((marker) => {
                        const isUp = marker.side === "B"
                        const color = isUp ? "bg-rose-500 text-white" : "bg-emerald-500 text-white"
                        const timeLabel = new Date(marker.timestamp).toLocaleTimeString("zh-CN", {
                          hour12: false,
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                        return (
                          <span
                            key={marker.id}
                            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${color}`}
                          >
                            <span>{marker.side}</span>
                            <span className="opacity-90">@ {timeLabel}</span>
                            <span className="opacity-80">{formatPrice(marker.price)}</span>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation()
                                handleRemoveMarker(marker.id)
                              }}
                              className="ml-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-white/30 text-white hover:bg-white/50"
                              aria-label="删除标记"
                            >
                              ×
                            </button>
                          </span>
                        )
                      })}
                  </div>
                ) : null}
              </section>

              <aside className="flex min-h-0 flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                {/* AI 逻辑分析 */}
                <div className="flex min-h-0 flex-1 flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-900">AI 逻辑分析</div>
                    <Button size="sm" onClick={handleRunAiAnalysis} disabled={aiLoading} className="h-7 px-3 text-xs">
                      {aiLoading ? "分析中…" : "运行分析"}
                    </Button>
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-700">
                    {aiLoading ? (
                      <div className="flex flex-col items-center gap-3 py-6 text-slate-500">
                        <Skeleton className="h-4 w-3/4" />
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-5/6" />
                        <Skeleton className="h-4 w-1/2" />
                      </div>
                    ) : aiError ? (
                      <div className="text-rose-600">{aiError}</div>
                    ) : aiAnalysis ? (
                      <div className="space-y-3">
                        {typeof aiSummary?.current_status === "string" && aiSummary.current_status ? (
                          <div className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-800">
                            <span className="text-slate-400">当前状态：</span>
                            {aiSummary.current_status}
                          </div>
                        ) : null}
                        {aiWarnings.length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-amber-600">数据质量提醒</div>
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-amber-700">
                              {aiWarnings.map((w, i) => (
                                <li key={i}>{w}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {Array.isArray(aiSummary?.main_observations) && aiSummary?.main_observations && aiSummary.main_observations.length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-slate-700">主要观察</div>
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">
                              {aiSummary.main_observations.map((obs, i) => (
                                <li key={i}>{String(obs)}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {Array.isArray(aiSummary?.main_support) && aiSummary?.main_support && aiSummary.main_support.length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-slate-700">主要支撑</div>
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">
                              {aiSummary.main_support.map((s, i) => (
                                <li key={i}>{String(s)}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {Array.isArray(aiSummary?.main_resistance) && aiSummary?.main_resistance && aiSummary.main_resistance.length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-slate-700">主要压力</div>
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">
                              {aiSummary.main_resistance.map((r, i) => (
                                <li key={i}>{String(r)}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {Array.isArray(aiSummary?.main_risks) && aiSummary?.main_risks && aiSummary.main_risks.length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-rose-600">主要风险</div>
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-rose-700">
                              {aiSummary.main_risks.map((r, i) => (
                                <li key={i}>{String(r)}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {aiTrend && Object.keys(aiTrend).length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-slate-700">趋势状态</div>
                            <div className="space-y-0.5 text-xs text-slate-700">
                              {Object.entries(aiTrend).slice(0, 6).map(([key, value]) => (
                                <div key={key} className="flex justify-between gap-2">
                                  <span className="text-slate-400">{key}</span>
                                  <span className="text-right">
                                    {value === null || value === undefined
                                      ? "—"
                                      : typeof value === "object"
                                        ? JSON.stringify(value)
                                        : String(value)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {aiSentiment && Object.keys(aiSentiment).length > 0 ? (
                          <div>
                            <div className="mb-1 text-xs font-medium text-slate-700">市场情绪</div>
                            <div className="space-y-0.5 text-xs text-slate-700">
                              {Object.entries(aiSentiment).slice(0, 6).map(([key, value]) => (
                                <div key={key} className="flex justify-between gap-2">
                                  <span className="text-slate-400">{key}</span>
                                  <span className="text-right">
                                    {value === null || value === undefined
                                      ? "—"
                                      : typeof value === "object"
                                        ? JSON.stringify(value)
                                        : String(value)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="grid h-full place-items-center text-center text-slate-400">
                        点击「运行分析」让 AI 解读当日分时和分钟 K
                      </div>
                    )}
                  </div>
                </div>

                {/* 复盘笔记 */}
                <div className="flex shrink-0 flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-900">复盘笔记</div>
                    <div className="text-xs text-slate-400">{reviewNote.length} 字</div>
                  </div>
                  <textarea
                    value={reviewNote}
                    onChange={(event) => setReviewNote(event.target.value)}
                    placeholder="记录复盘心得、交易思路、当日关键节点…"
                    className="h-[180px] w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  />
                </div>

                <div className="flex justify-end">
                  <Button variant="outline" onClick={() => onOpenChange(false)}>关闭</Button>
                </div>
              </aside>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
