/**
 * POC: 情绪折线图叠加上证指数
 *
 * 功能: 在情绪分折线图 (0-100) 上叠加上证指数日线 (右轴 auto-scale, 虚线)
 * 目的: 验证双 Y 轴 + 上证指数叠加效果，为合并到 market-sentiment 页做准备
 *
 * 数据流:
 *   fetchMarketSentimentIndexHistory → 情绪分历史 (YYYY-MM-DD)
 *   fetchIndexDailyHistory(code=000001) → 上证指数日线 close
 *   → 按 tradeDate 对齐 → SentimentLine(overlay=shOverlay)
 */
import { useEffect, useMemo, useRef, useState } from "react"
import * as echarts from "echarts/core"
import { CustomChart, LineChart } from "echarts/charts"
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"
import type { EChartsOption } from "echarts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchMarketSentimentIndexHistory,
  fetchIndexDailyHistory,
  type MarketSentimentIndexHistoryItem,
  type IndexDailyItem,
} from "@/lib/api"
import { scoreToColor, scoreToRgb } from "../../market/market-sentiment/lib/color"

echarts.use([
  CustomChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  CanvasRenderer,
])

// ─── 情绪折线组件 (复刻自 sentiment-line.tsx) ───────────────────────────────
interface SentimentLinePoint { date: string; value: number; level?: string }
interface OverlayPoint { date: string; value: number }

function SentimentLine({ data, height = 320, overlay }: {
  data: SentimentLinePoint[]
  height?: number
  overlay?: { name: string; color?: string; data: OverlayPoint[] }
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((d) => d.date)
    const values = data.map((d) => d.value)

    const minValue = values.length ? Math.min(...values) : 0
    const maxValue = values.length ? Math.max(...values) : 100
    const valueRange = Math.max(1, maxValue - minValue)
    const padding = Math.max(3, valueRange * 0.10)

    const recentBars = 63
    const totalBars = values.length
    const zoomStart = totalBars > recentBars
      ? Math.max(0, 100 - (recentBars / totalBars) * 100)
      : 0

    const yMin = Math.max(0, Math.floor(Math.min(minValue, 50) - padding))
    const yMax = Math.min(100, Math.ceil(Math.max(maxValue, 50) + padding))

    const bullData = values.map((v) => (v >= 50 ? v : 50))
    const bearData = values.map((v) => (v < 50 ? v : 50))

    const lineSegments: { x1: number; y1: number; x2: number; y2: number }[] = []
    for (let i = 1; i < values.length; i++) {
      lineSegments.push({ x1: i - 1, y1: values[i - 1], x2: i, y2: values[i] })
    }

    const fg = "#94a3b8"
    const fgStrong = "#e2e8f0"
    const axisLine = "rgba(148, 163, 184, 0.28)"
    const splitLine = "rgba(148, 163, 184, 0.10)"

    return {
      backgroundColor: "transparent",

      grid: {
        left: 42,
        right: overlay ? 56 : 18,
        top: 18,
        bottom: 48,
        containLabel: false,
      },

      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
          lineStyle: { color: "rgba(148, 163, 184, 0.45)", width: 1 },
        },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "rgba(148, 163, 184, 0.25)",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: "#e5e7eb", fontSize: 12 },
        formatter: (params: unknown) => {
          const arr = params as Array<{
            axisValueLabel: string; value: number; dataIndex: number; seriesName: string
          }>
          if (!arr || !arr.length) return ""

          const realPoint = arr.find((p) => p.seriesName === "市场情绪指数") ?? arr[0]
          const idx = realPoint.dataIndex
          const score = Number(values[idx] ?? realPoint.value)
          const diff = score - 50

          const moodLabel =
            score >= 70 ? "极热" : score >= 60 ? "偏热"
            : score >= 50 ? "偏多" : score >= 40 ? "偏弱"
            : score >= 30 ? "低迷" : "冰点"

          const moodColor =
            score >= 70 ? "#ef4444" : score >= 60 ? "#f97316"
            : score >= 50 ? "#f59e0b" : score >= 40 ? "#38bdf8"
            : score >= 30 ? "#60a5fa" : "#94a3b8"

          const overlayPoint = overlay
            ? arr.find((p) => p.seriesName === overlay.name)
            : undefined

          return `
            <div style="font-weight:600;margin-bottom:6px;">${realPoint.axisValueLabel}</div>
            <div>情绪分: <b style="color:${moodColor};font-size:14px;">${score.toFixed(1)}</b></div>
            <div style="margin-top:3px;">状态: <span style="color:${moodColor};">${moodLabel}</span></div>
            <div style="margin-top:3px;color:#94a3b8;">距离中性线: ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}</div>
            ${overlayPoint ? `<div style="margin-top:6px;padding-top:5px;border-top:1px solid rgba(148,163,184,0.25);color:${overlay?.color ?? "#475569"};">${overlay?.name ?? ""}: <b style="font-size:13px;">${Number(overlayPoint.value ?? 0).toFixed(2)}</b></div>` : ""}
          `
        },
      },

      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates,
        axisLine: { lineStyle: { color: axisLine } },
        axisTick: { show: false },
        axisLabel: { color: fg, fontSize: 10, margin: 10 },
      },

      yAxis: [
        {
          type: "value",
          min: yMin,
          max: yMax,
          splitNumber: 4,
          axisLabel: { color: fg, fontSize: 10, formatter: "{value}" },
          splitLine: { lineStyle: { color: splitLine } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        ...(overlay && overlay.data.length > 0
          ? [{
              type: "value" as const,
              scale: true,
              position: "right" as const,
              axisLabel: {
                color: overlay.color ?? "#475569",
                fontSize: 10,
                formatter: "{value}",
              },
              splitLine: { show: false },
              axisLine: { show: false },
              axisTick: { show: false },
            }]
          : []),
      ],

      dataZoom: [
        { type: "inside", start: zoomStart, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
        {
          type: "slider", start: zoomStart, end: 100, height: 18, bottom: 6,
          borderColor: "transparent",
          backgroundColor: "rgba(148,163,184,0.08)",
          fillerColor: "rgba(148,163,184,0.18)",
          handleStyle: { color: "#64748b" },
          textStyle: { color: fg, fontSize: 10 },
        },
      ],

      series: [
        {
          name: "多头区域", type: "line", data: bullData, symbol: "none", smooth: 0.3,
          lineStyle: { width: 0, opacity: 0 },
          areaStyle: {
            origin: 50, opacity: 0.34,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(239, 68, 68, 0.42)" },
              { offset: 0.55, color: "rgba(249, 115, 22, 0.20)" },
              { offset: 1, color: "rgba(249, 115, 22, 0.02)" },
            ]),
          },
          emphasis: { disabled: true }, tooltip: { show: false },
          markLine: {
            symbol: "none", silent: true,
            label: {
              color: fgStrong, fontSize: 11, fontWeight: 600,
              formatter: "中性线 50", position: "insideEndTop",
              backgroundColor: "rgba(226,232,240,0.10)", padding: [2, 5], borderRadius: 3,
            },
            lineStyle: {
              type: "solid", color: "rgba(226, 232, 240, 0.70)", width: 1.6,
            },
            data: [{ yAxis: 50, name: "中性线" }],
          },
          z: 1,
        },
        {
          name: "空头区域", type: "line", data: bearData, symbol: "none", smooth: 0.3,
          lineStyle: { width: 0, opacity: 0 },
          areaStyle: {
            origin: 50, opacity: 0.32,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(14, 165, 233, 0.02)" },
              { offset: 0.45, color: "rgba(14, 165, 233, 0.18)" },
              { offset: 1, color: "rgba(37, 99, 235, 0.38)" },
            ]),
          },
          emphasis: { disabled: true }, tooltip: { show: false }, z: 1,
        },
        {
          name: "市场情绪指数", type: "line", data: values, symbol: "none",
          lineStyle: { width: 0, opacity: 0 }, z: 2,
        },
        ...(lineSegments.length > 0
          ? [{
              name: "市场情绪指数", type: "custom" as const,
              coordinateSystem: "cartesian2d" as const, clip: true,
              renderItem: (_params: unknown, api: { value: (dim: number) => unknown; coord: (data: [number, number]) => [number, number] }) => {
                const x1 = Number(api.value(0))
                const y1 = Number(api.value(1))
                const x2 = Number(api.value(2))
                const y2 = Number(api.value(3))
                const toPixel = (x: number, y: number): [number, number] => {
                  const fx = Math.floor(x)
                  const cx = Math.ceil(x)
                  if (fx === cx) return api.coord([fx, y])
                  const frac = x - fx
                  const [px0, py0] = api.coord([fx, y])
                  const [px1, py1] = api.coord([cx, y])
                  return [px0 + (px1 - px0) * frac, py0 + (py1 - py0) * frac]
                }
                const start = toPixel(x1, y1)
                const end = toPixel(x2, y2)
                const c1 = scoreToColor(y1)
                const c2 = scoreToColor(y2)
                const midScore = (y1 + y2) / 2
                return {
                  type: "group",
                  children: [{
                    type: "polyline",
                    shape: { points: [start, end] },
                    style: {
                      fill: "none",
                      stroke: { type: "linear" as const, x: start[0], y: 0, x2: end[0], y2: 0, global: true, colorStops: [{ offset: 0, color: c1 }, { offset: 1, color: c2 }] },
                      lineWidth: 2.8, lineCap: "butt" as const, lineJoin: "round" as const,
                      shadowBlur: 8,
                      shadowColor: (() => { const [r, g, b] = scoreToRgb(midScore); return `rgba(${r},${g},${b},0.35)` })(),
                    },
                    silent: true,
                  }],
                }
              },
              data: lineSegments.map((s) => ({ value: [s.x1, s.y1, s.x2, s.y2] })),
              tooltip: { show: false }, z: 3,
            }]
          : []),
        ...(overlay && overlay.data.length > 0
          ? [{
              name: overlay.name, type: "line" as const,
              data: overlay.data.map((d) => (d === null ? null : d.value)),
              yAxisIndex: 1, symbol: "none", smooth: 0.2, connectNulls: false,
              lineStyle: { color: overlay.color ?? "#475569", width: 2, type: "dashed" as const, opacity: 1 },
              z: 4,
            }]
          : []),
      ],
    }
  }, [data, overlay])

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, { renderer: "canvas" })
    }
    chartRef.current.setOption(option, { notMerge: true })
    const onWinResize = () => chartRef.current?.resize()
    window.addEventListener("resize", onWinResize)
    const ro = new ResizeObserver(() => chartRef.current?.resize())
    ro.observe(ref.current)
    return () => { window.removeEventListener("resize", onWinResize); ro.disconnect() }
  }, [option])

  useEffect(() => {
    return () => { chartRef.current?.dispose(); chartRef.current = null }
  }, [])

  if (!data || data.length < 2) {
    return (
      <div style={{ height }} className="flex items-center justify-center text-xs text-slate-300">
        暂无趋势数据
      </div>
    )
  }

  return <div ref={ref} style={{ width: "100%", height }} />
}

// ─── POC 页面 ────────────────────────────────────────────────────────────────
export default function SentimentOverlayPoc() {
  const [history, setHistory] = useState<MarketSentimentIndexHistoryItem[] | null>(null)
  const [shIndex, setShIndex] = useState<IndexDailyItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const end = new Date().toISOString().slice(0, 10)
    const start = new Date(Date.now() - 1095 * 86400000).toISOString().slice(0, 10)
    void (async () => {
      try {
        const [hist, sh] = await Promise.all([
          fetchMarketSentimentIndexHistory(start, end),
          fetchIndexDailyHistory({ code: "000001", start, end }),
        ])
        if (cancelled) return
        setHistory(hist.items ?? [])
        setShIndex(sh.items ?? [])
      } catch (e) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  // 按 tradeDate 交集对齐 (msi ∩ sh, 避免断线)
  const { sentimentPoints, shOverlay } = useMemo(() => {
    if (!history || !shIndex || shIndex.length === 0) {
      return { sentimentPoints: [] as SentimentLinePoint[], shOverlay: undefined as undefined | { name: string; color: string; data: OverlayPoint[] } }
    }
    const shDates = new Set(shIndex.map((it) => it.tradeDate))
    const aligned = history.filter((it) => shDates.has(it.tradeDate))
    const sorted = aligned.slice().sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))

    const points: SentimentLinePoint[] = sorted.map((it) => ({
      date: it.tradeDate.slice(5),
      value: it.compositeScore ?? 50,
      level: it.level,
    }))

    const shMap = new Map(shIndex.map((it) => [it.tradeDate, it.close]))
    const data: (number | null)[] = sorted.map((it) => {
      const v = shMap.get(it.tradeDate)
      return v == null ? null : v
    })
    const hitCount = data.filter((v) => v != null).length
    const overlay = hitCount >= 2
      ? {
          name: "上证指数",
          color: "#475569",
          data: data.map((v, i) =>
            v == null ? null : { date: sorted[i].tradeDate.slice(5), value: v },
          ),
        }
      : undefined

    return { sentimentPoints: points, shOverlay: overlay }
  }, [history, shIndex])

  return (
    <div className="space-y-4">
      {/* 说明 */}
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">POC 目标</p>
        <p className="mt-1">在情绪分折线图 (左轴 0-100) 上叠加上证指数日线 (右轴 auto-scale, 虚线)，验证双 Y 轴 + 上证叠加效果。</p>
        <ul className="mt-2 ml-4 list-disc space-y-0.5 text-xs">
          <li>左轴: 市场情绪指数 (0-100), 温度计色阶渐变主线</li>
          <li>右轴: 上证指数收盘价 (auto-scale), 灰色虚线</li>
          <li>tooltip 同步显示情绪分 + 上证收盘价</li>
          <li>数据源: <code className="rounded bg-muted px-1">fetchMarketSentimentIndexHistory</code> + <code className="rounded bg-muted px-1">fetchIndexDailyHistory(000001)</code></li>
        </ul>
      </div>

      {/* 叠加效果图 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-medium">
            情绪分 + 上证指数叠加
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : error ? (
            <div className="flex h-[320px] items-center justify-center text-sm text-red-500">
              {error}
            </div>
          ) : (
            <SentimentLine data={sentimentPoints} height={320} overlay={shOverlay} />
          )}
        </CardContent>
      </Card>

      {/* 数据概览 */}
      {!loading && !error && (
        <div className="grid grid-cols-3 gap-3">
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">情绪分数据点</p>
              <p className="mt-1 text-2xl font-semibold">{sentimentPoints.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">上证指数数据点</p>
              <p className="mt-1 text-2xl font-semibold">{shIndex?.length ?? 0}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">叠加对齐点数</p>
              <p className="mt-1 text-2xl font-semibold">
                {shOverlay?.data.filter((d) => d !== null).length ?? 0}
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
