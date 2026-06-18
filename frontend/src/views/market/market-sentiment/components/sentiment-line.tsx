/**
 * ECharts 情绪分趋势折线 (composite 大卡左侧专用)
 * 视觉: smooth line + 双面积围绕 50 中性线 (上红橙扩张 / 下蓝绿收缩) +
 *        50 markLine + hover tooltip + inside slider dataZoom.
 * Y 轴固定 0-100, 主叙事 = 50 上是扩张 / 50 下是收缩.
 */
import { useEffect, useMemo, useRef } from "react"
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
import { scoreToColor, scoreToRgb } from "../lib/color"

echarts.use([
  CustomChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  CanvasRenderer,
])

interface SentimentLinePoint { date: string; value: number; level?: string }
interface SentimentLineProps {
  data: SentimentLinePoint[]
  height?: number
  /** 用浅色主题 (默认 false, 大卡深底浅字) */
  light?: boolean
}

export function SentimentLine({ data, height = 220, light = false }: SentimentLineProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((d) => d.date)
    const values = data.map((d) => d.value)

    const minValue = values.length ? Math.min(...values) : 0
    const maxValue = values.length ? Math.max(...values) : 100
    const valueRange = Math.max(1, maxValue - minValue)
    // Y 轴 padding 收紧到 10%, 让 18 分差距看起来更剧烈 (不再像 0-100 那么平)
    const padding = Math.max(3, valueRange * 0.10)

    // 默认 dataZoom 进入最近 ~63 个交易日 (≈ 3 个月); 用户可拖回全量
    // total=770 时 start≈91.8, total=60 时 start=0 (数据不够也铺满)
    const recentBars = 63
    const totalBars = values.length
    const zoomStart = totalBars > recentBars
      ? Math.max(0, 100 - (recentBars / totalBars) * 100)
      : 0

    /**
     * 动态缩放：
     * - 始终尽量包含 50 中性线；
     * - 不再固定 0-100；
     * - 但上下限仍限制在 0-100。
     */
    const yMin = Math.max(0, Math.floor(Math.min(minValue, 50) - padding))
    const yMax = Math.min(100, Math.ceil(Math.max(maxValue, 50) + padding))

    /**
     * 上下区域数据：
     * - bullData：只显示 50 以上区域；
     * - bearData：只显示 50 以下区域。
     */
    const bullData = values.map((v) => (v >= 50 ? v : 50))
    const bearData = values.map((v) => (v < 50 ? v : 50))

    // 相邻点线段 (每条线段用温度计色阶渐变着色)
    const lineSegments: { x1: number; y1: number; x2: number; y2: number }[] = []
    for (let i = 1; i < values.length; i++) {
      lineSegments.push({ x1: i - 1, y1: values[i - 1], x2: i, y2: values[i] })
    }

    const fg = light ? "#475569" : "#94a3b8"
    const fgStrong = light ? "#0f172a" : "#e2e8f0"
    const axisLine = light ? "rgba(15, 23, 42, 0.12)" : "rgba(148, 163, 184, 0.28)"
    const splitLine = light ? "rgba(15, 23, 42, 0.06)" : "rgba(148, 163, 184, 0.10)"

    return {
      backgroundColor: "transparent",

      grid: {
        left: 38,
        right: 18,
        top: 18,
        bottom: 44,
        containLabel: false,
      },

      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
          lineStyle: {
            color: "rgba(148, 163, 184, 0.45)",
            width: 1,
          },
        },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "rgba(148, 163, 184, 0.25)",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: {
          color: "#e5e7eb",
          fontSize: 12,
        },
        formatter: (params: unknown) => {
          const arr = params as Array<{
            axisValueLabel: string
            value: number
            dataIndex: number
            seriesName: string
          }>

          if (!arr || !arr.length) return ""

          const realPoint = arr.find((p) => p.seriesName === "市场情绪指数") ?? arr[0]
          const idx = realPoint.dataIndex
          const score = Number(values[idx] ?? realPoint.value)
          const diff = score - 50

          const moodLabel =
            score >= 70 ? "极热"
            : score >= 60 ? "偏热"
            : score >= 50 ? "偏多"
            : score >= 40 ? "偏弱"
            : score >= 30 ? "低迷"
            : "冰点"

          const moodColor =
            score >= 70 ? "#ef4444"
            : score >= 60 ? "#f97316"
            : score >= 50 ? "#f59e0b"
            : score >= 40 ? "#38bdf8"
            : score >= 30 ? "#60a5fa"
            : "#94a3b8"

          return `
            <div style="font-weight:600;margin-bottom:6px;">${realPoint.axisValueLabel}</div>
            <div>情绪分: <b style="color:${moodColor};font-size:14px;">${score.toFixed(1)}</b></div>
            <div style="margin-top:3px;">状态: <span style="color:${moodColor};">${moodLabel}</span></div>
            <div style="margin-top:3px;color:#94a3b8;">距离中性线: ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}</div>
          `
        },
      },

      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates,
        axisLine: {
          lineStyle: {
            color: axisLine,
          },
        },
        axisTick: {
          show: false,
        },
        axisLabel: {
          color: fg,
          fontSize: 10,
          margin: 10,
        },
      },

      yAxis: {
        type: "value",
        min: yMin,
        max: yMax,
        splitNumber: 4,
        axisLabel: {
          color: fg,
          fontSize: 10,
          formatter: "{value}",
        },
        splitLine: {
          lineStyle: {
            color: splitLine,
          },
        },
        axisLine: {
          show: false,
        },
        axisTick: {
          show: false,
        },
      },

      dataZoom: [
        {
          type: "inside",
          start: zoomStart,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
        {
          type: "slider",
          start: zoomStart,
          end: 100,
          height: 18,
          bottom: 6,
          borderColor: "transparent",
          backgroundColor: light ? "rgba(15,23,42,0.04)" : "rgba(148,163,184,0.08)",
          fillerColor: light ? "rgba(15,23,42,0.10)" : "rgba(148,163,184,0.18)",
          handleStyle: {
            color: light ? "#94a3b8" : "#64748b",
          },
          textStyle: {
            color: fg,
            fontSize: 10,
          },
        },
      ],

      series: [
        // ── 面积层 (多头 / 空头区域) ──
        {
          name: "多头区域",
          type: "line",
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
          // 中性线 markLine 从原主线移到此面积系列
          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: fgStrong,
              fontSize: 11,
              fontWeight: 600,
              formatter: "中性线 50",
              position: "insideEndTop",
              backgroundColor: light ? "rgba(15,23,42,0.04)" : "rgba(226,232,240,0.10)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "solid",
              color: light ? "rgba(15, 23, 42, 0.65)" : "rgba(226, 232, 240, 0.70)",
              width: 1.6,
            },
            data: [{ yAxis: 50, name: "中性线" }],
          },
          z: 1,
        },

        {
          name: "空头区域",
          type: "line",
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
          z: 1,
        },

        // ── 隐形线 (仅给 tooltip 提供 dataIndex / x 映射, 视觉不可见) ──
        {
          name: "市场情绪指数",
          type: "line",
          data: values,
          symbol: "none",
          lineStyle: { width: 0, opacity: 0 },
          z: 2,
        },

        // ── 温度计色阶主线 (单个 custom series, 每条线段 stroke 使用渐变) ──
        ...(lineSegments.length > 0
          ? [{
              name: "市场情绪指数",
              type: "custom" as const,
              coordinateSystem: "cartesian2d" as const,
              clip: true,
              renderItem: (_params: unknown, api: {
                value: (dim: number) => unknown
                coord: (data: [number, number]) => [number, number]
              }) => {
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
                      stroke: {
                        type: "linear" as const,
                        x: start[0], y: 0,
                        x2: end[0], y2: 0,
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
                  }],
                }
              },
              data: lineSegments.map((s) => ({ value: [s.x1, s.y1, s.x2, s.y2] })),
              tooltip: { show: false },
              z: 3,
            }]
          : []),
      ],
    }
  }, [data, light])

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, { renderer: "canvas" })
    }
    chartRef.current.setOption(option, { notMerge: true })
    const onWinResize = () => chartRef.current?.resize()
    window.addEventListener("resize", onWinResize)
    // 监听容器尺寸变化 (grid/flex 调整父宽时也会触发)
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