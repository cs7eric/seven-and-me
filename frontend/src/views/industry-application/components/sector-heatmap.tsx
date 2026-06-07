/**
 * 市场热力图（同花顺式 ECharts Treemap）
 *
 * - 一级: 行业按 成交额(amount) 切分面积
 * - 二级 (钻入后): 行业内个股按 成交额 切分面积
 * - 颜色: 涨跌幅 4 档 (red-300/500/700 / green-300/500/700) + 灰色中性
 * - 文字: 行业 cell 显示 名称 + 涨跌幅, 个股 cell 显示 名称 + 涨跌幅
 *   (面积太小自动隐藏, 由 ECharts `labelLayout.hideOverlap` 兜底)
 * - 交互:
 *   - 鼠标悬停: 弹出 tooltip (代码/价格/成交额/换手率/流通市值/主力净流入/涨速/概念/...)
 *   - 点击行业: 钻入 sector 视图
 *   - "返回全市场" 按钮: 回到 market 视图
 *   - 实时刷新 / 5 个快捷筛选 / 搜索 / 面积-颜色-排序切换
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, Building2, RefreshCw, Search, TrendingUp, Zap } from "lucide-react"
import * as echarts from "echarts/core"
import { TreemapChart } from "echarts/charts"
import {
  TooltipComponent,
  TitleComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([TreemapChart, TooltipComponent, TitleComponent, CanvasRenderer])

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

import type {
  HeatmapAreaBy,
  HeatmapColorBy,
  HeatmapQuickFilter,
  HeatmapSectorNode,
  HeatmapSortBy,
  MarketHeatmapResponse,
  StockHeatmapItem,
} from "../lib/types"

interface Props {
  data: MarketHeatmapResponse | null
  loading: boolean
  onRefresh: () => void
  autoRefresh: boolean
  onAutoRefreshChange: (value: boolean) => void
  kind: "industries" | "concepts" | "styles"
  onKindChange: (kind: "industries" | "concepts" | "styles") => void
}

type ViewMode = "market" | "sector"

// ---------------------------------------------------------------------------
// 常量配置
// ---------------------------------------------------------------------------

const QUICK_FILTER_OPTIONS: Array<{ value: HeatmapQuickFilter; label: string }> = [
  { value: "limitUp", label: "只看涨停股" },
  { value: "mainNetInflow", label: "只看主力净流入" },
  { value: "amountTop100", label: "只看成交额前100" },
  { value: "turnoverTop100", label: "只看换手率前100" },
  { value: "limitStreak", label: "只看连板股" },
]

const KIND_OPTIONS: Array<{ value: "industries" | "concepts" | "styles"; label: string }> = [
  { value: "industries", label: "行业" },
  { value: "concepts", label: "概念" },
  { value: "styles", label: "风格" },
]

const AREA_OPTIONS: Array<{ value: HeatmapAreaBy; label: string }> = [
  { value: "amount", label: "面积: 成交额" },
  { value: "circulatingMarketCap", label: "面积: 流通市值" },
]

const COLOR_OPTIONS: Array<{ value: HeatmapColorBy; label: string }> = [
  { value: "changePercent", label: "颜色: 涨跌幅" },
  { value: "mainNetInflow", label: "颜色: 主力净流入" },
  { value: "speed", label: "颜色: 涨速" },
]

const SORT_OPTIONS: Array<{ value: HeatmapSortBy; label: string }> = [
  { value: "changePercent", label: "排序: 涨跌幅" },
  { value: "amount", label: "排序: 成交额" },
  { value: "turnoverRate", label: "排序: 换手率" },
  { value: "mainNetInflow", label: "排序: 主力净流入" },
  { value: "speed", label: "排序: 涨速" },
  { value: "limitStreak", label: "排序: 连板数" },
]

function stockName(stock: StockHeatmapItem): string {
  return stock.name && stock.name !== stock.code ? stock.name : stock.code.slice(-4)
}

// ---------------------------------------------------------------------------
// 工具方法
// ---------------------------------------------------------------------------

function formatPct(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}%`
}

function formatAmount(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return value.toFixed(0)
}

function rankTop<T>(items: T[], metric: (item: T) => number | null | undefined, topN: number) {
  return [...items]
    .sort((a, b) => (metric(b) ?? Number.NEGATIVE_INFINITY) - (metric(a) ?? Number.NEGATIVE_INFINITY))
    .slice(0, topN)
}

function stockMatchesKeyword(stock: StockHeatmapItem, keyword: string) {
  if (!keyword) return true
  const haystack = [stock.name, stock.code, stock.sectorName, ...(stock.conceptTags || [])].join(" ").toLowerCase()
  return haystack.includes(keyword)
}

function sectorMatchesKeyword(sector: HeatmapSectorNode, keyword: string) {
  if (!keyword) return true
  if (sector.name.toLowerCase().includes(keyword) || sector.sectorCode.toLowerCase().includes(keyword)) return true
  return sector.children.some((child) => stockMatchesKeyword(child, keyword))
}

function sortStocks(items: StockHeatmapItem[], sortBy: HeatmapSortBy) {
  const getter = (item: StockHeatmapItem) => {
    switch (sortBy) {
      case "amount": return item.amount ?? -Infinity
      case "turnoverRate": return item.turnoverRate ?? -Infinity
      case "mainNetInflow": return item.mainNetInflow ?? -Infinity
      case "speed": return item.speed ?? -Infinity
      case "limitStreak": return item.limitStreak ?? -Infinity
      case "changePercent":
      default: return item.changePercent ?? -Infinity
    }
  }
  return [...items].sort((a, b) => getter(b) - getter(a))
}

function buildFilteredData(
  sectors: HeatmapSectorNode[],
  keyword: string,
  quickFilter: HeatmapQuickFilter | "all",
  sortBy: HeatmapSortBy,
) {
  const lowerKeyword = keyword.trim().toLowerCase()
  let globalTopAmount = new Set<string>()
  let globalTopTurnover = new Set<string>()

  if (quickFilter === "amountTop100") {
    globalTopAmount = new Set(rankTop(sectors.flatMap((sector) => sector.children), (item) => item.amount, 100).map((item) => item.fullCode))
  }
  if (quickFilter === "turnoverTop100") {
    globalTopTurnover = new Set(rankTop(sectors.flatMap((sector) => sector.children), (item) => item.turnoverRate, 100).map((item) => item.fullCode))
  }

  return sectors
    .filter((sector) => sectorMatchesKeyword(sector, lowerKeyword))
    .map((sector) => {
      let children = sector.children.filter((stock) => stockMatchesKeyword(stock, lowerKeyword))
      if (quickFilter === "limitUp") children = children.filter((stock) => stock.isLimitUp)
      if (quickFilter === "mainNetInflow") children = children.filter((stock) => (stock.mainNetInflow ?? 0) > 0)
      if (quickFilter === "amountTop100") children = children.filter((stock) => globalTopAmount.has(stock.fullCode))
      if (quickFilter === "turnoverTop100") children = children.filter((stock) => globalTopTurnover.has(stock.fullCode))
      if (quickFilter === "limitStreak") children = children.filter((stock) => (stock.limitStreak ?? 0) > 0)
      children = sortStocks(children, sortBy)
      return { ...sector, children }
    })
    .filter((sector) => sector.children.length > 0)
}

// ---------------------------------------------------------------------------
// 构造 treemap data
// ---------------------------------------------------------------------------

type EChartsTreemapNode = {
  name: string
  value: number
  itemStyle?: { color?: string; borderColor?: string; borderWidth?: number; gapWidth?: number }
  upperLabel?: { show?: boolean; height?: number; color?: string; fontSize?: number; fontWeight?: string | number; backgroundColor?: string; padding?: number[]; borderRadius?: number }
  label?: { show?: boolean; color?: string; fontSize?: number; formatter?: string | (() => string); position?: string; padding?: number[]; rich?: Record<string, unknown> }
  children?: EChartsTreemapNode[]
}

/**
 * 8 档涨跌色 + 1 档中性。涨红跌绿, 越远越深。阈值 ±0.5% / ±2% / ±5% / ±10%。
 */
type HeatmapBand =
  | "upExtreme"    // 涨停 >= +10%
  | "upStrong"     // +5% ~ +10%
  | "upMid"        // +2% ~ +5%
  | "upLight"      // +0.5% ~ +2%
  | "flat"         // ±0.5%
  | "downLight"    // -2% ~ -0.5%
  | "downMid"      // -5% ~ -2%
  | "downStrong"   // -10% ~ -5%
  | "downExtreme"  // 跌停 <= -10%

const BAND_COLORS: Record<HeatmapBand, { bg: string; fg: string }> = {
  upExtreme:   { bg: "#B71C1C", fg: "#ffffff" }, // 涨停: 深红
  upStrong:    { bg: "#D32F2F", fg: "#ffffff" }, // 大涨: 正红
  upMid:       { bg: "#F44336", fg: "#ffffff" }, // 明显上涨: 亮红
  upLight:     { bg: "#EF9A9A", fg: "#7f1d1d" }, // 小幅上涨: 浅红
  flat:        { bg: "#9E9E9E", fg: "#ffffff" }, // 基本持平: 灰
  downLight:   { bg: "#A5D6A7", fg: "#14532d" }, // 小幅下跌: 浅绿
  downMid:     { bg: "#4CAF50", fg: "#ffffff" }, // 明显下跌: 绿
  downStrong:  { bg: "#2E7D32", fg: "#ffffff" }, // 大跌: 深绿
  downExtreme: { bg: "#1B5E20", fg: "#ffffff" }, // 跌停: 暗绿
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

function buildTreemap(
  sectors: HeatmapSectorNode[],
  areaBy: HeatmapAreaBy,
  _colorBy: HeatmapColorBy,
  mode: "sector" | "stock" = "sector",
): EChartsTreemapNode[] {
  // value 严格 = amount(或流通市值), 这是面积; 颜色由 cell 的 changePercent 决定, 不受 amount 量级影响。
  void _colorBy
  return sectors.map((sector) => {
    const sectorValue = areaBy === "amount"
      ? (sector.amount || sector.children.reduce((s, c) => s + (c.amount ?? 0), 0))
      : (sector.circulatingMarketCap || sector.children.reduce((s, c) => s + (c.circulatingMarketCap ?? 0), 0))

    const c = colorForPct(sector.changePercent)

    // mode="sector"  (首屏): 板块本身当 leaf cell, 不展开 children, cell 染色 = 板块自身涨跌幅
    // mode="stock"   (钻入): 板块当 parent, children = 成分股 cell
    if (mode === "sector") {
      return {
        name: sector.name,
        value: Math.max(sectorValue, 1),
        _changePercent: sector.changePercent ?? 0,
        _amount: sector.amount ?? 0,
        _kind: "sector",
        _sectorNode: sector,  // 钻入时回传原始 sector 节点
        itemStyle: {
          color: c.bg,
          borderColor: "#e2e8f0",
          borderWidth: 2,
          gapWidth: 4,
        },
        upperLabel: { show: false },
        label: {
          show: true,
          color: c.fg,
          fontSize: 13,
          fontWeight: 700,
          lineHeight: 18,
          formatter: () => {
            return `{name|${sector.name}}\n{pct|${formatPct(sector.changePercent ?? 0)}}`
          },
          rich: {
            name: { color: c.fg, fontSize: 13, fontWeight: 700, lineHeight: 18 },
            pct:  { color: c.fg, fontSize: 11, fontWeight: 600, lineHeight: 16 },
          },
        },
      }
    }

    // mode === "stock" 钻入
    return {
      name: sector.name,
      value: Math.max(sectorValue, 1),
      _changePercent: sector.changePercent ?? 0,
      _amount: sector.amount ?? 0,
      _kind: "sector",
      itemStyle: {
        color: c.bg,
        // 父节点 (行业/概念/风格 板块) 之间需要明显 margin. 浅灰底 + 细白边
        borderColor: "#e2e8f0",
        borderWidth: 2,
        gapWidth: 4,
        // treemap cell 的内部 padding, 让 upperLabel 不贴边
        padding: [18, 4, 4, 4],
      },
      // 父节点 (行业/概念/风格 板块) 顶部 upperLabel: 显示板块名 + 涨跌幅.
      // 字号小一些, 在 margin 之上, 避免压住 children.
      upperLabel: {
        show: true,
        height: 18,
        color: c.fg,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: "rgba(255,255,255,0.92)",
        padding: [2, 6, 2, 6],
        formatter: () => {
          return `{name|${sector.name}} {pct|${formatPct(sector.changePercent ?? 0)}}`
        },
        rich: {
          name: { color: c.fg, fontSize: 11, fontWeight: 700, lineHeight: 14 },
          pct:  { color: c.fg, fontSize: 10, fontWeight: 600, lineHeight: 14 },
        },
      },
      label: {
        show: false,  // 父节点自己不显示 label (children cell 才有 label)
      },
      children: sector.children.map((stock) => {
        const cellValue = areaBy === "amount"
          ? (stock.amount ?? 0)
          : (stock.circulatingMarketCap ?? stock.totalMarketCap ?? stock.amount ?? 0)
        const cs = colorForPct(stock.changePercent)
        return {
          name: stockName(stock),
          value: Math.max(cellValue, 1),
          _changePercent: stock.changePercent ?? 0,
          _kind: "stock",
          itemStyle: {
            color: cs.bg,
            borderColor: "#ffffff",
            borderWidth: 0,
            gapWidth: 0.5,
          },
          upperLabel: { show: false },
          label: {
            show: true,
            color: cs.fg,
            fontSize: 12,
            fontWeight: 600,
            lineHeight: 16,
            formatter: () => {
              return `{name|${stockName(stock)}}\n{pct|${formatPct(stock.changePercent)}}`
            },
            rich: {
              name: { color: cs.fg, fontSize: 12, fontWeight: 700, lineHeight: 16 },
              pct:  { color: cs.fg, fontSize: 11, fontWeight: 600, lineHeight: 14 },
            },
          },
        }
      }),
    }
  })
}

/**
 * 找到 series click 事件 params.data 命中的 cell 在我们的模型里的元数据
 * (ECharts 会在 series 内部 normalize, 不会保留我们挂的 __kind/__meta,
 *  所以这里用 sector.children 的内存引用匹配。)
 */
function resolveClickMeta(
  params: any,
  sectors: HeatmapSectorNode[],
): { kind: "industry" | "stock"; sector: HeatmapSectorNode; stock?: StockHeatmapItem } | null {
  const data = params?.data
  if (!data) return null
  const name: string = data.name
  // 首屏 sector mode: cell 是 sector 自己, _sectorNode 挂在 data 上
  if (data._sectorNode) {
    return { kind: "industry", sector: data._sectorNode as HeatmapSectorNode }
  }
  // 钻入 stock mode: cell 是个股, 通过 treePath 找上层 sector
  const treePath: Array<{ name: string }> = params.treePathInfo || []
  const leafSectorName = treePath.length > 1 ? treePath[treePath.length - 2]?.name : name
  const sector = sectors.find((s) => s.name === leafSectorName || s.name === name)
  if (!sector) return null
  const stock = sector.children.find((c) => stockName(c) === name)
  if (stock) return { kind: "stock", sector, stock }
  if (sector.name === name) return { kind: "industry", sector }
  return null
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export function SectorHeatmap({ data, loading, onRefresh, autoRefresh, onAutoRefreshChange, kind, onKindChange }: Props) {
  // eslint-disable-next-line no-console
  console.log("[SectorHeatmap] render", {
    hasData: !!data,
    itemCount: data?.items?.length || 0,
  })
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("market")
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const [areaBy, setAreaBy] = useState<HeatmapAreaBy>("amount")
  const [colorBy, setColorBy] = useState<HeatmapColorBy>("changePercent")
  const [sortBy, setSortBy] = useState<HeatmapSortBy>("changePercent")
  const [quickFilter, setQuickFilter] = useState<HeatmapQuickFilter | "all">("all")
  const [keyword, setKeyword] = useState("")

  const sectors = useMemo(() => data?.items || [], [data])
  const filtered = useMemo(
    () => buildFilteredData(sectors, keyword, quickFilter, sortBy),
    [sectors, keyword, quickFilter, sortBy],
  )
  const activeSector = useMemo(
    () => filtered.find((sector) => sector.sectorCode === selectedSector) ?? null,
    [filtered, selectedSector],
  )

  const treemapData = useMemo(() => {
    if (viewMode === "sector" && activeSector) {
      // 钻入行业: 把单个 sector 当作 root, 让 ECharts 用一级布局切个股
      const wrapped: HeatmapSectorNode = { ...activeSector, value: activeSector.value || activeSector.amount || 1 }
      return buildTreemap([wrapped], areaBy, colorBy, "stock")
    }
    // 首屏: sector 当 leaf cell, 不展开成分股
    return buildTreemap(filtered, areaBy, colorBy, "sector")
  }, [filtered, activeSector, viewMode, areaBy, colorBy])

  // 实例化 + resize
  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    // eslint-disable-next-line no-console
    console.log("[SectorHeatmap] chart init", {
      domW: chartRef.current.clientWidth,
      domH: chartRef.current.clientHeight,
    })

    // ResizeObserver 兜底: 父级 flex chain 高度变化时主动 resize
    const ro = new ResizeObserver(() => {
      // eslint-disable-next-line no-console
      console.log("[SectorHeatmap] resize", {
        w: chartRef.current?.clientWidth,
        h: chartRef.current?.clientHeight,
      })
      chart.resize()
    })
    ro.observe(chartRef.current)

    const handleResize = () => chart.resize()
    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
      ro.disconnect()
      chart.dispose()
      instanceRef.current = null
    }
  }, [])

  // 配置变更 -> setOption
  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    if (treemapData.length === 0) return

    // eslint-disable-next-line no-console
    console.log("[SectorHeatmap] setOption", {
      viewMode,
      sectorCount: treemapData.length,
      totalChildren: treemapData.reduce((s, x) => s + (x.children?.length || 0), 0),
      domSize: { w: chart.getWidth(), h: chart.getHeight() },
      sample: treemapData[0],
    })

    chart.setOption({
      backgroundColor: "transparent",
      animationDurationUpdate: 600,
      tooltip: {
        trigger: "item",
        formatter: (info: any) => {
          const meta = resolveClickMeta(info, filtered)
          if (!meta) return ""
          if (meta.kind === "stock" && meta.stock) {
            const s = meta.stock
            return [
              `<div style="font-weight:700;margin-bottom:6px">${stockName(s)} <span style="font-family:ui-monospace,monospace;color:#64748b">· ${s.code}</span></div>`,
              `<div>价格：${s.latestPrice != null ? Number(s.latestPrice).toFixed(2) : "—"}</div>`,
              `<div>涨跌幅：${formatPct(s.changePercent)}</div>`,
              `<div>成交额：${formatAmount(s.amount)}</div>`,
              `<div>换手率：${formatPct(s.turnoverRate)}</div>`,
              `<div>流通市值：${formatAmount(s.circulatingMarketCap)}</div>`,
              `<div>主力净流入：${formatAmount(s.mainNetInflow)}</div>`,
              `<div>涨速：${formatPct(s.speed)}</div>`,
              `<div>连板数：${s.limitStreak ?? "—"}</div>`,
              `<div>封单金额：${formatAmount(s.boardSealedAmount)}</div>`,
              `<div>概念：${s.conceptTags?.length ? s.conceptTags.join(" / ") : "—"}</div>`,
            ].join("")
          }
          const sec = meta.sector
          return [
            `<div style="font-weight:700;margin-bottom:6px">${sec.name}</div>`,
            `<div>成分股：${sec.stockCount}</div>`,
            `<div>板块涨跌幅：${formatPct(sec.changePercent)}</div>`,
            `<div>成交额：${formatAmount(sec.amount)}</div>`,
            `<div>主力净流入：${formatAmount(sec.mainNetInflow)}</div>`,
            `<div>涨停数：${sec.limitUpCount}</div>`,
            `<div>换手率(均)：${formatPct(sec.turnoverRateAvg)}</div>`,
            `<div style="margin-top:6px;color:#64748b">点击进入行业内部</div>`,
          ].join("")
        },
      },
      // 与 demo 一致的最简配置, 仅多给 cell 染色
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          animationDurationUpdate: 400,
          // 父节点 (行业/概念/风格 板块) 之间 + 跟外边界的间距.
          // 浅灰底 + 6px 间距, 不同板块之间有明显 margin.
          nodeGap: 6,
          nodePadding: 2,
          // 用 callback formatter, 从原始 data 上读 changePercent / amount 自己拼字符串
          label: {
            show: true,
            // 兜底: series-level 颜色 + 字号. 每个 cell 自身的 label.rich 会覆盖 name/pct 颜色.
            color: "#fff",
            fontSize: 12,
            lineHeight: 16,
          },
          // 父节点 (行业/概念/风格) 顶部标签: 显示板块名 + 涨跌幅.
          // node-level upperLabel 会覆盖这个全局配置.
          upperLabel: {
            show: true,
            height: 24,
            backgroundColor: "rgba(255,255,255,0.85)",
            color: "#0f172a",
            fontSize: 13,
            fontWeight: 700,
            padding: [4, 6, 4, 6],
          },
          data: treemapData,
        },
      ],
    })
    chart.resize()
  }, [treemapData, viewMode, filtered])

  // 点击行业 -> 钻入
  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    const handler = (params: any) => {
      // 首屏 (viewMode=market): 点击 sector cell 钻入成分股
      if (viewMode === "market") {
        const meta = resolveClickMeta(params, filtered)
        if (meta?.kind === "industry" && meta.sector) {
          setSelectedSector(meta.sector.sectorCode)
          setViewMode("sector")
        }
        return
      }
      // 钻入视图 (viewMode=sector): 板块当 parent, 个股 cell 直接点 (无钻入行为)
    }
    chart.on("click", handler)
    return () => {
      chart.off("click", handler)
    }
  }, [viewMode, filtered])

  // 派生统计
  const statTotal = useMemo(() => filtered.reduce((sum, sector) => sum + sector.children.length, 0), [filtered])
  const limitUpTotal = useMemo(() => filtered.reduce((sum, sector) => sum + sector.limitUpCount, 0), [filtered])

  return (
    <Card className="flex h-full min-h-0 flex-col rounded-xl border-slate-200/60 bg-white text-slate-800">
      <CardContent className="flex min-h-0 flex-1 flex-col gap-1.5 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500 mr-1">板块</span>
          {KIND_OPTIONS.map((opt) => (
            <FilterChip
              key={opt.value}
              active={kind === opt.value}
              label={opt.label}
              onClick={() => onKindChange(opt.value)}
            />
          ))}
          <span className="mx-2 h-4 w-px bg-slate-200" />
          <FilterChip active={quickFilter === "all"} label="全部" onClick={() => setQuickFilter("all")} />
          <FilterChip
            active={quickFilter === "limitUp"}
            label="只看涨停"
            onClick={() => setQuickFilter(quickFilter === "limitUp" ? "all" : "limitUp")}
          />
          <FilterChip
            active={quickFilter === "amountTop100"}
            label="只看成交额前 100"
            onClick={() => setQuickFilter(quickFilter === "amountTop100" ? "all" : "amountTop100")}
          />
          <FilterChip
            active={quickFilter === "turnoverTop100"}
            label="只看高换手率"
            onClick={() => setQuickFilter(quickFilter === "turnoverTop100" ? "all" : "turnoverTop100")}
          />
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => onAutoRefreshChange(!autoRefresh)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition",
                autoRefresh
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-slate-200 bg-white text-slate-500 hover:border-slate-300",
              )}
            >
              <Zap className="size-3.5" />
              实时刷新
            </button>
            {viewMode === "sector" ? (
              <Button size="sm" variant="outline" onClick={() => { setViewMode("market"); setSelectedSector(null) }}>
                <ArrowLeft className="mr-1 size-3.5" />返回全市场
              </Button>
            ) : null}
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading}>
              <RefreshCw className={cn("mr-1 size-3.5", loading && "animate-spin")} />
              {loading ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-1.5">
          <div className="relative h-full min-h-0 overflow-hidden rounded-lg bg-white">
            <div ref={chartRef} className="h-full w-full" />
            {treemapData.length === 0 ? (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">
                {loading ? "热力图加载中…" : "当前筛选条件下暂无数据"}
              </div>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function FilterChip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition",
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-800",
      )}
    >
      {label}
    </button>
  )
}

function SelectBar({
  value,
  options,
  onChange,
}: {
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-slate-400"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  )
}
