/**
 * 市场热力图（行业 / 概念，同花顺式 ECharts Treemap）
 *
 * - 一级: 行业按 成交额(amount) 切分面积
 * - 二级 (钻入后): 行业内个股按 成交额 切分面积
 * - 颜色: 涨跌幅 4 档 (red/green) + 灰色中性
 * - 文字: 行业 cell 显示 名称 + 涨跌幅, 个股 cell 显示 名称 + 涨跌幅
 * - 交互:
 *   - 鼠标悬停: 弹出 tooltip
 *   - 点击行业: 钻入 sector 视图
 *   - "返回全市场" 按钮: 回到 market 视图
 *   - 实时刷新 / 快捷筛选
 *
 * 从 industry-application 版本 fork而来，移除了 Card 包装和"风格"tab。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, RefreshCw, Zap } from "lucide-react"
import * as echarts from "echarts/core"
import { TreemapChart } from "echarts/charts"
import { TooltipComponent, TitleComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([TreemapChart, TooltipComponent, TitleComponent, CanvasRenderer])

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { notification } from "@/components/ui/notification"
import { cn } from "@/lib/utils"
import { fetchIndustryConstituentsByCode } from "@/lib/api"
import type { IndustryConstituentRow } from "@/lib/api"
import { StockDetailDialog } from "@/components/stock-detail-dialog"

import type {
  HeatmapAreaBy,
  HeatmapColorBy,
  HeatmapQuickFilter,
  HeatmapSectorNode,
  HeatmapSortBy,
  MarketHeatmapResponse,
  StockHeatmapItem,
} from "@/views/industry-application/lib/types"

interface Props {
  data: MarketHeatmapResponse | null
  loading: boolean
  onRefresh: () => void
  autoRefresh: boolean
  onAutoRefreshChange: (value: boolean) => void
  kind: "industries" | "concepts"
  onKindChange: (kind: "industries" | "concepts") => void
}

type ViewMode = "market" | "sector"

// ---------------------------------------------------------------------------
// 常量配置
// ---------------------------------------------------------------------------

const KIND_OPTIONS: Array<{ value: "industries" | "concepts"; label: string }> = [
  { value: "industries", label: "行业" },
  { value: "concepts", label: "概念" },
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

// ---------------------------------------------------------------------------
// 行业成分股快照 -> StockHeatmapItem 适配
// ---------------------------------------------------------------------------

const _AMOUNT_RE = /^\s*([-+]?\d+(?:\.\d+)?)\s*([亿万千]?)\s*$/

function parseAmountToYuan(raw: number | string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "" || raw === "--") return null
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null
  const s = String(raw).trim()
  const m = _AMOUNT_RE.exec(s)
  if (!m) {
    const n = Number(s)
    return Number.isFinite(n) ? n : null
  }
  const num = Number(m[1])
  const unit = m[2]
  if (unit === "亿") return num * 1e8
  if (unit === "万") return num * 1e4
  if (unit === "千") return num * 1e3
  return num
}

function parseNumberField(raw: number | string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "" || raw === "--") return null
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null
  const n = Number(String(raw).replace(/[%\s]/g, ""))
  return Number.isFinite(n) ? n : null
}

function isLimitUpByRow(row: IndustryConstituentRow): boolean {
  const zdf = parseNumberField(row["涨跌幅(%)"])
  return zdf !== null && zdf >= 9.7
}

function constituentRowToStockItem(
  row: IndustryConstituentRow,
  sector: HeatmapSectorNode,
): StockHeatmapItem {
  const code = (row["代码"] || "").toString().padStart(6, "0")
  const market: "sh" | "sz" | "bj" = code.startsWith("6") || code.startsWith("9") ? "sh" : code.startsWith("8") ? "bj" : "sz"
  const amount = parseAmountToYuan(row["成交额"])
  const latestPrice = parseNumberField(row["现价"])
  const volume = amount != null && latestPrice != null && latestPrice > 0
    ? amount / latestPrice
    : null
  return {
    code,
    name: row["名称"] || code,
    fullCode: `${market}${code}`,
    latestPrice,
    changePercent: parseNumberField(row["涨跌幅(%)"]),
    amount,
    volume,
    turnoverRate: parseNumberField(row["换手(%)"]),
    circulatingMarketCap: parseAmountToYuan(row["流通市值"]),
    totalMarketCap: null,
    mainNetInflow: null,
    speed: parseNumberField(row["涨速(%)"]),
    limitStreak: null,
    boardSealedAmount: null,
    conceptTags: [],
    isLimitUp: isLimitUpByRow(row),
    sectorCode: sector.sectorCode,
    sectorName: sector.name,
  }
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
    .filter((sector) => {
      if (sector.children.length > 0) return true
      const hasAmount = (sector.amount ?? sector.value ?? 0) > 0
      const hasChange = sector.changePercent != null
      return hasAmount || hasChange
    })
}

// ---------------------------------------------------------------------------
// 构造 treemap data
// ---------------------------------------------------------------------------

function compressAreaValue(raw: number | null | undefined): number {
  if (!Number.isFinite(raw) || (raw as number) <= 0) return 1
  return Math.sqrt(raw as number)
}

type EChartsTreemapNode = {
  name: string
  value: number
  itemStyle?: { color?: string; borderColor?: string; borderWidth?: number; gapWidth?: number }
  upperLabel?: { show?: boolean; height?: number; color?: string; fontSize?: number; fontWeight?: string | number; backgroundColor?: string; padding?: number[]; borderRadius?: number }
  label?: { show?: boolean; color?: string; fontSize?: number; formatter?: string | (() => string); position?: string; padding?: number[]; rich?: Record<string, unknown> }
  children?: EChartsTreemapNode[]
}

type HeatmapBand =
  | "upExtreme" | "upStrong" | "upMid" | "upLight" | "flat"
  | "downLight" | "downMid" | "downStrong" | "downExtreme"

interface Palette {
  upExtreme: { bg: string; fg: string }
  upStrong:  { bg: string; fg: string }
  upMid:     { bg: string; fg: string }
  upLight:   { bg: string; fg: string }
  flat:      { bg: string; fg: string }
  downLight: { bg: string; fg: string }
  downMid:   { bg: string; fg: string }
  downStrong:  { bg: string; fg: string }
  downExtreme: { bg: string; fg: string }
}

const SECTOR_PALETTE: Palette = {
  upExtreme:   { bg: "#DC2626", fg: "#ffffff" },
  upStrong:    { bg: "#F87171", fg: "#7F1D1D" },
  upLight:     { bg: "#FECACA", fg: "#991B1B" },
  upMid:       { bg: "#F87171", fg: "#7F1D1D" },
  flat:        { bg: "#F1F5F9", fg: "#475569" },
  downLight:   { bg: "#DCFCE7", fg: "#14532D" },
  downMid:     { bg: "#86EFAC", fg: "#14532D" },
  downStrong:  { bg: "#86EFAC", fg: "#14532D" },
  downExtreme: { bg: "#15803D", fg: "#ffffff" },
}

const STOCK_PALETTE: Palette = {
  upExtreme:   { bg: "#B91C1C", fg: "#ffffff" },
  upStrong:    { bg: "#DC2626", fg: "#ffffff" },
  upMid:       { bg: "#EF4444", fg: "#ffffff" },
  upLight:     { bg: "#FCA5A5", fg: "#7F1D1D" },
  flat:        { bg: "#E2E8F0", fg: "#475569" },
  downLight:   { bg: "#86EFAC", fg: "#14532D" },
  downMid:     { bg: "#22C55E", fg: "#ffffff" },
  downStrong:  { bg: "#15803D", fg: "#ffffff" },
  downExtreme: { bg: "#14532D", fg: "#ffffff" },
}

function sectorBandForPct(pct: number | null | undefined): HeatmapBand {
  if (pct == null || !Number.isFinite(pct) || Math.abs(pct) > 50) return "flat"
  if (pct >= 5) return "upExtreme"
  if (pct >= 2) return "upStrong"
  if (pct >= 0.5) return "upLight"
  if (pct <= -5) return "downExtreme"
  if (pct <= -2) return "downStrong"
  if (pct <= -0.5) return "downLight"
  return "flat"
}

function stockBandForPct(pct: number | null | undefined): HeatmapBand {
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

function paletteColor(palette: Palette, pct: number | null | undefined): { bg: string; fg: string } {
  const band = palette === SECTOR_PALETTE ? sectorBandForPct(pct) : stockBandForPct(pct)
  return palette[band]
}

function sectorColorForPct(pct: number | null | undefined): { bg: string; fg: string } {
  return paletteColor(SECTOR_PALETTE, pct)
}

function stockColorForPct(pct: number | null | undefined): { bg: string; fg: string } {
  return paletteColor(STOCK_PALETTE, pct)
}

function buildTreemap(
  sectors: HeatmapSectorNode[],
  areaBy: HeatmapAreaBy,
  _colorBy: HeatmapColorBy,
  mode: "sector" | "stock" = "sector",
): EChartsTreemapNode[] {
  void _colorBy

  const sectorAreaRaw = (s: HeatmapSectorNode): number => {
    if (areaBy === "volume") {
      return s.children.reduce((sum, c) => sum + (c.volume ?? 0), 0)
    }
    const sectorLevel =
      areaBy === "amount" ? s.amount : (s.circulatingMarketCap ?? 0)
    const fallbackSum = s.children.reduce(
      (sum, c) => sum + (areaBy === "amount" ? (c.amount ?? 0) : (c.circulatingMarketCap ?? 0)),
      0,
    )
    return sectorLevel || fallbackSum
  }

  const stockAreaRaw = (stock: StockHeatmapItem): number => {
    if (areaBy === "volume") return stock.volume ?? 0
    if (areaBy === "amount") return stock.amount ?? 0
    return stock.circulatingMarketCap ?? stock.totalMarketCap ?? stock.amount ?? 0
  }

  const sectorRaws = sectors.map(sectorAreaRaw)

  return sectors.map((sector, idx) => {
    const sectorValue = sectorRaws[idx]
    const c = sectorColorForPct(sector.changePercent)

    if (mode === "sector") {
      return {
        name: sector.name,
        value: Math.max(compressAreaValue(sectorValue), 1),
        _changePercent: sector.changePercent ?? 0,
        _amount: sector.amount ?? 0,
        _kind: "sector",
        _sectorNode: sector,
        itemStyle: {
          color: c.bg,
          borderColor: "#ffffff",
          borderWidth: 1,
          gapWidth: 0,
        },
        upperLabel: { show: false },
        label: {
          show: true,
          color: c.fg,
          fontSize: 13,
          fontWeight: 700,
          lineHeight: 18,
          formatter: () => {
            return `{name|${sector.name}}\n{pct|${formatPct(sector.changePercent ?? 0)}}\n{amt|${formatAmount(sector.amount)}}`
          },
          rich: {
            name: { color: c.fg, fontSize: 13, fontWeight: 700, lineHeight: 18 },
            pct:  { color: c.fg, fontSize: 11, fontWeight: 600, lineHeight: 16 },
            amt:  { color: c.fg, fontSize: 10, fontWeight: 500, lineHeight: 14 },
          },
        },
      }
    }

    const stockRaws = sector.children.map(stockAreaRaw)
    const stockSqrt = stockRaws.map((v) => compressAreaValue(v))
    const sumSqrt = stockSqrt.reduce((s, v) => s + v, 0)
    void sumSqrt
    const parentSqrt = compressAreaValue(sectorValue)

    return {
      name: sector.name,
      value: Math.max(parentSqrt, 1),
      _changePercent: sector.changePercent ?? 0,
      _amount: sector.amount ?? 0,
      _kind: "sector",
      itemStyle: {
        color: c.bg,
        borderColor: "#ffffff",
        borderWidth: 1,
        gapWidth: 2,
        padding: [18, 4, 4, 4],
      },
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
      label: { show: false },
      children: sector.children.map((stock, ci) => {
        const cellValue = stockRaws[ci]
        const cs = stockColorForPct(stock.changePercent)
        return {
          name: stockName(stock),
          value: Math.max(stockSqrt[ci], 1),
          _changePercent: stock.changePercent ?? 0,
          _kind: "stock",
          _rawValue: cellValue,
          _stock: stock,
          _parentSector: sector,
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

function resolveClickMeta(
  params: any,
  sectors: HeatmapSectorNode[],
): { kind: "industry" | "stock"; sector: HeatmapSectorNode; stock?: StockHeatmapItem } | null {
  const data = params?.data
  if (!data) return null
  if (data._sectorNode) {
    return { kind: "industry", sector: data._sectorNode as HeatmapSectorNode }
  }
  if (data._stock) {
    return {
      kind: "stock",
      sector: data._parentSector as HeatmapSectorNode,
      stock: data._stock as StockHeatmapItem,
    }
  }
  const treePath: Array<{ name: string }> = params.treePathInfo || []
  const leafSectorName = treePath.length > 1 ? treePath[treePath.length - 2]?.name : data.name
  const sector = sectors.find((s) => s.name === leafSectorName || s.name === data.name)
  if (!sector) return null
  const stock = sector.children.find((c) => stockName(c) === data.name)
  if (stock) return { kind: "stock", sector, stock }
  if (sector.name === data.name) return { kind: "industry", sector }
  return null
}

// ---------------------------------------------------------------------------
// 主组件 (无 Card 包装)
// ---------------------------------------------------------------------------

export function IndustryHeatmap({ data, loading, onRefresh, autoRefresh, onAutoRefreshChange, kind, onKindChange }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("market")
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const [areaBy] = useState<HeatmapAreaBy>("circulatingMarketCap")
  const [colorBy] = useState<HeatmapColorBy>("changePercent")
  const [sortBy] = useState<HeatmapSortBy>("changePercent")
  const [quickFilter, setQuickFilter] = useState<HeatmapQuickFilter | "all">("all")

  void sortBy // used in buildFilteredData dep array

  const [stockDialogOpen, setStockDialogOpen] = useState(false)
  const [stockDialogInfo, setStockDialogInfo] = useState<{
    code: string
    name: string
    industryName: string | null
  } | null>(null)

  const sectors = useMemo(() => data?.items || [], [data])
  const filtered = useMemo(
    () => buildFilteredData(sectors, "", quickFilter, sortBy),
    [sectors, quickFilter, sortBy],
  )
  const activeSector = useMemo(
    () => filtered.find((sector) => sector.sectorCode === selectedSector) ?? null,
    [filtered, selectedSector],
  )

  const [drillDownCache, setDrillDownCache] = useState<Record<string, StockHeatmapItem[]>>({})
  const [drillDownLoading, setDrillDownLoading] = useState(false)
  const drillDownKey = selectedSector ?? ""

  const loadDrillDown = useCallback(async (code: string, sector: HeatmapSectorNode) => {
    setDrillDownLoading(true)
    try {
      const resp = await fetchIndustryConstituentsByCode(code)
      const rows = Array.isArray(resp.rows) ? resp.rows : []
      const items = rows
        .filter((row): row is IndustryConstituentRow => !!row && !!row["代码"])
        .map((row) => constituentRowToStockItem(row, sector))
      setDrillDownCache((prev) => ({ ...prev, [code]: items }))
    } catch (err) {
      notification.danger({
        title: `加载 ${sector.name} 成分股失败`,
        description: err instanceof Error ? err.message : "未知错误",
      })
      setDrillDownCache((prev) => ({ ...prev, [code]: [] }))
    } finally {
      setDrillDownLoading(false)
    }
  }, [])

  useEffect(() => {
    if (viewMode !== "sector" || !activeSector) return
    const code = activeSector.sectorCode
    if (!code) return
    if (drillDownCache[code]) return
    void loadDrillDown(code, activeSector)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, activeSector?.sectorCode])

  const drillDownStocks = drillDownCache[drillDownKey] ?? null

  const treemapData = useMemo(() => {
    if (viewMode === "sector" && activeSector) {
      const wrapped: HeatmapSectorNode = {
        ...activeSector,
        value: activeSector.value || activeSector.amount || 1,
        children: drillDownStocks ?? activeSector.children ?? [],
      }
      return buildTreemap([wrapped], areaBy, colorBy, "stock")
    }
    return buildTreemap(filtered, areaBy, colorBy, "sector")
  }, [filtered, activeSector, viewMode, areaBy, colorBy, drillDownStocks])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    let resizeTimer: number | null = null
    const ro = new ResizeObserver(() => {
      if (resizeTimer != null) window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => chart.resize(), 80)
    })
    ro.observe(chartRef.current)

    const handleResize = () => chart.resize()
    window.addEventListener("resize", handleResize)

    return () => {
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
    if (treemapData.length === 0) return

    chart.setOption({
      backgroundColor: "#ffffff",
      animation: false,
      tooltip: {
        trigger: "item",
        transitionDuration: 0,
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
            `<div style="font-weight:700;margin-bottom:6px">${sec.name} <span style="font-family:ui-monospace,monospace;color:#64748b">· ${sec.sectorCode}</span></div>`,
            `<div>板块涨跌幅：<b>${formatPct(sec.changePercent)}</b></div>`,
            `<div>流通市值：<b>${formatAmount(sec.circulatingMarketCap)}</b></div>`,
            `<div>成交额：<b>${formatAmount(sec.amount)}</b></div>`,
            `<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #cbd5e1">成分股：${sec.stockCount} &nbsp;·&nbsp; 涨停数：${sec.limitUpCount} &nbsp;·&nbsp; 换手率(均)：${formatPct(sec.turnoverRateAvg)}</div>`,
            `<div>主力净流入：${formatAmount(sec.mainNetInflow)}</div>`,
            `<div style="margin-top:6px;color:#64748b">点击进入行业内部</div>`,
          ].join("")
        },
      },
      series: [
        {
          type: "treemap",
          left: 0,
          top: 0,
          right: 0,
          bottom: 0,
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          animationDuration: 0,
          animationDurationUpdate: 0,
          animationEasing: "linear",
          nodeGap: 2,
          nodePadding: 1,
          label: {
            show: true,
            color: "#fff",
            fontSize: 12,
            lineHeight: 16,
          },
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
  }, [treemapData, viewMode, filtered])

  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    const handler = (params: any) => {
      const meta = resolveClickMeta(params, filtered)
      if (!meta) return
      if (meta.kind === "stock" && meta.stock) {
        const s = meta.stock
        setStockDialogInfo({
          code: s.code,
          name: s.name,
          industryName: meta.sector?.name ?? null,
        })
        setStockDialogOpen(true)
        return
      }
      if (viewMode === "market" && meta.kind === "industry" && meta.sector) {
        setSelectedSector(meta.sector.sectorCode)
        setViewMode("sector")
      }
    }
    chart.on("click", handler)
    return () => {
      chart.off("click", handler)
    }
  }, [viewMode, filtered])

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* 头部 */}
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
          label="成交额前100"
          onClick={() => setQuickFilter(quickFilter === "amountTop100" ? "all" : "amountTop100")}
        />
        <FilterChip
          active={quickFilter === "turnoverTop100"}
          label="高换手率"
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
          {viewMode === "sector" && activeSector ? (
            <div className="inline-flex items-center gap-2">
              <Badge variant="secondary" className="border-slate-200 bg-secondary text-slate-700">
                {activeSector.name} · {activeSector.sectorCode}
              </Badge>
              {drillDownStocks ? (
                <span className="text-xs text-slate-500">
                  {drillDownStocks.length} 只成分股
                </span>
              ) : null}
              <Button size="sm" variant="secondary" onClick={() => { setViewMode("market"); setSelectedSector(null) }}>
                <ArrowLeft className="mr-1 size-3.5" />返回
              </Button>
            </div>
          ) : null}
          <Button size="sm" variant="secondary" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={cn("mr-1 size-3.5", loading && "animate-spin")} />
            {loading ? "刷新中" : "Refresh"}
          </Button>
        </div>
      </div>

      {/* 图表 */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-white">
        <div ref={chartRef} className="h-full w-full bg-white" />
        {treemapData.length === 0 ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">
            {loading
              ? "热力图加载中…"
              : drillDownLoading
                ? `${activeSector?.name ?? "行业"} 成分股加载中…`
                : viewMode === "sector" && drillDownStocks && drillDownStocks.length === 0
                  ? `${activeSector?.name ?? "该行业"} 暂无成分股数据`
                  : "当前筛选条件下暂无数据"}
          </div>
        ) : null}
        {viewMode === "sector" && drillDownLoading ? (
          <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-slate-900/70 px-3 py-1 text-xs text-white shadow">
            {activeSector?.name ?? "行业"} 成分股加载中…
          </div>
        ) : null}
      </div>

      <StockDetailDialog
        open={stockDialogOpen}
        onOpenChange={setStockDialogOpen}
        stockCode={stockDialogInfo?.code ?? null}
        stockName={stockDialogInfo?.name ?? null}
        industryName={stockDialogInfo?.industryName ?? null}
      />
    </div>
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