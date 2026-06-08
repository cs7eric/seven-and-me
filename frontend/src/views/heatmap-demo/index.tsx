import { useEffect, useRef, useState } from "react"
import * as echarts from "echarts/core"
import { TreemapChart } from "echarts/charts"
import { TitleComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([TreemapChart, TitleComponent, TooltipComponent, CanvasRenderer])

// ---------------------------------------------------------------------------
// 涨跌色阶 (与 sector-heatmap.tsx 同款)
// 阈值 ±0.5% / ±2% / ±5% / ±10%, 涨红跌绿, 越远越深
// ---------------------------------------------------------------------------
type HeatmapBand =
  | "upExtreme" | "upStrong" | "upMid" | "upLight" | "flat"
  | "downLight" | "downMid" | "downStrong" | "downExtreme"

const BAND_COLORS: Record<HeatmapBand, { bg: string; fg: string }> = {
  upExtreme:   { bg: "#B71C1C", fg: "#ffffff" },
  upStrong:    { bg: "#D32F2F", fg: "#ffffff" },
  upMid:       { bg: "#F44336", fg: "#ffffff" },
  upLight:     { bg: "#EF9A9A", fg: "#7f1d1d" },
  flat:        { bg: "#9E9E9E", fg: "#ffffff" },
  downLight:   { bg: "#A5D6A7", fg: "#14532d" },
  downMid:     { bg: "#4CAF50", fg: "#ffffff" },
  downStrong:  { bg: "#2E7D32", fg: "#ffffff" },
  downExtreme: { bg: "#1B5E20", fg: "#ffffff" },
}

function bandForPct(pct: number | null | undefined): HeatmapBand {
  if (pct == null || !Number.isFinite(pct) || Math.abs(pct) > 50) return "flat"
  if (pct >= 10) return "upExtreme"
  if (pct >= 5) return "upStrong"
  if (pct >= 2) return "upMid"
  if (pct >= 0.5) return "upLight"
  if (pct <= -10) return "downExtreme"
  if (pct <= -5) return "downStrong"
  if (pct <= -2) return "downMid"
  if (pct <= -0.5) return "downLight"
  return "flat"
}

function colorForPct(pct: number | null | undefined): { bg: string; fg: string } {
  return BAND_COLORS[bandForPct(pct)]
}

function formatPct(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}%`
}

// ---------------------------------------------------------------------------
// Demo 1: 最小 treemap (echarts 自带 sample, 验证 echarts 渲染)
// ---------------------------------------------------------------------------
const SAMPLE_DATA = {
  name: "flare",
  children: [
    { name: "analytics", children: [
      { name: "cluster", value: 1358 },
      { name: "graph", value: 4231 },
      { name: "optimization", value: 6999 },
    ]},
    { name: "data", children: [
      { name: "converters", value: 12000 },
      { name: "DataUtil", value: 8000 },
      { name: "DataSet", value: 9000 },
    ]},
    { name: "display", children: [
      { name: "DirtySprite", value: 1000 },
      { name: "LineSprite", value: 2000 },
      { name: "RectSprite", value: 3000 },
      { name: "TextSprite", value: 4000 },
    ]},
    { name: "util", children: [
      { name: "Arrays", value: 8258 },
      { name: "Colors", value: 10001 },
      { name: "math", value: 11782 },
    ]},
  ],
}

export function HeatmapDemoPage() {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })
    chart.setOption({
      title: { text: "Treemap 最小 demo (验证 echarts)", left: 16, top: 8 },
      tooltip: { trigger: "item" },
      series: [{
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        data: SAMPLE_DATA.children,
        label: { show: true, formatter: "{b}" },
      }],
    })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.dispose() }
  }, [])

  return (
    <div className="flex h-screen w-screen flex-col bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
        路由: <code className="rounded bg-slate-200 px-1.5 py-0.5">/heatmap-demo</code>
        · 数据: 简化版 sample data · 用于验证 echarts treemap 渲染
      </div>
      <div ref={ref} className="h-[600px] w-full" />
    </div>
  )
}

export default HeatmapDemoPage

// ---------------------------------------------------------------------------
// Demo 2: 29 个风格板块热力图 (与 sector-heatmap.tsx 同款渲染)
//   数据源: GET /api/stock-chart/style-sectors
//   渲染:   treemap, 面积=成分股数 (sample_size), 颜色=板块涨跌幅
//   交互:   tooltip 展示 涨跌幅 / 有效成分股 / 数据完整度
// ---------------------------------------------------------------------------
const STYLE_SECTORS_API = "http://localhost:5000/api/stock-chart/style-sectors"

interface StyleSectorItem {
  name: string
  change_pct: number | null
  valid_size: number
  sample_size: number
}

export function HeatmapDataDebug() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [items, setItems] = useState<StyleSectorItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(STYLE_SECTORS_API)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = await r.json()
      const list: StyleSectorItem[] = Array.isArray(j) ? j : (j.items || [])
      setItems(list)
      setFetchedAt(new Date().toLocaleString("zh-CN"))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  useEffect(() => {
    if (!ref.current || items.length === 0) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })

    const data = items.map((s) => {
      const c = colorForPct(s.change_pct)
      return {
        name: s.name,
        value: Math.max(s.sample_size || 1, 1),
        itemStyle: {
          color: c.bg,
          borderColor: "#e2e8f0",
          borderWidth: 2,
          gapWidth: 4,
        },
        label: {
          show: true,
          color: c.fg,
          fontSize: 13,
          fontWeight: 700,
          lineHeight: 18,
          formatter: () => `{name|${s.name}}\n{pct|${formatPct(s.change_pct)}}`,
          rich: {
            name: { color: c.fg, fontSize: 13, fontWeight: 700, lineHeight: 18 },
            pct: { color: c.fg, fontSize: 11, fontWeight: 600, lineHeight: 16 },
          },
        },
      }
    })

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (info: any) => {
          const s = items.find((x) => x.name === info.name)
          if (!s) return ""
          const coverage = s.sample_size > 0 ? ((s.valid_size / s.sample_size) * 100).toFixed(1) : "0.0"
          return [
            `<div style="font-weight:700;margin-bottom:6px">${s.name}</div>`,
            `<div>板块涨跌幅：${formatPct(s.change_pct)}</div>`,
            `<div>有效成分股：${s.valid_size} / ${s.sample_size}</div>`,
            `<div>数据完整度：${coverage}%</div>`,
          ].join("")
        },
      },
      series: [{
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        nodeGap: 6,
        nodePadding: 2,
        label: {
          show: true,
          color: "#fff",
          fontSize: 12,
          lineHeight: 16,
        },
        data,
      }],
    })

    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.dispose() }
  }, [items])

  return (
    <div className="flex h-screen w-screen flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
        <div>
          路由: <code className="rounded bg-slate-200 px-1.5 py-0.5">/heatmap-data-debug</code>
          · 数据: <code>GET /api/stock-chart/style-sectors</code>
          · 状态: {error
            ? <span className="text-red-600">{error}</span>
            : loading
              ? "loading…"
              : `${items.length} 个风格板块${fetchedAt ? ` · ${fetchedAt}` : ""}`}
        </div>
        <button
          type="button"
          onClick={fetchData}
          disabled={loading}
          className="rounded border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>
      <div ref={ref} className="h-[600px] w-full" />
    </div>
  )
}
