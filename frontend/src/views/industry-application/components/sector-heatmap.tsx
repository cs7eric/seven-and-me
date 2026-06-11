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
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
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
import { notification } from "@/components/ui/notification"
import { cn } from "@/lib/utils"
import { fetchIndustryConstituentsByCode } from "@/lib/api"
import type { IndustryConstituentRow } from "@/lib/api"

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
  { value: "circulatingMarketCap", label: "面积: 流通市值" },
  { value: "amount", label: "面积: 成交额" },
  { value: "volume", label: "面积: 成交量" },
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

// ---------------------------------------------------------------------------
// 行业成分股快照 -> StockHeatmapItem 适配
//
// 数据源: GET /api/stock-chart/ths-industry/constituents-by-code?code=881xxx
// 14 列 pandas 落盘, 成交额 / 流通市值 是带中文单位的字符串 (e.g. "5.60亿" / "1234万")
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
  const amount = parseAmountToYuan(row["成交额"])    // 元
  const latestPrice = parseNumberField(row["现价"])  // 元/股
  // 成交量 (股) = 成交额 (元) / 现价 (元/股); 现价缺失就拿不到
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
    // 过滤: 首屏把 sector 当 leaf cell, 只要 sector 自身有数据 (amount/value/changePercent)
    // 就保留; 即便 children 为空 (行业 / 风格板块常常没落盘成分股, 走纯板块视图) 也展示.
    // 钻入 view 完全走 activeSector, 走不到这里, 不需要按 children 兜底.
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

/**
 * 把成交额 / 成交量 / 流通市值 这种长尾数值压缩成 treemap value, 让首屏 90 行业
 * + 钻入的成分股**既不会让大票吃掉整个 cell, 也不会让小票全部同样大小**.
 *
 * 策略: Math.sqrt(raw) 开方压缩.
 * - 7.18亿  = 7.18e8 -> 26,795
 * - 2231亿 = 2.231e11 -> 472,343      面积比 17.6, 线性比 4.2 (大板块明显大, 小板块可见)
 * - 0.01亿 (成分股) = 1e6 -> 1,000     30亿 = 3e9 -> 54,772      面积比 54.8, 线性比 7.4
 *
 * 比 log/min-max ([1,100]) 更柔和 — 后者会让最大 cell 比最小 cell 大 100x 面积 (10x 线性),
 * 视觉上跟 raw 几乎没差别; sqrt 给的是 17x 面积 / 4x 线性, "大板块明显更大, 小板块看得到".
 */
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

/**
 * 两套独立的涨跌色卡: 行业用蓝/橙 (跟个股的红/绿**视觉上完全区分**),
 * 个股用东方财富/同花顺风格的红/绿.
 *
 * 色板分级 (更明显的差异, 适合treemap):
 *   SECTOR_PALETTE — 行业 (波动小, 分级宽 ±0.5 / ±2 / ±5):
 *     upExtreme +5%↑     深蓝     downExtreme -5%↓    深橙
 *     upStrong  +2~5%    鲜蓝     downStrong  -2~-5%  鲜橙
 *     upLight   +0.5~2%  浅蓝     downLight   -0.5~-2% 浅橙
 *     flat      ±0.5%    浅灰
 *
 *   STOCK_PALETTE  — 个股 (波动大, 分级细 ±0.5 / ±2 / ±5 / ±10):
 *     upExtreme  +10%↑   涨停红    downExtreme -10%↓   跌停绿
 *     upStrong   +5~10%  深红      downStrong  -5~-10%  深绿
 *     upMid      +2~5%   鲜红      downMid     -2~-5%   鲜绿
 *     upLight    +0.5~2% 浅红      downLight   -0.5~-2% 浅绿
 *     flat       ±0.5%   浅灰
 *
 * 文字色按底色亮度选 — 浅底配深字 (可读性高), 深底配白字.
 */

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

/** 行业色板: 红/绿 (跟个股同色系, 但**饱和度低**让两层视觉区分), 4 档 (+flat) */
const SECTOR_PALETTE: Palette = {
  upExtreme:   { bg: "#DC2626", fg: "#ffffff" }, // 红 +5%↑
  upStrong:    { bg: "#F87171", fg: "#7F1D1D" }, // 浅红 +2~5%
  upLight:     { bg: "#FECACA", fg: "#991B1B" }, // 粉 +0.5~2%
  upMid:       { bg: "#F87171", fg: "#7F1D1D" }, // 同 upStrong (sector 不分 mid/strong)
  flat:        { bg: "#F1F5F9", fg: "#475569" }, // 浅灰 ±0.5%
  downLight:   { bg: "#DCFCE7", fg: "#14532D" }, // 浅绿 -0.5~-2%
  downMid:     { bg: "#86EFAC", fg: "#14532D" }, // 鲜绿 -2~-5%
  downStrong:  { bg: "#86EFAC", fg: "#14532D" }, // 同 downMid
  downExtreme: { bg: "#15803D", fg: "#ffffff" }, // 深绿 -5%↓
}

/** 个股色板: 红/绿, 5 档 (+flat), 跟 同花顺 / 东方财富 一致 (饱和度高, 跟行业的浅色区分) */
const STOCK_PALETTE: Palette = {
  upExtreme:   { bg: "#B91C1C", fg: "#ffffff" }, // 涨停红 +10%↑
  upStrong:    { bg: "#DC2626", fg: "#ffffff" }, // 深红 +5~10%
  upMid:       { bg: "#EF4444", fg: "#ffffff" }, // 鲜红 +2~5%
  upLight:     { bg: "#FCA5A5", fg: "#7F1D1D" }, // 浅红 +0.5~2%
  flat:        { bg: "#E2E8F0", fg: "#475569" }, // 浅灰 ±0.5%
  downLight:   { bg: "#86EFAC", fg: "#14532D" }, // 浅绿 -0.5~-2%
  downMid:     { bg: "#22C55E", fg: "#ffffff" }, // 鲜绿 -2~-5%
  downStrong:  { bg: "#15803D", fg: "#ffffff" }, // 深绿 -5~-10%
  downExtreme: { bg: "#14532D", fg: "#ffffff" }, // 跌停绿 -10%↓
}

/** 行业分级阈值 (更宽, 4 档 + flat): ±0.5 / ±2 / ±5 */
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

/** 个股分级阈值 (更细, 5 档 + flat): ±0.5 / ±2 / ±5 / ±10 */
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
  const isSector = palette === SECTOR_PALETTE
  const band = isSector ? sectorBandForPct(pct) : stockBandForPct(pct)
  return palette[band]
}

function colorForPct(pct: number | null | undefined): { bg: string; fg: string } {
  // 兼容旧调用: 默认走 STOCK_PALETTE (个股)
  return paletteColor(STOCK_PALETTE, pct)
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
  // value 严格 = amount/volume/流通市值, 这是面积; 颜色由 cell 的 changePercent 决定, 不受 amount 量级影响。
  // 单位: fetchMarketHeatmap 已经把 sector.amount / sector.circulatingMarketCap 从 亿 转成了 元,
  // 跟 StockHeatmapItem.amount (元) 同量级, 不需要再转换.
  void _colorBy

  const sectorAreaRaw = (s: HeatmapSectorNode): number => {
    if (areaBy === "volume") {
      // 成交量无行业级聚合, 直接累加 children
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

  // 首屏 (mode=sector): 90 个 sector 各自是 leaf cell, 用 sqrt 压缩,
  // 保留相对量级的同时让最大最小 cell 都不会太极端 (17x 面积比 / 4x 线性比).
  const sectorRaws = sectors.map(sectorAreaRaw)

  return sectors.map((sector, idx) => {
    const sectorValue = sectorRaws[idx]
    const c = sectorColorForPct(sector.changePercent)

    // mode="sector"  (首屏): 板块本身当 leaf cell, 不展开 children, cell 染色 = 板块自身涨跌幅
    if (mode === "sector") {
      return {
        name: sector.name,
        value: Math.max(compressAreaValue(sectorValue), 1),
        _changePercent: sector.changePercent ?? 0,
        _amount: sector.amount ?? 0,
        _kind: "sector",
        _sectorNode: sector,  // 钻入时回传原始 sector 节点
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
            // 三件套: 行业名 + 涨跌幅 + 成交额 (跟 tooltip 同口径, hover 前也能直接看到)
            // cell 太小自动只显示 name, ECharts 会截断; 大 cell 全部可见.
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

    // mode === "stock" 钻入: 单一 sector 当 parent, 内部 children = 成分股 cell.
    //
    // 策略: parent.value = sum(sqrt(children)), children = sqrt(raw) 各自.
    // - parent 跟 children 在同一 sqrt 量级, 面积分配自然合理
    // - 通信设备: parent=sqrt(2.231e11)=472343, 100只成分股 sum sqrt ≈ 1.2e6
    //   parent area = 472343/1.67e6 ≈ 28% (upperLabel 够显示)
    // - children 之间按 sqrt 比例 (54.8x 面积 / 7.4x 线性, 大票明显大但小票也可见)
    const stockRaws = sector.children.map(stockAreaRaw)
    const stockSqrt = stockRaws.map((v) => compressAreaValue(v))
    const sumSqrt = stockSqrt.reduce((s, v) => s + v, 0)
    const parentSqrt = compressAreaValue(sectorValue)

    return {
      name: sector.name,
      value: Math.max(parentSqrt, 1),
      _changePercent: sector.changePercent ?? 0,
      _amount: sector.amount ?? 0,
      _kind: "sector",
      itemStyle: {
        color: c.bg,
        // 父节点 (行业/概念/风格 板块) 之间需要明显 margin. 白边让 cell 之间透出画布白底.
        borderColor: "#ffffff",
        borderWidth: 1,
        gapWidth: 2,  // 钻入后, 父容器内部成分股 cell 之间的间距 (还原回去)
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
      children: sector.children.map((stock, ci) => {
        const cellValue = stockRaws[ci]
        const cs = stockColorForPct(stock.changePercent)
        return {
          name: stockName(stock),
          value: Math.max(stockSqrt[ci], 1),
          _changePercent: stock.changePercent ?? 0,
          _kind: "stock",
          _rawValue: cellValue,
          _stock: stock,             // 给 tooltip 直接拿, 不用 sector.children 找
          _parentSector: sector,     // tooltip 里需要 sector 信息
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
  // 钻入 stock mode: cell 上已经挂 _stock + _parentSector, 直接拿 (不用 sector.children 找,
  // 因为 sector.children 是旧数据, 钻入的 stocks 存在 drillDownStocks 里, sector.children 是 [])
  if (data._stock) {
    return {
      kind: "stock",
      sector: data._parentSector as HeatmapSectorNode,
      stock: data._stock as StockHeatmapItem,
    }
  }
  // fallback: 通过 treePath 找上层 sector (兼容老数据)
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
  const [areaBy, setAreaBy] = useState<HeatmapAreaBy>("circulatingMarketCap")
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

  // 钻入个股热力图: 按 sector code 缓存成分股快照, 避免重复请求
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

  // 钻入 + sector 变化时拉成分股; 已经缓存的就不再拉
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
      // 钻入行业: 把单个 sector 当作 root, children 用刚拉到的成分股快照
      const wrapped: HeatmapSectorNode = {
        ...activeSector,
        value: activeSector.value || activeSector.amount || 1,
        children: drillDownStocks ?? activeSector.children ?? [],
      }
      return buildTreemap([wrapped], areaBy, colorBy, "stock")
    }
    // 首屏: sector 当 leaf cell, 不展开成分股
    return buildTreemap(filtered, areaBy, colorBy, "sector")
  }, [filtered, activeSector, viewMode, areaBy, colorBy, drillDownStocks])

  // 实例化 + resize
  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    // ResizeObserver 兜底: 父级 flex chain 高度变化时主动 resize
    // debounce 一下避免 hover 期间被频繁触发, 打断 tooltip.
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

  // 配置变更 -> setOption
  // 注意: tooltip 的 formatter 闭包用 filtered, 但 filtered 已经通过 treemapData 间接进了 deps,
  // 不要把它放 deps 里 (会触发双重 setOption, 打断 hover 的 tooltip).
  // setOption 内不要调 chart.resize(), ResizeObserver 已经接管了 resize.
  // animationDurationUpdate 关掉, 否则 hover 期间动画会打断 tooltip 事件.
  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    if (treemapData.length === 0) return

    chart.setOption({
      backgroundColor: "#ffffff",
      // 全局动画也关掉 (treemap 内部默认 1000ms), 避免 hover 期间 chart 重绘打断 tooltip
      animation: false,
      tooltip: {
        trigger: "item",
        // 关掉 transition, 避免 tooltip 在动画期间被吃
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
      // 与 demo 一致的最简配置, 仅多给 cell 染色
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          // 关掉动画: hover 期间 chart 重绘如果带 animation 会打断 tooltip 事件,
          // 表现就是 tooltip 一会有一会没. treemap 默认 1000ms, 这里直接置 0.
          animationDuration: 0,
          animationDurationUpdate: 0,
          animationEasing: "linear",
          // 板块之间 + 跟外边界的间距. 全部用白底配白边, 杜绝任何灰底漏出来.
          nodeGap: 2,
          nodePadding: 1,
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
    // 注意: 这里不调 chart.resize(), ResizeObserver 已经接管了大小变化,
    // 每次 setOption 都 resize 会在 hover 期间打断 tooltip 事件, 导致 tooltip 一会有一会没.
    // 注意: deps 只放 treemapData + viewMode. filtered 已经通过 treemapData 间接进来,
    // 重复放进去会触发双重 setOption, 同样会打断 hover tooltip.
  }, [treemapData, viewMode])

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
            {viewMode === "sector" && activeSector ? (
              <div className="inline-flex items-center gap-2">
                <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                  {activeSector.name} · {activeSector.sectorCode}
                </Badge>
                {drillDownStocks ? (
                  <span className="text-xs text-slate-500">
                    {drillDownStocks.length} 只成分股
                  </span>
                ) : null}
                <Button size="sm" variant="outline" onClick={() => { setViewMode("market"); setSelectedSector(null) }}>
                  <ArrowLeft className="mr-1 size-3.5" />返回全市场
                </Button>
              </div>
            ) : null}
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading}>
              <RefreshCw className={cn("mr-1 size-3.5", loading && "animate-spin")} />
              {loading ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-1.5">
          <div className="relative h-full min-h-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
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
