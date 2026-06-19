/**
 * Market Sentiment 顶卡专用 ECharts 三层叠加图.
 *
 * 源自 /poc/sentiment-overlay 迁移:
 *   上 1: 主力净流, Rainfall 风格, 反向轴, 0 在顶部
 *   中 3: 情绪分 (主线) + 上证指数 (右轴虚线)
 *   下 1: 成交额, Flow 风格, 蓝色面积图
 *
 * 轴布局:
 *   左外: 成交额
 *   左内: 情绪分
 *   右内: 上证指数
 *   右外: 主力净流
 *
 * 成交额数据源: duckdb.market_overview_daily.total_amount (亿元) 为主
 *              duckdb.index_daily_raw.amount (元) 兜底
 * 主力净流数据源: duckdb.market_overview_daily.main_net_inflow (亿元)
 *
 * 主力净流:
 *   流入: 红色
 *   流出: 绿色
 *   正负切换经过中性色, 减少割裂感
 *   线和面积都做渐变
 *   使用 custom series 画平滑曲线
 *   缩放时 clamp 贝塞尔控制点, 避免左右过冲
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
  ToolboxComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"
import type { EChartsOption } from "echarts"
import { scoreToColor, scoreToRgb } from "../lib/color"

echarts.use([
  CustomChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  LegendComponent,
  ToolboxComponent,
  CanvasRenderer,
])

export interface SentimentOverlayPoint {
  date: string
  value: number
  level?: string
}

export interface SentimentOverlayDatum {
  date: string
  value: number | null
}

export interface SentimentOverlaySeries {
  name: string
  color?: string
  data: SentimentOverlayDatum[]
}

export interface SentimentOverlayProps {
  data: SentimentOverlayPoint[]
  height?: number | string
  shOverlay?: SentimentOverlaySeries
  mainNetFlowOverlay?: SentimentOverlaySeries
  amountOverlay?: SentimentOverlaySeries
}

function toFiniteNumber(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function formatYi(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return "-"
  return `${(v / 1e8).toFixed(2)}亿`
}

function maxOf(arr: Array<number | null>, fallback = 1) {
  const nums = arr.filter((v): v is number => v != null && Number.isFinite(v))
  return nums.length ? Math.max(fallback, ...nums) : fallback
}

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v))
}

function mix(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t)
}

function rgba(rgb: [number, number, number], alpha: number) {
  return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`
}

export function SentimentOverlay({
  data,
  height = "100%",
  shOverlay,
  mainNetFlowOverlay,
  amountOverlay,
}: SentimentOverlayProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [zoomRange, setZoomRange] = useState<{ start: number; end: number } | null>(null)
  const [chartWidth, setChartWidth] = useState(1200)

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
      totalBars > recentBars
        ? Math.max(0, 100 - (recentBars / totalBars) * 100)
        : 0

    const effectiveZoomStart = zoomRange?.start ?? zoomStart
    const effectiveZoomEnd = zoomRange?.end ?? 100

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

    const shValues = shOverlay?.data.map((d) => d.value) ?? []
    const mainNetFlowRawValues = mainNetFlowOverlay?.data.map((d) => d.value) ?? []
    const amountRawValues = amountOverlay?.data.map((d) => d.value) ?? []

    const mainNetFlowYiValues = mainNetFlowRawValues.map((v) =>
      v == null ? null : v / 1e8,
    )

    const mainNetFlowRainValues = mainNetFlowYiValues.map((v) =>
      v == null ? null : Math.abs(v),
    )

    /**
     * 主力净流使用分段视觉刻度：
     * - 0 ~ 500 亿：压缩, 避免小额波动占用太多顶部空间
     * - 500 亿以上：放大, 让大额净流变化更明显
     *
     * 注意：这里只改 Rainfall 的 y 坐标, 不改真实主力净流值。
     * tooltip 仍然展示原始主力净流, y 轴标签会反算回真实亿数。
     */
    const FLOW_BREAKPOINT_YI = 500
    const FLOW_LOW_SCALE = 0.4
    const FLOW_HIGH_SCALE = 3

    const flowToVisual = (flowYi: number) => {
      const absFlowYi = Math.max(0, Math.abs(flowYi))

      if (absFlowYi <= FLOW_BREAKPOINT_YI) {
        return absFlowYi * FLOW_LOW_SCALE
      }

      return (
        FLOW_BREAKPOINT_YI * FLOW_LOW_SCALE +
        (absFlowYi - FLOW_BREAKPOINT_YI) * FLOW_HIGH_SCALE
      )
    }

    const visualToFlow = (visualValue: number) => {
      const breakpointVisual = FLOW_BREAKPOINT_YI * FLOW_LOW_SCALE

      if (visualValue <= breakpointVisual) {
        return visualValue / FLOW_LOW_SCALE
      }

      return (
        FLOW_BREAKPOINT_YI +
        (visualValue - breakpointVisual) / FLOW_HIGH_SCALE
      )
    }

    const formatFlowAxis = (visualValue: number) => {
      const flowYi = visualToFlow(visualValue)
      if (!Number.isFinite(flowYi)) return "-"

      return flowYi >= 1000
        ? `${Math.round(flowYi / 100) / 10}千`
        : `${Math.round(flowYi)}`
    }

    const mainNetFlowVisualRainValues = mainNetFlowRainValues.map((v) =>
      v == null ? null : flowToVisual(v),
    )

    const maxFlowVisualRain = maxOf(mainNetFlowVisualRainValues, 1)

    const maxInflowYi = maxOf(
      mainNetFlowYiValues.map((v) =>
        v != null && v > 0 ? Math.abs(v) : null,
      ),
      1,
    )

    const maxOutflowYi = maxOf(
      mainNetFlowYiValues.map((v) =>
        v != null && v < 0 ? Math.abs(v) : null,
      ),
      1,
    )

    const fillNullableNumbers = (arr: Array<number | null>) => {
      const result = arr.slice()
      const validIndexes: number[] = []

      for (let i = 0; i < result.length; i++) {
        const v = result[i]
        if (v != null && Number.isFinite(v)) validIndexes.push(i)
      }

      if (!validIndexes.length) return [] as number[]

      const first = validIndexes[0]
      const last = validIndexes[validIndexes.length - 1]

      for (let i = 0; i < first; i++) result[i] = result[first]
      for (let i = last + 1; i < result.length; i++) result[i] = result[last]

      for (let k = 0; k < validIndexes.length - 1; k++) {
        const left = validIndexes[k]
        const right = validIndexes[k + 1]
        const leftValue = result[left]
        const rightValue = result[right]

        if (leftValue == null || rightValue == null || right - left <= 1) continue

        for (let i = left + 1; i < right; i++) {
          const t = (i - left) / (right - left)
          result[i] = leftValue + (rightValue - leftValue) * t
        }
      }

      return result.map((v) => (v == null || !Number.isFinite(v) ? 0 : v))
    }

    const catmullRom = (
      p0: number,
      p1: number,
      p2: number,
      p3: number,
      t: number,
    ) => {
      const t2 = t * t
      const t3 = t2 * t
      return (
        0.5 *
        (2 * p1 +
          (-p0 + p2) * t +
          (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
          (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
      )
    }

    const clampBetween = (v: number, a: number, b: number) => {
      const lo = Math.min(a, b)
      const hi = Math.max(a, b)
      return Math.max(lo, Math.min(hi, v))
    }

    const clampInt = (v: number, min: number, max: number) =>
      Math.max(min, Math.min(max, Math.round(v)))

    /**
     * 主力净流动态虚拟点策略:
     * - raw 是 signed 主力净流的真实插值值, 专门用于颜色。
     * - y 是 Rainfall 可视高度的插值值, 专门用于面积形状。
     * - 当前 dataZoom 放得越大, 每根 bar 的像素越宽, 虚拟点越密。
     */
    const filledMainNetFlowYiValues = fillNullableNumbers(mainNetFlowYiValues)

    type FlowVirtualSample = {
      x: number
      y: number
      raw: number
    }

    const buildDynamicVirtualFlowSamples = (
      filledValues: number[],
      zoomStartPercent: number,
      zoomEndPercent: number,
      widthPx: number,
    ): FlowVirtualSample[] => {
      const total = filledValues.length
      if (!total) return []

      if (total === 1) {
        const raw = filledValues[0]
        return [{ x: 0, y: flowToVisual(raw), raw }]
      }

      const startPercent = clamp01(Math.min(zoomStartPercent, zoomEndPercent) / 100)
      const endPercent = clamp01(Math.max(zoomStartPercent, zoomEndPercent) / 100)

      const visibleStartFloat = startPercent * (total - 1)
      const visibleEndFloat = endPercent * (total - 1)

      const visibleStart = Math.max(0, Math.floor(visibleStartFloat))
      const visibleEnd = Math.min(total - 1, Math.ceil(visibleEndFloat))
      const visibleBars = Math.max(1, visibleEndFloat - visibleStartFloat)

      // 与 option.grid[0] 的 left/right 对齐, 用于估算当前一根 bar 的像素宽度。
      const gridWidth = Math.max(160, widthPx - 86 - 96)
      const pxPerBar = gridWidth / visibleBars

      // 目标是大约每 0.75px 一个虚拟点。
      // zoom 越近, pxPerBar 越大, 补点越多; 全景时自动降密度。
      const baseStepsPerBar = clampInt(pxPerBar / 0.75, 16, 720)

      // 只生成可视区附近, 不对全量历史做过度采样, 避免拖动缩放时卡成毛线团。
      const buildStart = Math.max(0, visibleStart - 2)
      const buildEnd = Math.min(total - 1, visibleEnd + 2)

      const samples: FlowVirtualSample[] = []

      for (let i = buildStart; i < buildEnd; i++) {
        const p0 = filledValues[i - 1] ?? filledValues[i]
        const p1 = filledValues[i]
        const p2 = filledValues[i + 1]
        const p3 = filledValues[i + 2] ?? p2

        const h0 = flowToVisual(p0)
        const h1 = flowToVisual(p1)
        const h2 = flowToVisual(p2)
        const h3 = flowToVisual(p3)

        const crossesZero = p1 !== 0 && p2 !== 0 && p1 * p2 < 0
        const steps = clampInt(
          crossesZero ? baseStepsPerBar * 2.4 : baseStepsPerBar,
          16,
          1200,
        )

        for (let step = 0; step < steps; step++) {
          const t = step / steps
          const x = i + t

          // 关键：每一个虚拟点都有 signed raw 的真实过渡值, 颜色就有连续采样。
          const smoothRaw = catmullRom(p0, p1, p2, p3, t)
          const raw = clampBetween(smoothRaw, p1, p2)

          // Rainfall 的面积高度单独对分段视觉值做插值：0~100 亿压缩, 100 亿以上放大。
          const smoothHeight = catmullRom(h0, h1, h2, h3, t)
          const y = Math.max(0, clampBetween(smoothHeight, h1, h2))

          samples.push({ x, y, raw })
        }
      }

      const lastRaw = filledValues[buildEnd]
      samples.push({ x: buildEnd, y: flowToVisual(lastRaw), raw: lastRaw })

      return samples
    }

    const mainNetFlowVirtualSamples = buildDynamicVirtualFlowSamples(
      filledMainNetFlowYiValues,
      effectiveZoomStart,
      effectiveZoomEnd,
      chartWidth,
    )

    /**
     * 更柔和的颜色策略:
     * - 正值: neutral -> light red -> deep red
     * - 负值: neutral -> light green -> deep green
     * - 接近 0 时尽量接近中性色, 避免红绿硬切
     */
    const neutral: [number, number, number] = [226, 232, 240]

    const inflowSoftRed: [number, number, number] = [254, 202, 202]
    const inflowDeepRed: [number, number, number] = [220, 38, 38]

    const outflowSoftGreen: [number, number, number] = [187, 247, 208]
    const outflowDeepGreen: [number, number, number] = [22, 101, 52]

    const mixRgb = (
      from: [number, number, number],
      to: [number, number, number],
      t: number,
    ): [number, number, number] => [
      mix(from[0], to[0], t),
      mix(from[1], to[1], t),
      mix(from[2], to[2], t),
    ]

    const toneIntensity = (value: number, maxValue: number) => {
      const raw = clamp01(Math.abs(value) / Math.max(1, maxValue))

      if (raw < 0.000001) return 0

      /**
       * 这一版继续保持"均匀", 但整体再推重:
       * - 小值也明显染色, 不再贴近白底。
       * - 中大值更多靠近 soft/deep, 但 deep 仍然受控, 避免重新两极分化。
       * - 只改映射比例, 不改 neutral / soft / deep 的原始 RGB。
       */
      return clamp01(0.50 + 0.42 * Math.pow(raw, 0.62))
    }

    const flowRgb = (rawYi: number) => {
      if (Math.abs(rawYi) < 0.000001) return neutral

      if (rawYi > 0) {
        const t = toneIntensity(rawYi, maxInflowYi)
        const softRatio = 0.72 + 0.25 * t
        const deepRatio = clamp01((t - 0.60) / 0.40) * 0.32
        const soft = mixRgb(neutral, inflowSoftRed, softRatio)
        return mixRgb(soft, inflowDeepRed, deepRatio)
      }

      const t = toneIntensity(rawYi, maxOutflowYi)
      const softRatio = 0.72 + 0.25 * t
      const deepRatio = clamp01((t - 0.60) / 0.40) * 0.32
      const soft = mixRgb(neutral, outflowSoftGreen, softRatio)
      return mixRgb(soft, outflowDeepGreen, deepRatio)
    }

    const flowLineColor = (rawYi: number) => {
      const t =
        rawYi >= 0
          ? toneIntensity(rawYi, maxInflowYi)
          : toneIntensity(rawYi, maxOutflowYi)

      // 线条基本不透明, 让主力净流轮廓更明确。
      return rgba(flowRgb(rawYi), 0.96 + 0.04 * t)
    }

    const flowAreaColor = (rawYi: number) => {
      const t =
        rawYi >= 0
          ? toneIntensity(rawYi, maxInflowYi)
          : toneIntensity(rawYi, maxOutflowYi)

      // 面积明显加重, 同时保持窄区间, 避免又出现深浅割裂。
      return rgba(flowRgb(rawYi), 0.42 + 0.10 * t)
    }

    const dedupeStops = (
      stops: Array<{ offset: number; color: string }>,
    ) =>
      stops
        .map((s) => ({ offset: clamp01(s.offset), color: s.color }))
        .sort((a, b) => a.offset - b.offset)
        .reduce<Array<{ offset: number; color: string }>>((acc, stop) => {
          const last = acc[acc.length - 1]
          if (last && Math.abs(last.offset - stop.offset) < 0.0008) {
            last.color = stop.color
          } else {
            acc.push(stop)
          }
          return acc
        }, [])

    const buildFlowStops = (
      samples: Array<{ x: number; y: number; raw: number }>,
      colorFn: (raw: number) => string,
    ) => {
      if (!samples.length) {
        return [
          { offset: 0, color: colorFn(0) },
          { offset: 1, color: colorFn(0) },
        ]
      }

      const firstX = samples[0].x
      const lastX = samples[samples.length - 1].x
      const span = Math.max(0.000001, lastX - firstX)
      const stops: Array<{ offset: number; color: string }> = []

      for (const sample of samples) {
        stops.push({
          offset: (sample.x - firstX) / span,
          color: colorFn(sample.raw),
        })
      }

      return dedupeStops(stops)
    }

    const amountFlowValues = amountRawValues.map((v) =>
      v == null ? null : v / 1e8,
    )

    /**
     * 成交额使用分段视觉刻度：
     * - 0 ~ 25000 亿：压缩, 避免低区间吃掉太多纵向空间
     * - 25000 亿以上：放大, 让高成交额区间的细微变化更明显
     *
     * 注意：这里只改绘图坐标, 不改真实成交额。
     * tooltip 仍然展示原始成交额, y 轴标签会反算回真实成交额。
     */
    const AMOUNT_BREAKPOINT_YI = 25000
    const AMOUNT_LOW_SCALE = 0.24
    const AMOUNT_HIGH_SCALE = 1.85

    const amountToVisual = (amountYi: number) => {
      if (amountYi <= AMOUNT_BREAKPOINT_YI) {
        return amountYi * AMOUNT_LOW_SCALE
      }

      return (
        AMOUNT_BREAKPOINT_YI * AMOUNT_LOW_SCALE +
        (amountYi - AMOUNT_BREAKPOINT_YI) * AMOUNT_HIGH_SCALE
      )
    }

    const visualToAmount = (visualValue: number) => {
      const breakpointVisual = AMOUNT_BREAKPOINT_YI * AMOUNT_LOW_SCALE

      if (visualValue <= breakpointVisual) {
        return visualValue / AMOUNT_LOW_SCALE
      }

      return (
        AMOUNT_BREAKPOINT_YI +
        (visualValue - breakpointVisual) / AMOUNT_HIGH_SCALE
      )
    }

    const formatAmountAxis = (visualValue: number) => {
      const amountYi = visualToAmount(visualValue)
      if (!Number.isFinite(amountYi)) return "-"

      return amountYi >= 10000
        ? `${Math.round(amountYi / 1000) / 10}万`
        : `${Math.round(amountYi)}`
    }

    const amountVisualValues = amountFlowValues.map((v) =>
      v == null ? null : amountToVisual(v),
    )

    const maxAmountFlow = maxOf(amountFlowValues, 1)
    const maxAmountVisualFlow = Math.max(
      amountToVisual(AMOUNT_BREAKPOINT_YI),
      amountToVisual(maxAmountFlow),
    )

    const fg = "#555"
    const fgLight = "#6b7280"
    const axisLine = "#ccd3dd"
    const splitLine = "#d9dee8"

    const flowBlue = "#5470c6"
    const flowBlueArea = "rgba(84, 112, 198, 0.62)"

    /**
     * 上下两层向中间主图叠加的比例。
     * 0.30 表示：
     * - 上方主力净流向下进入中间主图 30% 的中图高度
     * - 下方成交额向上进入中间主图 30% 的中图高度
     *
     * 这里只改变可渲染区域, 不改变真实数据和 tooltip 口径。
     */
    const MIDDLE_OVERLAY_RATIO = 0.3
    const MIDDLE_GRID_TOP = 22
    const MIDDLE_GRID_HEIGHT = 54
    const EXTRA_OVERLAY_HEIGHT = MIDDLE_GRID_HEIGHT * MIDDLE_OVERLAY_RATIO

    const FLOW_GRID_TOP = 8
    const FLOW_GRID_BASE_HEIGHT = 24
    const FLOW_GRID_HEIGHT = FLOW_GRID_BASE_HEIGHT + EXTRA_OVERLAY_HEIGHT

    const AMOUNT_GRID_BASE_TOP = 68
    const AMOUNT_GRID_BOTTOM = 88
    const AMOUNT_GRID_TOP = AMOUNT_GRID_BASE_TOP - EXTRA_OVERLAY_HEIGHT
    const AMOUNT_GRID_HEIGHT = AMOUNT_GRID_BOTTOM - AMOUNT_GRID_TOP

    return {
      backgroundColor: "#fff",

      legend: {
        bottom: 34,
        left: 8,
        itemWidth: 18,
        itemHeight: 10,
        textStyle: { color: fg, fontSize: 12 },
        data: ["成交额", "主力净流", "市场情绪指数", "上证指数"],
      },

      toolbox: {
        right: 8,
        top: 0,
        feature: {
          dataZoom: {
            yAxisIndex: "none",
          },
          restore: {},
          saveAsImage: {},
        },
        iconStyle: {
          borderColor: "#64748b",
        },
      },

      grid: [
        {
          left: 86,
          right: 96,
          top: `${FLOW_GRID_TOP}%`,
          height: `${FLOW_GRID_HEIGHT}%`,
          containLabel: false,
        },
        {
          left: 86,
          right: 96,
          top: `${MIDDLE_GRID_TOP}%`,
          height: `${MIDDLE_GRID_HEIGHT}%`,
          containLabel: false,
        },
        {
          left: 86,
          right: 96,
          top: `${AMOUNT_GRID_TOP}%`,
          height: `${AMOUNT_GRID_HEIGHT}%`,
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
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d9dee8",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: "#333", fontSize: 12 },
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

          const idx = scorePoint.dataIndex
          const score = Number(values[idx] ?? scorePoint.value ?? 50)
          const diff = score - 50

          const rawFlow = mainNetFlowRawValues[idx]
          const rawAmount = amountRawValues[idx]
          const sh = toFiniteNumber(shPoint?.value)

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

          return `
            <div style="font-weight:600;margin-bottom:6px;">${arr[0].axisValueLabel}</div>

            ${
            rawFlow != null
              ? `<div style="color:${flowLineColor(rawFlow / 1e8)};">
                    主力净流: <b>${formatYi(rawFlow)}</b>
                  </div>`
              : ""
          }

            <div style="margin-top:6px;padding-top:5px;border-top:1px solid #e5e7eb;">
              情绪分: <b style="color:${moodColor};font-size:14px;">${score.toFixed(1)}</b>
            </div>
            <div style="margin-top:3px;">状态: <span style="color:${moodColor};">${moodLabel}</span></div>
            <div style="margin-top:3px;color:#6b7280;">距离中性线: ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}</div>

            ${
            sh != null
              ? `<div style="margin-top:5px;color:#475569;">上证指数: <b>${sh.toFixed(2)}</b></div>`
              : ""
          }

            ${
            rawAmount != null
              ? `<div style="margin-top:6px;padding-top:5px;border-top:1px solid #e5e7eb;color:${flowBlue};">
                    成交额: <b>${formatYi(rawAmount)}</b>
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
          // 上方 grid 现在会向中间主图叠加, 隐藏它自己的 x 轴线, 避免横线切进中图。
          axisLine: { show: false, onZero: false, lineStyle: { color: axisLine } },
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
          axisLabel: { color: fg, fontSize: 11, margin: 8 },
        },
      ],

      yAxis: [
        {
          type: "value",
          name: "主力净流(亿)",
          nameTextStyle: { color: "#047857", fontSize: 12 },
          gridIndex: 0,
          min: 0,
          max: Math.ceil(maxFlowVisualRain * 1.15),
          inverse: true,
          position: "right",
          offset: 42,
          splitNumber: 4,
          axisLabel: {
            color: "#047857",
            fontSize: 11,
            formatter: (value: number) => formatFlowAxis(Number(value)),
            margin: 6,
          },
          axisPointer: {
            label: {
              formatter: (params: { value: number }) =>
                `${formatFlowAxis(Number(params.value))}亿`,
            },
          },
          splitLine: { lineStyle: { color: "rgba(217,222,232,0.38)" } },
          axisLine: { show: true, lineStyle: { color: "#86efac" } },
          axisTick: { show: false },
        },
        {
          type: "value",
          name: "情绪分",
          nameTextStyle: { color: fg, fontSize: 12 },
          gridIndex: 1,
          min: yMin,
          max: yMax,
          splitNumber: 4,
          position: "left",
          offset: 0,
          axisLabel: { color: fg, fontSize: 11, formatter: "{value}" },
          splitLine: { lineStyle: { color: splitLine } },
          axisLine: { show: true, lineStyle: { color: axisLine } },
          axisTick: { show: false },
        },
        {
          type: "value",
          name: "上证",
          nameTextStyle: { color: "#475569", fontSize: 12 },
          gridIndex: 1,
          scale: true,
          position: "right",
          offset: 0,
          splitNumber: 3,
          axisLabel: {
            color: "#475569",
            fontSize: 11,
            formatter: "{value}",
          },
          splitLine: { show: false },
          axisLine: { show: true, lineStyle: { color: "#94a3b8" } },
          axisTick: { show: false },
        },
        {
          type: "value",
          name: "成交额(亿)",
          nameTextStyle: { color: "#5470c6", fontSize: 12 },
          gridIndex: 2,
          min: 0,
          max: Math.ceil(maxAmountVisualFlow * 1.08),
          splitNumber: 4,
          position: "left",
          offset: 42,
          axisLabel: {
            color: "#5470c6",
            fontSize: 11,
            formatter: (value: number) => formatAmountAxis(Number(value)),
            margin: 6,
          },
          axisPointer: {
            label: {
              formatter: (params: { value: number }) =>
                `${formatAmountAxis(Number(params.value))}亿`,
            },
          },
          splitLine: { lineStyle: { color: "rgba(217,222,232,0.38)" } },
          axisLine: { show: true, lineStyle: { color: "#5470c6" } },
          axisTick: { show: false },
        },
      ],

      dataZoom: [
        {
          show: true,
          realtime: true,
          xAxisIndex: [0, 1, 2],
          start: effectiveZoomStart,
          end: effectiveZoomEnd,
          height: 24,
          bottom: 4,
          borderColor: "#dbe3f3",
          backgroundColor: "#f5f7fc",
          fillerColor: "rgba(151, 171, 232, 0.35)",
          handleStyle: { color: "#aab8df" },
          moveHandleStyle: { color: "#aab8df" },
          textStyle: { color: fgLight, fontSize: 10 },
          filterMode: "none",
        },
        {
          type: "inside",
          realtime: true,
          xAxisIndex: [0, 1, 2],
          start: effectiveZoomStart,
          end: effectiveZoomEnd,
          filterMode: "none",
        },
      ],

      series: [
        {
          name: "主力净流",
          type: "custom" as const,
          xAxisIndex: 0,
          yAxisIndex: 0,
          coordinateSystem: "cartesian2d" as const,
          clip: true,
          renderItem: (
            _params: unknown,
            api: {
              coord: (data: [number, number]) => [number, number]
            },
          ) => {
            if (mainNetFlowVirtualSamples.length < 2) return null

            const toPixel = (x: number, y: number): [number, number] => {
              const fx = Math.floor(x)
              const cx = Math.ceil(x)

              if (fx === cx) return api.coord([fx, y])

              const frac = x - fx
              const [px0, py0] = api.coord([fx, y])
              const [px1, py1] = api.coord([cx, y])
              return [px0 + (px1 - px0) * frac, py0 + (py1 - py0) * frac]
            }

            const topPoints = mainNetFlowVirtualSamples.map((p) =>
              toPixel(p.x, p.y),
            )

            const first = mainNetFlowVirtualSamples[0]
            const last = mainNetFlowVirtualSamples[mainNetFlowVirtualSamples.length - 1]

            const gradientLeft = toPixel(first.x, 0)
            const gradientRight = toPixel(last.x, 0)

            const lineGradient = {
              type: "linear" as const,
              x: gradientLeft[0],
              y: 0,
              x2: gradientRight[0],
              y2: 0,
              global: true,
              colorStops: buildFlowStops(mainNetFlowVirtualSamples, flowLineColor),
            }

            const areaGradient = {
              type: "linear" as const,
              x: gradientLeft[0],
              y: 0,
              x2: gradientRight[0],
              y2: 0,
              global: true,
              colorStops: buildFlowStops(mainNetFlowVirtualSamples, flowAreaColor),
            }

            const continuousArea = [
              toPixel(first.x, 0),
              ...topPoints,
              toPixel(last.x, 0),
            ]

            // 一整块 polygon 承载整条渐变, 避免薄片拼接产生抗锯齿白缝。
            const baseArea = {
              type: "polygon" as const,
              shape: { points: continuousArea },
              style: {
                fill: rgba(neutral, 0.105),
                stroke: "none",
              },
              silent: true,
            }

            const continuousGradientArea = {
              type: "polygon" as const,
              shape: { points: continuousArea },
              style: {
                fill: areaGradient,
                stroke: "none",
              },
              silent: true,
            }

            return {
              type: "group",
              children: [
                baseArea,
                continuousGradientArea,
                {
                  type: "polyline",
                  shape: {
                    points: topPoints,
                  },
                  style: {
                    fill: "none",
                    stroke: lineGradient,
                    lineWidth: 1.8,
                    lineJoin: "round" as const,
                    lineCap: "round" as const,
                  },
                  silent: true,
                },
              ],
            }
          },
          data: mainNetFlowVirtualSamples.length
            ? [{ value: [Math.max(0, dates.length - 1), 0] }]
            : [],
          tooltip: { show: false },
          // 叠到中间主图时作为背景信息层, 避免压住情绪线和上证线。
          z: 3,
        },

        {
          name: "主力净流压缩线",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: dates.map(() => null),
          symbol: "none",
          lineStyle: { width: 0, opacity: 0 },
          tooltip: { show: false },
          silent: true,
          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: "#047857",
              fontSize: 10,
              formatter: "500亿压缩线",
              position: "insideEndTop",
              backgroundColor: "rgba(255,255,255,0.72)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "dashed",
              color: "rgba(4,120,87,0.42)",
              width: 1,
            },
            data: [
              {
                yAxis: flowToVisual(FLOW_BREAKPOINT_YI),
                name: "500亿压缩线",
              },
            ],
          },
          z: 3,
        },

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
            opacity: 0.24,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(239, 68, 68, 0.26)" },
              { offset: 0.55, color: "rgba(249, 115, 22, 0.12)" },
              { offset: 1, color: "rgba(249, 115, 22, 0.01)" },
            ]),
          },
          emphasis: { disabled: true },
          tooltip: { show: false },
          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: "#444",
              fontSize: 11,
              fontWeight: 600,
              formatter: "中性线 50",
              position: "insideEndTop",
              backgroundColor: "rgba(255,255,255,0.70)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "solid",
              color: "rgba(80, 80, 80, 0.55)",
              width: 1.4,
            },
            data: [{ yAxis: 50, name: "中性线" }],
          },
          z: 2,
        },

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
            opacity: 0.22,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(14, 165, 233, 0.01)" },
              { offset: 0.45, color: "rgba(14, 165, 233, 0.10)" },
              { offset: 1, color: "rgba(37, 99, 235, 0.22)" },
            ]),
          },
          emphasis: { disabled: true },
          tooltip: { show: false },
          z: 2,
        },

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

        {
          name: "成交额",
          type: "line",
          xAxisIndex: 2,
          yAxisIndex: 3,
          data: amountVisualValues,
          symbol: "none",
          smooth: 0.22,
          connectNulls: false,
          clip: false,
          lineStyle: {
            width: 1.5,
            color: flowBlue,
          },
          areaStyle: {
            color: flowBlueArea,
          },
          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: "#5470c6",
              fontSize: 10,
              formatter: "25000亿压缩线",
              position: "insideEndTop",
              backgroundColor: "rgba(255,255,255,0.72)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "dashed",
              color: "rgba(84,112,198,0.45)",
              width: 1,
            },
            data: [
              {
                yAxis: amountToVisual(AMOUNT_BREAKPOINT_YI),
                name: "25000亿压缩线",
              },
            ],
          },
          emphasis: {
            focus: "series",
          },
          // 叠到中间主图时作为背景信息层, 中央情绪线和上证线仍在上面。
          z: 3,
        },
      ],
    }
  }, [
    data,
    shOverlay,
    mainNetFlowOverlay,
    amountOverlay,
    zoomRange?.start,
    zoomRange?.end,
    chartWidth,
  ])

  useEffect(() => {
    if (!ref.current) return

    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, {
        renderer: "canvas",
      })
    }

    const chart = chartRef.current
    chart.setOption(option, { notMerge: true, lazyUpdate: true })

    const syncSize = () => {
      chart.resize()
      const nextWidth = ref.current?.clientWidth ?? chart.getWidth?.() ?? 1200
      setChartWidth((prev) =>
        Math.abs(prev - nextWidth) > 2 ? nextWidth : prev,
      )
    }

    const syncZoomRange = () => {
      const model = chart.getOption() as { dataZoom?: Array<Record<string, unknown>> }
      const dz = Array.isArray(model.dataZoom) ? model.dataZoom[0] : undefined
      if (!dz) return

      const start = Number(dz.start ?? 0)
      const end = Number(dz.end ?? 100)
      if (!Number.isFinite(start) || !Number.isFinite(end)) return

      setZoomRange((prev) => {
        if (
          prev &&
          Math.abs(prev.start - start) < 0.03 &&
          Math.abs(prev.end - end) < 0.03
        ) {
          return prev
        }

        return { start, end }
      })
    }

    const onDataZoom = () => syncZoomRange()

    ;(chart as any).off("datazoom", onDataZoom)
    ;(chart as any).off("dataZoom", onDataZoom)
    ;(chart as any).on("datazoom", onDataZoom)
    ;(chart as any).on("dataZoom", onDataZoom)

    syncSize()
    syncZoomRange()

    window.addEventListener("resize", syncSize)

    const ro = new ResizeObserver(() => syncSize())
    ro.observe(ref.current)

    return () => {
      ;(chart as any).off("datazoom", onDataZoom)
      ;(chart as any).off("dataZoom", onDataZoom)
      window.removeEventListener("resize", syncSize)
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
