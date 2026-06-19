/**
 * POC: 情绪折线图叠加上证指数 + 主力净流 + 成交额
 *
 * 布局:
 *   上 1: 主力净流
 *   中 3: 情绪分 + 上证指数
 *   下 1: 成交额
 *
 * 关键:
 *   - 三个 grid 轻微重叠，制造“上下区域溢入主图”的效果
 *   - dataZoom 联动 3 个 xAxis
 *   - axisPointer 使用 cross + link，贴近 ECharts sample 的交互风格
 */
import { useEffect, useMemo, useRef, useState } from "react"
import * as echarts from "echarts/core"
import { CustomChart, LineChart } from "echarts/charts"
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  LegendComponent,
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
  LegendComponent,
  CanvasRenderer,
])

interface SentimentLinePoint {
  date: string
  value: number
  level?: string
}

interface OverlayPoint {
  date: string
  value: number | null
}

interface OverlaySeries {
  name: string
  color?: string
  data: OverlayPoint[]
}

function toFiniteNumber(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function formatYi(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return "-"
  return `${(v / 1e8).toFixed(2)}亿`
}

function pickFirstNumber(obj: unknown, keys: string[]) {
  const record = obj as Record<string, unknown>
  for (const key of keys) {
    const n = toFiniteNumber(record[key])
    if (n != null) return n
  }
  return null
}

/**
 * 成交额字段适配:
 * 你可以按真实 IndexDailyItem 字段改这里。
 *
 * 常见字段可能是:
 *   amount / turnoverAmount / turnover / volumeAmount
 */
function pickAmount(item: IndexDailyItem) {
  return pickFirstNumber(item, [
    "amount",
    "turnoverAmount",
    "turnover",
    "volumeAmount",
    "成交额",
  ])
}

/**
 * 主力净流字段适配:
 * 如果主力净流来自另一个接口，建议把那个接口返回 items 传进这里生成 map。
 *
 * 这里先兼容从 history 或 shIndex item 里取字段。
 */
function pickMainNetFlow(item: unknown) {
  return pickFirstNumber(item, [
    "mainNetFlow",
    "mainNetInflow",
    "mainForceNetFlow",
    "mainForceNetInflow",
    "netMainInflow",
    "netInflowMain",
    "主力净流",
    "主力净流入",
  ])
}

function SentimentLine({
                         data,
                         height = 560,
                         shOverlay,
                         mainNetFlowOverlay,
                         amountOverlay,
                       }: {
  data: SentimentLinePoint[]
  height?: number
  shOverlay?: OverlaySeries
  mainNetFlowOverlay?: OverlaySeries
  amountOverlay?: OverlaySeries
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((d) => d.date)
    const values = data.map((d) => d.value)

    const minValue = values.length ? Math.min(...values) : 0
    const maxValue = values.length ? Math.max(...values) : 100
    const valueRange = Math.max(1, maxValue - minValue)
    const padding = Math.max(3, valueRange * 0.1)

    const recentBars = 63
    const totalBars = values.length
    const zoomStart =
      totalBars > recentBars ? Math.max(0, 100 - (recentBars / totalBars) * 100) : 0

    const yMin = Math.max(0, Math.floor(Math.min(minValue, 50) - padding))
    const yMax = Math.min(100, Math.ceil(Math.max(maxValue, 50) + padding))

    const bullData = values.map((v) => (v >= 50 ? v : 50))
    const bearData = values.map((v) => (v < 50 ? v : 50))

    const lineSegments: { x1: number; y1: number; x2: number; y2: number }[] = []
    for (let i = 1; i < values.length; i++) {
      lineSegments.push({
        x1: i - 1,
        y1: values[i - 1],
        x2: i,
        y2: values[i],
      })
    }

    const fg = "#94a3b8"
    const fgStrong = "#e2e8f0"
    const axisLine = "rgba(148, 163, 184, 0.28)"
    const splitLine = "rgba(148, 163, 184, 0.10)"

    const shValues = shOverlay?.data.map((d) => d.value) ?? []
    const mainNetFlowValues = mainNetFlowOverlay?.data.map((d) => d.value) ?? []
    const amountValues = amountOverlay?.data.map((d) => d.value) ?? []

    return {
      backgroundColor: "transparent",

      legend: {
        top: 0,
        right: 8,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { color: fg, fontSize: 11 },
        data: ["主力净流", "市场情绪指数", "上证指数", "成交额"],
      },

      /**
       * 1:3:1 的视觉布局。
       *
       * 注意这里不是硬切成 20 / 60 / 20。
       * top 和 bottom grid 都稍微压进 middle，
       * 再配合 series.clip = false，形成“溢入中间主图”的感觉。
       */
      grid: [
        {
          // 上 1: 主力净流
          left: 42,
          right: 58,
          top: 30,
          height: "22%",
          containLabel: false,
        },
        {
          // 中 3: 情绪分 + 上证
          left: 42,
          right: 58,
          top: "20%",
          height: "52%",
          containLabel: false,
        },
        {
          // 下 1: 成交额
          left: 42,
          right: 58,
          top: "64%",
          height: "22%",
          containLabel: false,
        },
      ],

      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "cross",
          animation: false,
          label: {
            backgroundColor: "#505765",
          },
        },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "rgba(148, 163, 184, 0.25)",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: "#e5e7eb", fontSize: 12 },
        formatter: (params: unknown) => {
          const arr = params as Array<{
            axisValueLabel: string
            value: number | null
            dataIndex: number
            seriesName: string
          }>

          if (!arr || !arr.length) return ""

          const scorePoint =
            arr.find((p) => p.seriesName === "市场情绪指数") ?? arr[0]
          const shPoint = arr.find((p) => p.seriesName === "上证指数")
          const flowPoint = arr.find((p) => p.seriesName === "主力净流")
          const amountPoint = arr.find((p) => p.seriesName === "成交额")

          const idx = scorePoint.dataIndex
          const score = Number(values[idx] ?? scorePoint.value ?? 50)
          const diff = score - 50

          const moodLabel =
            score >= 70
              ? "极热"
              : score >= 60
                ? "偏热"
                : score >= 50
                  ? "偏多"
                  : score >= 40
                    ? "偏弱"
                    : score >= 30
                      ? "低迷"
                      : "冰点"

          const moodColor =
            score >= 70
              ? "#ef4444"
              : score >= 60
                ? "#f97316"
                : score >= 50
                  ? "#f59e0b"
                  : score >= 40
                    ? "#38bdf8"
                    : score >= 30
                      ? "#60a5fa"
                      : "#94a3b8"

          const flow = toFiniteNumber(flowPoint?.value)
          const amount = toFiniteNumber(amountPoint?.value)
          const sh = toFiniteNumber(shPoint?.value)

          return `
            <div style="font-weight:600;margin-bottom:6px;">${arr[0].axisValueLabel}</div>

            ${
            flow != null
              ? `<div style="color:${flow >= 0 ? "#ef4444" : "#38bdf8"};">
                    主力净流: <b>${formatYi(flow)}</b>
                  </div>`
              : ""
          }

            <div style="margin-top:6px;padding-top:5px;border-top:1px solid rgba(148,163,184,0.25);">
              情绪分: <b style="color:${moodColor};font-size:14px;">${score.toFixed(1)}</b>
            </div>
            <div style="margin-top:3px;">状态: <span style="color:${moodColor};">${moodLabel}</span></div>
            <div style="margin-top:3px;color:#94a3b8;">距离中性线: ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}</div>

            ${
            sh != null
              ? `<div style="margin-top:5px;color:#94a3b8;">上证指数: <b>${sh.toFixed(2)}</b></div>`
              : ""
          }

            ${
            amount != null
              ? `<div style="margin-top:6px;padding-top:5px;border-top:1px solid rgba(148,163,184,0.25);color:#60a5fa;">
                    成交额: <b>${formatYi(amount)}</b>
                  </div>`
              : ""
          }
          `
        },
      },

      axisPointer: {
        link: [{ xAxisIndex: [0, 1, 2] }],
      },

      xAxis: [
        {
          type: "category",
          gridIndex: 0,
          boundaryGap: false,
          data: dates,
          axisLine: { onZero: false, lineStyle: { color: axisLine } },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
        {
          type: "category",
          gridIndex: 1,
          boundaryGap: false,
          data: dates,
          axisLine: { onZero: false, lineStyle: { color: axisLine } },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
        {
          type: "category",
          gridIndex: 2,
          boundaryGap: false,
          data: dates,
          axisLine: { onZero: false, lineStyle: { color: axisLine } },
          axisTick: { show: false },
          axisLabel: { color: fg, fontSize: 10, margin: 8 },
        },
      ],

      yAxis: [
        {
          // 0: 主力净流
          type: "value",
          gridIndex: 0,
          scale: true,
          splitNumber: 2,
          axisLabel: {
            color: fg,
            fontSize: 10,
            formatter: (v: number) => formatYi(v),
          },
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          // 1: 情绪分
          type: "value",
          gridIndex: 1,
          min: yMin,
          max: yMax,
          splitNumber: 4,
          axisLabel: { color: fg, fontSize: 10, formatter: "{value}" },
          splitLine: { lineStyle: { color: splitLine } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          // 2: 上证指数
          type: "value",
          gridIndex: 1,
          scale: true,
          position: "right",
          axisLabel: {
            color: shOverlay?.color ?? "#475569",
            fontSize: 10,
            formatter: "{value}",
          },
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          // 3: 成交额
          type: "value",
          gridIndex: 2,
          scale: true,
          splitNumber: 2,
          axisLabel: {
            color: fg,
            fontSize: 10,
            formatter: (v: number) => formatYi(v),
          },
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],

      dataZoom: [
        {
          type: "inside",
          xAxisIndex: [0, 1, 2],
          realtime: true,
          start: zoomStart,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
        {
          type: "slider",
          xAxisIndex: [0, 1, 2],
          realtime: true,
          start: zoomStart,
          end: 100,
          height: 18,
          bottom: 6,
          borderColor: "transparent",
          backgroundColor: "rgba(148,163,184,0.08)",
          fillerColor: "rgba(148,163,184,0.18)",
          handleStyle: { color: "#64748b" },
          textStyle: { color: fg, fontSize: 10 },
        },
      ],

      series: [
        /**
         * 上 1: 主力净流
         * 用 line + area，更贴近你给的 sample。
         * clip:false 让它可以轻微溢出自己的 grid。
         */
        {
          name: "主力净流",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: mainNetFlowValues,
          symbol: "none",
          smooth: 0.25,
          connectNulls: false,
          clip: false,
          lineStyle: {
            width: 2,
            color: mainNetFlowOverlay?.color ?? "#22c55e",
            opacity: 0.95,
          },
          areaStyle: {
            opacity: 0.12,
            color: mainNetFlowOverlay?.color ?? "#22c55e",
          },
          markLine: {
            symbol: "none",
            silent: true,
            label: { show: false },
            lineStyle: {
              color: "rgba(148, 163, 184, 0.35)",
              width: 1,
              type: "dashed",
            },
            data: [{ yAxis: 0 }],
          },
          z: 1,
        },

        /**
         * 中 3: 情绪多头区域
         */
        {
          name: "多头区域",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: bullData,
          symbol: "none",
          smooth: 0.3,
          lineStyle: { width: 0, opacity: 0 },
          areaStyle: {
            origin: 50,
            opacity: 0.34,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(239, 68, 68, 0.42)" },
              { offset: 0.55, color: "rgba(249, 115, 22, 0.20)" },
              { offset: 1, color: "rgba(249, 115, 22, 0.02)" },
            ]),
          },
          emphasis: { disabled: true },
          tooltip: { show: false },
          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: fgStrong,
              fontSize: 11,
              fontWeight: 600,
              formatter: "中性线 50",
              position: "insideEndTop",
              backgroundColor: "rgba(226,232,240,0.10)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "solid",
              color: "rgba(226, 232, 240, 0.70)",
              width: 1.6,
            },
            data: [{ yAxis: 50, name: "中性线" }],
          },
          z: 2,
        },

        /**
         * 中 3: 情绪空头区域
         */
        {
          name: "空头区域",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: bearData,
          symbol: "none",
          smooth: 0.3,
          lineStyle: { width: 0, opacity: 0 },
          areaStyle: {
            origin: 50,
            opacity: 0.32,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(14, 165, 233, 0.02)" },
              { offset: 0.45, color: "rgba(14, 165, 233, 0.18)" },
              { offset: 1, color: "rgba(37, 99, 235, 0.38)" },
            ]),
          },
          emphasis: { disabled: true },
          tooltip: { show: false },
          z: 2,
        },

        /**
         * 中 3: 透明情绪线，只用于 tooltip 命中
         */
        {
          name: "市场情绪指数",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: values,
          symbol: "none",
          lineStyle: { width: 0, opacity: 0 },
          z: 3,
        },

        /**
         * 中 3: 情绪渐变主线
         */
        ...(lineSegments.length > 0
          ? [
            {
              name: "市场情绪指数",
              type: "custom" as const,
              xAxisIndex: 1,
              yAxisIndex: 1,
              coordinateSystem: "cartesian2d" as const,
              clip: true,
              renderItem: (
                _params: unknown,
                api: {
                  value: (dim: number) => unknown
                  coord: (data: [number, number]) => [number, number]
                },
              ) => {
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
                  children: [
                    {
                      type: "polyline",
                      shape: { points: [start, end] },
                      style: {
                        fill: "none",
                        stroke: {
                          type: "linear" as const,
                          x: start[0],
                          y: 0,
                          x2: end[0],
                          y2: 0,
                          global: true,
                          colorStops: [
                            { offset: 0, color: c1 },
                            { offset: 1, color: c2 },
                          ],
                        },
                        lineWidth: 2.8,
                        lineCap: "butt" as const,
                        lineJoin: "round" as const,
                        shadowBlur: 8,
                        shadowColor: (() => {
                          const [r, g, b] = scoreToRgb(midScore)
                          return `rgba(${r},${g},${b},0.35)`
                        })(),
                      },
                      silent: true,
                    },
                  ],
                }
              },
              data: lineSegments.map((s) => ({
                value: [s.x1, s.y1, s.x2, s.y2],
              })),
              tooltip: { show: false },
              z: 4,
            },
          ]
          : []),

        /**
         * 中 3: 上证指数
         */
        {
          name: "上证指数",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 2,
          data: shValues,
          symbol: "none",
          smooth: 0.2,
          connectNulls: false,
          lineStyle: {
            color: shOverlay?.color ?? "#475569",
            width: 2,
            type: "dashed",
            opacity: 1,
          },
          z: 5,
        },

        /**
         * 下 1: 成交额
         * 同样用 line + area，并允许向中间溢出一点。
         */
        {
          name: "成交额",
          type: "line",
          xAxisIndex: 2,
          yAxisIndex: 3,
          data: amountValues,
          symbol: "none",
          smooth: 0.25,
          connectNulls: false,
          clip: false,
          lineStyle: {
            width: 2,
            color: amountOverlay?.color ?? "#60a5fa",
            opacity: 0.95,
          },
          areaStyle: {
            opacity: 0.12,
            color: amountOverlay?.color ?? "#60a5fa",
          },
          z: 1,
        },
      ],
    }
  }, [data, shOverlay, mainNetFlowOverlay, amountOverlay])

  useEffect(() => {
    if (!ref.current) return

    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, {
        renderer: "canvas",
      })
    }

    chartRef.current.setOption(option, { notMerge: true })

    const onWinResize = () => chartRef.current?.resize()
    window.addEventListener("resize", onWinResize)

    const ro = new ResizeObserver(() => chartRef.current?.resize())
    ro.observe(ref.current)

    return () => {
      window.removeEventListener("resize", onWinResize)
      ro.disconnect()
    }
  }, [option])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  if (!data || data.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-xs text-slate-300"
      >
        暂无趋势数据
      </div>
    )
  }

  return <div ref={ref} style={{ width: "100%", height }} />
}

// ─── POC 页面 ────────────────────────────────────────────────────────────────
export default function SentimentOverlayPoc() {
  const [history, setHistory] = useState<MarketSentimentIndexHistoryItem[] | null>(
    null,
  )
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

    return () => {
      cancelled = true
    }
  }, [])

  /**
   * 重要改动:
   * 以前是 history ∩ shIndex 取交集。
   * 现在改成以 history 为主时间轴，其它指标缺失填 null。
   *
   * 原因:
   * 加了成交额、主力净流以后，如果继续取交集，很容易把可视区砍碎。
   */
  const {
    sentimentPoints,
    shOverlay,
    mainNetFlowOverlay,
    amountOverlay,
    shHitCount,
    flowHitCount,
    amountHitCount,
  } = useMemo(() => {
    if (!history || history.length === 0) {
      return {
        sentimentPoints: [] as SentimentLinePoint[],
        shOverlay: undefined as OverlaySeries | undefined,
        mainNetFlowOverlay: undefined as OverlaySeries | undefined,
        amountOverlay: undefined as OverlaySeries | undefined,
        shHitCount: 0,
        flowHitCount: 0,
        amountHitCount: 0,
      }
    }

    const sorted = history
      .slice()
      .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))

    const shMap = new Map(
      (shIndex ?? []).map((it) => [it.tradeDate, toFiniteNumber(it.close)]),
    )

    const amountMap = new Map(
      (shIndex ?? []).map((it) => [it.tradeDate, pickAmount(it)]),
    )

    /**
     * 主力净流:
     *
     * 如果你的主力净流来自独立接口，例如:
     *   fetchMarketMainNetFlowHistory(start, end)
     *
     * 那就新增一个 state:
     *   const [mainFlow, setMainFlow] = useState<MainFlowItem[] | null>(null)
     *
     * 然后这里改成:
     *   const flowMap = new Map(mainFlow.map((it) => [it.tradeDate, it.mainNetFlow]))
     *
     * 现在这版先尝试从 history / shIndex item 里取，方便你直接跑布局。
     */
    const flowMapFromHistory = new Map(
      sorted.map((it) => [it.tradeDate, pickMainNetFlow(it)]),
    )

    const flowMapFromIndex = new Map(
      (shIndex ?? []).map((it) => [it.tradeDate, pickMainNetFlow(it)]),
    )

    const sentimentPoints: SentimentLinePoint[] = sorted.map((it) => ({
      date: it.tradeDate.slice(5),
      value: it.compositeScore ?? 50,
      level: it.level,
    }))

    const shData: OverlayPoint[] = sorted.map((it) => ({
      date: it.tradeDate.slice(5),
      value: shMap.get(it.tradeDate) ?? null,
    }))

    const amountData: OverlayPoint[] = sorted.map((it) => ({
      date: it.tradeDate.slice(5),
      value: amountMap.get(it.tradeDate) ?? null,
    }))

    const flowData: OverlayPoint[] = sorted.map((it) => ({
      date: it.tradeDate.slice(5),
      value:
        flowMapFromHistory.get(it.tradeDate) ??
        flowMapFromIndex.get(it.tradeDate) ??
        null,
    }))

    const shHitCount = shData.filter((d) => d.value != null).length
    const amountHitCount = amountData.filter((d) => d.value != null).length
    const flowHitCount = flowData.filter((d) => d.value != null).length

    return {
      sentimentPoints,

      shOverlay:
        shHitCount >= 2
          ? {
            name: "上证指数",
            color: "#475569",
            data: shData,
          }
          : undefined,

      mainNetFlowOverlay:
        flowHitCount >= 2
          ? {
            name: "主力净流",
            color: "#22c55e",
            data: flowData,
          }
          : undefined,

      amountOverlay:
        amountHitCount >= 2
          ? {
            name: "成交额",
            color: "#60a5fa",
            data: amountData,
          }
          : undefined,

      shHitCount,
      flowHitCount,
      amountHitCount,
    }
  }, [history, shIndex])

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">POC 目标</p>
        <p className="mt-1">
          按 1:3:1 分为上中下三层：上层主力净流，中层情绪分 + 上证指数，下层成交额。
          上下两层轻微溢入中间主图，验证多 grid 联动效果。
        </p>
        <ul className="mt-2 ml-4 list-disc space-y-0.5 text-xs">
          <li>上层: 主力净流，line + area，允许溢出</li>
          <li>中层: 市场情绪指数 + 上证指数</li>
          <li>下层: 成交额，line + area，允许溢出</li>
          <li>交互: cross tooltip + axisPointer link + dataZoom 三轴联动</li>
        </ul>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-medium">
            主力净流 / 情绪分 + 上证指数 / 成交额
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <Skeleton className="h-[560px] w-full" />
          ) : error ? (
            <div className="flex h-[560px] items-center justify-center text-sm text-red-500">
              {error}
            </div>
          ) : (
            <SentimentLine
              data={sentimentPoints}
              height={560}
              shOverlay={shOverlay}
              mainNetFlowOverlay={mainNetFlowOverlay}
              amountOverlay={amountOverlay}
            />
          )}
        </CardContent>
      </Card>

      {!loading && !error && (
        <div className="grid grid-cols-4 gap-3">
          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">情绪分数据点</p>
              <p className="mt-1 text-2xl font-semibold">
                {sentimentPoints.length}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">上证指数对齐点</p>
              <p className="mt-1 text-2xl font-semibold">{shHitCount}</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">主力净流对齐点</p>
              <p className="mt-1 text-2xl font-semibold">{flowHitCount}</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground">成交额对齐点</p>
              <p className="mt-1 text-2xl font-semibold">{amountHitCount}</p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}