/**
 * 市场脉搏历史趋势图 (ECharts)
 *
 * 数据源: GET /api/stock-chart/market-overview-akshare/history?range=60d
 * 4 个视图共用一个 chart container, 由 view prop 切换:
 *   - turnover  成交趋势  (柱 + MA5 + MA20)
 *   - breadth   涨跌温度  (上涨占比 % + 50% 强弱线)
 *   - flow      资金潮汐  (红绿渐变面积 + 主线 + 4 虚线 + 0 轴 + 极值点)  ← 默认
 *   - structure 资金结构  (100% 堆叠面积, 按绝对值占比)
 *
 * hover 联动: onPointHover 回调当前 hover 的 date / point data,
 * 父组件 MarketPulsePanel 接到后驱动顶部两个快照卡临时显示该日数据.
 *
 * 单位约定 (跟现有 archive / snapshot 一致):
 *   - totalAmount / mainNetInflow / ... : 单位 "亿"
 *   - 涨跌家数: 整数
 *   - 渲染时: totalAmount / 1e4 = 万亿, mainNetInflow 直接 = 亿
 */
import { useEffect, useMemo, useRef } from "react"
import * as echarts from "echarts/core"
import { BarChart, LineChart } from "echarts/charts"
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  LegendComponent,
  CanvasRenderer,
])

import type { MarketHistoryPoint } from "@/lib/api"

export type PulseView = "turnover" | "breadth" | "flow" | "structure"

interface Props {
  data: MarketHistoryPoint[]
  view: PulseView
  /** hover 联动: 当前 hover 的 point (data 数组下标), null = 未 hover */
  hoverIndex: number | null
  /** hover 变化时回调 (用于驱动顶部快照卡联动) */
  onPointHover?: (idx: number | null, point: MarketHistoryPoint | null) => void
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------
/** 亿元 -> 万亿元 (用于成交额柱图, 全A 日成交 ~1万亿) */
function toWanYi(v: number | null | undefined): number | null {
  if (v == null || !Number.isFinite(v)) return null
  return v / 10000
}

/** 亿元数格式化 */
function formatYi(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(2)}亿`
}

/** 亿元 -> 万亿元格式化 */
function formatWanYi(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—"
  return `${(v / 10000).toFixed(2)}万亿`
}

/** 简单移动平均 (忽略 null) */
function movingAverage(values: Array<number | null>, windowSize: number): Array<number | null> {
  return values.map((_, i) => {
    const start = Math.max(0, i - windowSize + 1)
    const slice = values.slice(start, i + 1).filter((x): x is number => x != null)
    if (slice.length === 0) return null
    return slice.reduce((a, b) => a + b, 0) / slice.length
  })
}

// ---------------------------------------------------------------------------
// 各视图的 option builder
// ---------------------------------------------------------------------------
function buildBaseOption(dates: string[]) {
  return {
    backgroundColor: "#ffffff",
    animation: true,
    animationDuration: 500,
    animationDurationUpdate: 300,
    grid: { left: 12, right: 16, top: 56, bottom: 36, containLabel: true },
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
    },
    // 顶部水平 legend: 紧凑字体, 小色块, 单行(不够就溢出)
    // 单 series 视图(breadth)也会显示一项, 提示当前是什么指标
    legend: {
      show: true,
      top: 6,
      left: "center",
      orient: "horizontal",
      textStyle: { fontSize: 11, color: "#475569" },
      itemWidth: 12,
      itemHeight: 8,
      itemGap: 12,
      icon: "roundRect",
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: dates,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "#f1f5f9" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    dataZoom: [
      { type: "inside", zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
    ],
  } as const
}

/** 资金潮汐 flow: 红绿渐变面积 + 主线 + 4 虚线 + 0 轴 + 极值点 */
function buildFlowOption(data: MarketHistoryPoint[], dates: string[]) {
  const main = data.map((x) => x.mainNetInflow ?? null)
  const positive = main.map((v) => (v != null && v > 0 ? v : 0))
  const negative = main.map((v) => (v != null && v < 0 ? v : 0))

  return {
    ...buildBaseOption(dates),
    // flow 视图只暴露 5 条真正可切换的线; 2 个渐变面积是视觉背景, 不进 legend
    legend: {
      show: true,
      top: 6,
      left: "center",
      orient: "horizontal",
      textStyle: { fontSize: 11, color: "#475569" },
      itemWidth: 14,
      itemHeight: 8,
      itemGap: 12,
      icon: "roundRect",
      data: ["主力净流入", "超大单", "大单", "中单", "小单"],
    },
    yAxis: {
      ...(buildBaseOption(dates).yAxis as object),
      axisLabel: {
        color: "#94a3b8",
        fontSize: 11,
        formatter: (v: number) => `${v.toFixed(0)}亿`,
      },
    },
    tooltip: {
      ...(buildBaseOption(dates).tooltip as object),
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number }>
        const i = arr?.[0]?.dataIndex ?? 0
        const row = data[i]
        if (!row) return ""
        return [
          `<div style="font-weight:700;margin-bottom:6px">${row.date}</div>`,
          `<div>主力净流入：<b>${formatYi(row.mainNetInflow)}</b></div>`,
          `<div>超大单：<b>${formatYi(row.superLargeNetInflow)}</b></div>`,
          `<div>大单：<b>${formatYi(row.largeNetInflow)}</b></div>`,
          `<div>中单：<b>${formatYi(row.mediumNetInflow)}</b></div>`,
          `<div>小单：<b>${formatYi(row.smallNetInflow)}</b></div>`,
        ].join("")
      },
    },
    series: [
      // 红渐变: 正向面积
      {
        name: "净流入区域",
        type: "line",
        data: positive,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(220, 38, 38, 0.24)" },
              { offset: 1, color: "rgba(220, 38, 38, 0.02)" },
            ],
          },
        },
        emphasis: { disabled: true },
        z: 1,
      },
      // 绿渐变: 负向面积
      {
        name: "净流出区域",
        type: "line",
        data: negative,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(22, 163, 74, 0.02)" },
              { offset: 1, color: "rgba(22, 163, 74, 0.22)" },
            ],
          },
        },
        emphasis: { disabled: true },
        z: 1,
      },
      // 主线: 主力净流入
      {
        name: "主力净流入",
        type: "line",
        data: main,
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: {
          width: 3,
          color: "#dc2626",
          shadowBlur: 10,
          shadowColor: "rgba(220, 38, 38, 0.22)",
        },
        itemStyle: { color: "#dc2626", borderColor: "#ffffff", borderWidth: 2 },
        endLabel: {
          show: true,
          formatter: "主力净流入",
          color: "#dc2626",
          fontSize: 11,
          fontWeight: 600,
          padding: [0, 0, 0, 4],
        },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: "#cbd5e1", type: "dashed", width: 1 },
          label: { color: "#94a3b8", fontSize: 10, formatter: "0轴" },
          data: [{ yAxis: 0 }],
        },
        markPoint: {
          symbolSize: 44,
          label: {
            color: "#fff",
            fontSize: 10,
            formatter: (p: { name?: string }) =>
              p.name === "max" ? "高" : p.name === "min" ? "低" : "",
          },
          data: [{ type: "max", name: "max" }, { type: "min", name: "min" }],
        },
        z: 4,
      },
      // 4 条细虚线 (超大/大/中/小) - 颜色刻意拉开: 红 / 琥珀 / 翠绿 / 靛蓝
      {
        name: "超大单",
        type: "line",
        data: data.map((x) => x.superLargeNetInflow ?? null),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, type: "dashed", color: "#ef4444" },
        endLabel: { show: true, formatter: "超大单", color: "#ef4444", fontSize: 10, padding: [0, 0, 0, 4] },
        z: 2,
      },
      {
        name: "大单",
        type: "line",
        data: data.map((x) => x.largeNetInflow ?? null),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, type: "dashed", color: "#f59e0b" },
        endLabel: { show: true, formatter: "大单", color: "#f59e0b", fontSize: 10, padding: [0, 0, 0, 4] },
        z: 2,
      },
      {
        name: "中单",
        type: "line",
        data: data.map((x) => x.mediumNetInflow ?? null),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, type: "dashed", color: "#10b981" },
        endLabel: { show: true, formatter: "中单", color: "#10b981", fontSize: 10, padding: [0, 0, 0, 4] },
        z: 2,
      },
      {
        name: "小单",
        type: "line",
        data: data.map((x) => x.smallNetInflow ?? null),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, type: "dashed", color: "#6366f1" },
        endLabel: { show: true, formatter: "小单", color: "#6366f1", fontSize: 10, padding: [0, 0, 0, 4] },
        z: 2,
      },
    ],
  }
}

/** 成交趋势 turnover: 柱 + MA5 + MA20 (单位: 万亿) */
function buildTurnoverOption(data: MarketHistoryPoint[], dates: string[]) {
  const amountWanYi = data.map((x) => toWanYi(x.totalAmount))
  const ma5 = movingAverage(amountWanYi, 5)
  const ma20 = movingAverage(amountWanYi, 20)
  const base = buildBaseOption(dates)
  return {
    ...base,
    tooltip: {
      ...(base.tooltip as object),
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number }>
        const i = arr?.[0]?.dataIndex ?? 0
        const row = data[i]
        if (!row) return ""
        return [
          `<div style="font-weight:700;margin-bottom:6px">${row.date}</div>`,
          `<div>全 A 成交额：<b>${formatWanYi(row.totalAmount)}</b></div>`,
          `<div>上涨 / 下跌：<b>${row.risingCount ?? "—"} / ${row.fallingCount ?? "—"}</b></div>`,
        ].join("")
      },
    },
    yAxis: {
      ...(base.yAxis as object),
      axisLabel: {
        color: "#94a3b8",
        fontSize: 11,
        formatter: (v: number) => `${v.toFixed(1)}万亿`,
      },
    },
    series: [
      {
        name: "成交额",
        type: "bar",
        data: amountWanYi,
        barWidth: "42%",
        itemStyle: {
          color: "rgba(148, 163, 184, 0.28)",
          borderRadius: [6, 6, 0, 0],
        },
        z: 1,
      },
      {
        name: "MA5",
        type: "line",
        data: ma5,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: "#0f172a" },
        z: 3,
      },
      {
        name: "MA20",
        type: "line",
        data: ma20,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, type: "dashed", color: "#64748b" },
        z: 2,
      },
    ],
  }
}

/** 涨跌温度 breadth: 上涨占比 (0-100%) + 50% 强弱线 */
function buildBreadthOption(data: MarketHistoryPoint[], dates: string[]) {
  const upRatio = data.map((x) => {
    const up = x.risingCount ?? 0
    const down = x.fallingCount ?? 0
    const flat = x.flatCount ?? 0
    const total = up + down + flat
    return total > 0 ? (up / total) * 100 : null
  })
  const base = buildBaseOption(dates)
  return {
    ...base,
    yAxis: {
      ...(base.yAxis as object),
      min: 0,
      max: 100,
      axisLabel: {
        color: "#94a3b8",
        fontSize: 11,
        formatter: "{value}%",
      },
    },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number }>
        const i = arr?.[0]?.dataIndex ?? 0
        const row = data[i]
        const ratio = upRatio[i]
        if (!row) return ""
        return [
          `<div style="font-weight:700;margin-bottom:6px">${row.date}</div>`,
          `<div>上涨占比：<b>${ratio == null ? "—" : `${ratio.toFixed(1)}%`}</b></div>`,
          `<div>上涨 / 下跌：<b>${row.risingCount ?? "—"} / ${row.fallingCount ?? "—"}</b></div>`,
          `<div>涨停 / 跌停：<b>${row.limitUpCount ?? "—"} / ${row.limitDownCount ?? "—"}</b></div>`,
        ].join("")
      },
    },
    series: [
      {
        name: "上涨占比",
        type: "line",
        data: upRatio,
        smooth: true,
        showSymbol: false,
        lineStyle: {
          width: 3,
          color: "#dc2626",
          shadowBlur: 10,
          shadowColor: "rgba(220, 38, 38, 0.18)",
        },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(220, 38, 38, 0.20)" },
              { offset: 1, color: "rgba(220, 38, 38, 0.02)" },
            ],
          },
        },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: "#cbd5e1", type: "dashed" },
          label: { color: "#94a3b8", fontSize: 10, formatter: "强弱线 50%" },
          data: [{ yAxis: 50 }],
        },
      },
    ],
  }
}

/** 资金结构 structure: 100% 堆叠面积 (按绝对值占比) */
function buildStructureOption(data: MarketHistoryPoint[], dates: string[]) {
  const rows = data.map((x) => {
    const a = Math.abs(x.superLargeNetInflow ?? 0)
    const b = Math.abs(x.largeNetInflow ?? 0)
    const c = Math.abs(x.mediumNetInflow ?? 0)
    const d = Math.abs(x.smallNetInflow ?? 0)
    const total = a + b + c + d
    if (total <= 0) return { superLarge: null, large: null, medium: null, small: null }
    return {
      superLarge: (a / total) * 100,
      large: (b / total) * 100,
      medium: (c / total) * 100,
      small: (d / total) * 100,
    }
  })
  const base = buildBaseOption(dates)
  return {
    ...base,
    yAxis: {
      ...(base.yAxis as object),
      min: 0,
      max: 100,
      axisLabel: { color: "#94a3b8", fontSize: 11, formatter: "{value}%" },
    },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number }>
        const i = arr?.[0]?.dataIndex ?? 0
        const row = rows[i]
        const date = data[i]?.date ?? ""
        if (!row) return ""
        return [
          `<div style="font-weight:700;margin-bottom:6px">${date}</div>`,
          `<div>超大单：<b>${row.superLarge == null ? "—" : row.superLarge.toFixed(1) + "%"}</b></div>`,
          `<div>大单：<b>${row.large == null ? "—" : row.large.toFixed(1) + "%"}</b></div>`,
          `<div>中单：<b>${row.medium == null ? "—" : row.medium.toFixed(1) + "%"}</b></div>`,
          `<div>小单：<b>${row.small == null ? "—" : row.small.toFixed(1) + "%"}</b></div>`,
        ].join("")
      },
    },
    series: [
      {
        name: "超大单",
        type: "line",
        stack: "total",
        data: rows.map((x) => x.superLarge),
        smooth: true,
        showSymbol: false,
        areaStyle: {},
        lineStyle: { width: 0 },
        itemStyle: { color: "rgba(220, 38, 38, 0.72)" },
      },
      {
        name: "大单",
        type: "line",
        stack: "total",
        data: rows.map((x) => x.large),
        smooth: true,
        showSymbol: false,
        areaStyle: {},
        lineStyle: { width: 0 },
        itemStyle: { color: "rgba(248, 113, 113, 0.68)" },
      },
      {
        name: "中单",
        type: "line",
        stack: "total",
        data: rows.map((x) => x.medium),
        smooth: true,
        showSymbol: false,
        areaStyle: {},
        lineStyle: { width: 0 },
        itemStyle: { color: "rgba(134, 239, 172, 0.68)" },
      },
      {
        name: "小单",
        type: "line",
        stack: "total",
        data: rows.map((x) => x.small),
        smooth: true,
        showSymbol: false,
        areaStyle: {},
        lineStyle: { width: 0 },
        itemStyle: { color: "rgba(21, 128, 61, 0.68)" },
      },
    ],
  }
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------
export function MarketPulseEChart({ data, view, hoverIndex, onPointHover }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const dates = useMemo(
    () => data.map((x) => x.date.slice(5).replace("-", "/")),
    [data],
  )

  // 初始化 chart
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })
    chartRef.current = chart
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  // 更新 view / data
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    let option: echarts.EChartsCoreOption
    if (view === "flow") option = buildFlowOption(data, dates) as echarts.EChartsCoreOption
    else if (view === "turnover") option = buildTurnoverOption(data, dates) as echarts.EChartsCoreOption
    else if (view === "breadth") option = buildBreadthOption(data, dates) as echarts.EChartsCoreOption
    else option = buildStructureOption(data, dates) as echarts.EChartsCoreOption
    chart.setOption(option, true)
  }, [data, dates, view])

  // hover 联动: 高亮当前 hover 索引 (markPoint / markLine)
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.dispatchAction({
      type: hoverIndex == null ? "downplay" : "highlight",
      seriesIndex: 2, // 主线 (flow / breadth 通用)
      dataIndex: hoverIndex ?? 0,
    })
    chart.dispatchAction({
      type: "showTip",
      seriesIndex: 2,
      dataIndex: hoverIndex ?? 0,
    })
  }, [hoverIndex])

  // 鼠标事件: 触发 hover 联动
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onPointHover) return
    const onUpdate = (e: { dataIndex?: number }) => {
      const i = e.dataIndex
      if (typeof i === "number" && i >= 0 && i < data.length) {
        onPointHover(i, data[i])
      }
    }
    const onOut = () => onPointHover(null, null)
    chart.on("updateAxisPointer", onUpdate)
    const zr = chart.getZr()
    if (zr) zr.on("mouseout", onOut)
    return () => {
      // 走 ref 而不是 closure: init 卸载时可能先把 chart.dispose() 掉,
      // 此时 closure 里的 chart.getZr() 已返回 null, .off() 会炸.
      const c = chartRef.current
      if (!c) return
      try { c.off("updateAxisPointer", onUpdate) } catch { /* 已 dispose, 忽略 */ }
      const z = c.getZr()
      if (z) { try { z.off("mouseout", onOut) } catch { /* 忽略 */ } }
    }
  }, [data, onPointHover])

  return <div ref={ref} className="h-full w-full bg-white" />
}