import { useEffect, useMemo, useState } from "react"
import { Activity, ArrowDownRight, ArrowUpRight, Flame, Loader2, RefreshCw, TrendingUp, Waves, Wallet } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { fetchStyleSectors, fetchMarketOverviewAkshare, fetchMarketOverviewEltdx, fetchStyleSectorConstituents, triggerMarketOverviewEltdxRefresh, type StyleSectorItem, type MarketOverview, type MarketOverviewEltdx, type MarketHistoryPoint, type IndustryConstituentsIndexResponse, type StyleSectorConstituent } from "@/lib/api"
import { StyleSectorsHeatmap } from "./components/style-sectors-heatmap"
import { MarketPulsePanel } from "./components/market-pulse-panel"
import { IndexKlineDeck } from "./components/index-kline-deck"
import { IndustryConstituentsDrawer } from "@/views/industry-application/components/industry-constituents-drawer"

const PLACEHOLDER_CARDS = [
  {
    title: "Index Snapshot",
    description: "三大指数实时涨跌、成交额、领涨/领跌板块概览(占位)。",
  },
  {
    title: "Sector Heatmap",
    description: "申万一级 / 同花顺行业板块的涨跌幅热力图(占位)。",
  },
  {
    title: "Limit Up / Down",
    description: "涨停 / 跌停家数、连板高度、炸板率(占位)。",
  },
  {
    title: "Northbound Flow",
    description: "北向资金净流入、十大活跃股(占位)。",
  },
  {
    title: "Volume Leaders",
    description: "成交额 / 换手率 Top 榜单(占位)。",
  },
  {
    title: "Anomaly Alerts",
    description: "异动提醒:快速拉升、急速跳水、量比突增(占位)。",
  },
]

/** 成交额 / 主力净流入 格式化 (后端已返回 亿, 前端只 toFixed).
 *  sign: 流入 + / 流出 - / null —
 */
function formatYi(v: number | null | undefined): string {
  if (v == null) return "—"
  if (!Number.isFinite(v)) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(2)}亿`
}

// ---------------------------------------------------------------------------
// 客户端 A 股交易日 / 交易时段判定 (只处理周末; 节假日由后端 overview.tradingDate 覆盖)
//
// **使用场景**: overview API 还没回来 / 失败时, 给 IndexKlineDeck 一个"非空"的兜底,
// 避免 deck 顶部 pill 错误显示 "今日实时 1m" 并且把请求的 date 钉到"今天".
// 真实节假日会让周末 fallback 给个非交易日日期, 此时后端 overview 一旦回来就会用
// ``overview.tradingDate`` (上一个真正交易日) 覆盖.
// ---------------------------------------------------------------------------
function getMostRecentTradingDayClient(now: Date = new Date()): string {
  const d = new Date(now.getTime())
  const day = d.getDay()
  if (day === 0) d.setDate(d.getDate() - 2) // 周日 → 周五
  else if (day === 6) d.setDate(d.getDate() - 1) // 周六 → 周五
  return d.toISOString().slice(0, 10)
}

function isTradeTimeClient(now: Date = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const hm = now.getHours() * 60 + now.getMinutes()
  const morning = 9 * 60 + 30 <= hm && hm <= 11 * 60 + 30
  const afternoon = 13 * 60 <= hm && hm <= 15 * 60
  return morning || afternoon
}

/** 成交量: 万手 */
function formatWanShou(v: number | null | undefined): string {
  if (v == null) return "—"
  return `${v.toFixed(0)}万手`
}

function formatCount(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toLocaleString("zh-CN")
}

// ---------------------------------------------------------------------------
// 资金流向卡片 (按 spec 重写: 主结论 + 两组辅助信息)
// ---------------------------------------------------------------------------
/** 格式化亿单位数值 (复用一个 formatYi) */
const _formatYi = formatYi

/** 格式化百分比 */
function _formatPct(v: number): string {
  return `${v.toFixed(1)}%`
}

/**
 * moneyTone: 返回 A 股风格的颜色集合.
 * 流入 (value > 0): 红 / 浅红底
 * 流出 (value < 0): 绿 / 浅绿底
 * 零值: 灰 / 浅灰底
 */
function moneyTone(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v) || v === 0) {
    return {
      text: "text-slate-500",
      bg: "bg-slate-50",
      border: "border-slate-100",
      soft: "bg-slate-100 text-slate-500",
      bar: "bg-slate-300",
    }
  }
  if (v > 0) {
    return {
      text: "text-red-600",
      bg: "bg-red-50/70",
      border: "border-red-100",
      soft: "bg-red-100 text-red-700",
      bar: "bg-red-500",
    }
  }
  return {
    text: "text-emerald-600",
    bg: "bg-emerald-50/70",
    border: "border-emerald-100",
    soft: "bg-emerald-100 text-emerald-700",
    bar: "bg-emerald-500",
  }
}

// ---------------------------------------------------------------------------
// 类型: 资金流条目 (label + 当前值 + 较昨日 diff)
// ---------------------------------------------------------------------------
type FlowValue = {
  label: string
  value: number | null
  diff: number | null
}

// ---------------------------------------------------------------------------
// 子组件: FlowMiniCard (单个资金分类: label + 主数 + 较昨 diff)
// ---------------------------------------------------------------------------
function FlowMiniCard({ item }: { item: FlowValue }) {
  const tone = moneyTone(item.value)
  const diffTone = moneyTone(item.diff)
  const arrow = item.diff == null ? "" : item.diff > 0 ? "↑" : item.diff < 0 ? "↓" : "·"

  return (
    <div className={`relative overflow-hidden rounded-xl border ${tone.border} ${tone.bg} px-3 py-2`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-medium text-slate-500">{item.label}</div>
        {item.diff != null && (
          <div className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${diffTone.soft}`}>
            <span>{arrow}</span>
            <span>{item.diff >= 0 ? "+" : ""}{item.diff.toFixed(2)}亿</span>
          </div>
        )}
      </div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone.text}`}>
        {item.value != null
          ? `${item.value >= 0 ? "+" : ""}${item.value.toFixed(2)}`
          : "—"}
        <span className="ml-0.5 text-[11px] font-medium text-slate-400">亿</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 子组件: FlowStructureBar (纯可视化: 横向色块条 + 下方 4 色点图例)
// 数字本身已在 FlowMiniCard 显示, 这里只负责 "占比 + 流向方向" 可视化
// ---------------------------------------------------------------------------
function FlowStructureBar({ items }: { items: FlowValue[] }) {
  const valid = items.filter((x) => x.value != null && Number.isFinite(x.value))
  const totalAbs = valid.reduce((s, x) => s + Math.abs(x.value || 0), 0)
  if (totalAbs <= 0) return null

  return (
    <div className="rounded-xl border border-slate-100 bg-gradient-to-b from-slate-50/50 to-white px-3 py-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-slate-700">资金结构</div>
        <div className="text-[10px] text-slate-400">按绝对值占比</div>
      </div>

      {/* 色块条 */}
      <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-slate-100">
        {valid.map((item) => {
          const pct = Math.abs(item.value || 0) / totalAbs
          const tone = moneyTone(item.value)
          return (
            <div
              key={item.label}
              className={tone.bar}
              style={{ width: `${pct * 100}%` }}
              title={`${item.label} ${_formatYi(item.value)} · 占比 ${_formatPct(pct * 100)}`}
            />
          )
        })}
      </div>

      {/* 4 色点图例 (只显示 label + 占比, 不重复金额) */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {valid.map((item) => {
          const pct = Math.abs(item.value || 0) / totalAbs
          const tone = moneyTone(item.value)
          return (
            <div key={item.label} className="flex items-center gap-1 text-[11px]">
              <span className={`h-1.5 w-1.5 rounded-full ${tone.bar}`} />
              <span className="text-slate-500">{item.label}</span>
              <span className="font-semibold tabular-nums text-slate-700">
                {_formatPct(pct * 100)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------
type MoneyFlowData = {
  date: string
  prevDate: string
  main: number | null
  mainDiff: number | null
  superLarge: FlowValue
  large: FlowValue
  medium: FlowValue
  small: FlowValue
}

export function MoneyFlowCard({ data }: { data: MoneyFlowData }) {
  const mainTone = moneyTone(data.main)
  const items = [data.superLarge, data.large, data.medium, data.small]

  // 内联 diff: 较 06/11 +X.XX亿 ↑ / ↓
  const mainDiffText =
    data.mainDiff != null
      ? `较 ${data.prevDate || "昨日"} ${
          data.mainDiff >= 0 ? "+" : ""
        }${data.mainDiff.toFixed(2)}亿 ${data.mainDiff > 0 ? "↑" : data.mainDiff < 0 ? "↓" : ""}`
      : null
  const mainDiffTone = moneyTone(data.mainDiff)

  // hero 渐变背景: 流入浅红 / 流出浅绿 / null slate
  const heroBg =
    data.main == null
      ? "bg-slate-50"
      : data.main > 0
        ? "bg-gradient-to-br from-red-50 via-red-50/60 to-white"
        : data.main < 0
          ? "bg-gradient-to-br from-emerald-50 via-emerald-50/60 to-white"
          : "bg-slate-50"

  return (
    <section className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
      {/* 头部 */}
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-slate-900">资金流向</div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            东方财富 · 主力 = 超大单 + 大单
          </div>
        </div>
        <div className="rounded-full bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-500">
          {data.date}
        </div>
      </div>

      {/* hero: 主力净流入 + 内联 diff (5xl 大字 + 渐变背景) */}
      <div
        className={`relative overflow-hidden rounded-2xl border ${mainTone.border} ${heroBg} px-3 py-2.5`}
      >
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-xs font-medium text-slate-500">今日主力净流入</div>
          {mainDiffText && (
            <div className={`text-[11px] font-medium tabular-nums ${mainDiffTone.text}`}>
              {mainDiffText}
            </div>
          )}
        </div>
        <div
          className={`mt-1 text-3xl font-bold tracking-tight tabular-nums ${mainTone.text}`}
        >
          {_formatYi(data.main)}
        </div>
      </div>

      {/* 2x2 分类: 超大单 / 大单 / 中单 / 小单 (每个保留 diff) */}
      <div className="mt-2 grid grid-cols-2 gap-2">
        {items.map((item) => (
          <FlowMiniCard key={item.label} item={item} />
        ))}
      </div>

      {/* 资金结构条 (纯可视化) */}
      <div className="mt-2">
        <FlowStructureBar items={items} />
      </div>
    </section>
  )
}

/**
 * 把数字格式化成 "1.5亿" / "2300万" / "5百万" / "1.2万亿" / "8000" 之类可读字符串.
 *
 * 用途: 喂 IndustryConstituentsDrawer 的 流通市值 / 流通股 / 成交额 字段
 * (drawer 的 formatAmount 只是 String(value), 不做格式化, 我们前端预 format).
 *
 * 单位梯度 (从大到小):
 *   万亿 (1e12) > 亿 (1e8) > 千万 (1e7) > 百万 (1e6) > 万 (1e4) > 原始
 */
function formatReadable(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—"
  const abs = Math.abs(v)
  const fmt = (scaled: number) => {
    // 2 位小数, 去掉尾随 0
    const s = scaled.toFixed(2).replace(/\.?0+$/, "")
    return s
  }
  if (abs >= 1e12) return `${fmt(v / 1e12)}万亿`
  if (abs >= 1e8) return `${fmt(v / 1e8)}亿`
  if (abs >= 1e7) return `${fmt(v / 1e7)}千万`
  if (abs >= 1e6) return `${fmt(v / 1e6)}百万`
  if (abs >= 1e4) return `${fmt(v / 1e4)}万`
  return v.toFixed(0)
}

export default function MarketPulsePage() {
  const [items, setItems] = useState<StyleSectorItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  // 大盘成交额 / 主力净流入 (AKShare)
  const [overview, setOverview] = useState<MarketOverview | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [overviewFetchedAt, setOverviewFetchedAt] = useState<string | null>(null)
  // 市场概况 (eltdx): 独立获取, 互不影响 fund-flow 持久化
  const [overviewCounts, setOverviewCounts] = useState<MarketOverviewEltdx | null>(null)
  const [overviewCountsError, setOverviewCountsError] = useState<string | null>(null)

  // 风格板块 成分股 drawer (复用 industry-constituents-drawer, 走 external data 模式)
  const [constituentsOpen, setConstituentsOpen] = useState(false)
  const [constituentsStyle, setConstituentsStyle] = useState<string | null>(null)
  const [constituentsData, setConstituentsData] = useState<IndustryConstituentsIndexResponse | null>(null)
  const [constituentsLoading, setConstituentsLoading] = useState(false)

  // 历史趋势图 联动:
  //   hoveredPoint  → 鼠标 hover 某根柱子 (瞬时预览, 不持久化, 不影响 K 线)
  //   selectedPoint → 鼠标 click 某根柱子 (持久化, 钉住, 顶部 K 线 + 快照卡 全部跟随)
  //
  // **三级 fallback** 决定 overview 卡片显示:
  //   hoveredPoint ?? selectedPoint ?? overview (今日 / 上次收盘)
  //   hover 优先于 click: 用户先 click 锁定到 A 日, 然后 hover B 日预览 → 显示 B
  //   鼠标离开 hover → 自动回退到 click 锁定的 A 日
  //
  // selectedPoint 为 null 时, K 线回退到 overview.tradingDate (今日 / 上次收盘)
  const [hoveredPoint, setHoveredPoint] = useState<MarketHistoryPoint | null>(null)
  const [selectedPoint, setSelectedPoint] = useState<MarketHistoryPoint | null>(null)
  // overview 卡片显示源: hover > click > 今日 overview
  const activePoint = hoveredPoint ?? selectedPoint
  // K 线 + replay 状态只看 click 锁定的 selectedPoint (hover 不影响 K 线, 避免抖动)
  const activeTradingDate =
    selectedPoint?.date ?? overview?.tradingDate ?? getMostRecentTradingDayClient()
  // isTradeTime 同理: 后端 get_latest_snapshot 已经覆盖为"当前真实时间", 这里再补一道
  // 客户端兜底, 处理 overview 尚未到达的初始空窗.
  const liveIsTradeTime = overview?.isTradeTime ?? isTradeTimeClient()
  const isReplayMode = Boolean(selectedPoint)
  const isPinnedReplay = Boolean(selectedPoint)

  const clearReplay = () => {
    setSelectedPoint(null)
  }

  /**
   * 鼠标 hover 历史图某根柱子 → 瞬时切换 overview 卡片数据预览
   * (K 线不动, 只有成交额 / 主力净流入 卡片跟手)
   */
  const handlePointHover = (point: MarketHistoryPoint | null) => {
    setHoveredPoint(point)
  }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchStyleSectors()
      setItems(res.items || [])
      setFetchedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const loadOverview = async () => {
    setOverviewLoading(true)
    setOverviewError(null)
    try {
      // fund-flow: eastmoney 资金流 (独立持久化)
      const res = await fetchMarketOverviewAkshare()
      setOverview(res)
      setOverviewFetchedAt(
        res.fetchedAt
          ? new Date(res.fetchedAt).toLocaleTimeString()
          : new Date().toLocaleTimeString(),
      )
    } catch (e) {
      setOverviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setOverviewLoading(false)
    }

    // eltdx: 全A成交额 / 涨跌家数 (独立持久化, 互不影响)
    try {
      const counts = await fetchMarketOverviewEltdx()
      setOverviewCounts(counts)
    } catch (e) {
      setOverviewCountsError(e instanceof Error ? e.message : String(e))
    }
  }

  /**
   * 把后端 constituents 映射到 14 列 IndustryConstituentsIndexResponse 形状,
   * 喂给现成的 IndustryConstituentsDrawer (external data 模式).
   *
   * 关键:  **column key 必须严格匹配 drawer COLUMNS 数组里的 key** (含 `(%)` 后缀).
   *        否则 drawer 的 `r[key]` 读 undefined -> 显示 "—".
   *        涨跌幅(%) / 换手(%) / 振幅(%) 都带 "(%)" 后缀.
   *
   * 数值列 (流通市值 / 流通股 / 成交额) 用 ``formatReadable`` 预格式化成
   * "1.5亿" / "2300万" / "5百万" / "1.2万亿" 字符串 (drawer 的 formatAmount 不做单位格式化).
   *
   * 缺失字段 (涨速 / 量比 / 市盈率) tencent snapshot 拿不到, 留 null -> drawer 渲染为 "—".
   */
  const mapToIndustryShape = (
    name: string,
    constituents: StyleSectorConstituent[],
  ): IndustryConstituentsIndexResponse => {
    return {
      ok: true,
      name,
      code: name, // 复用 drawer's code 字段 (显示用)
      count: constituents.length,
      matched: constituents.filter((c) => c.valid).length,
      indexFetchedAt: null,
      rowsFetchedAt: constituents[0] ? new Date().toISOString() : null,
      rows: constituents.map((c, i) => ({
        序号: i + 1,
        代码: c.code,                      // 已去前缀 (000048)
        名称: c.name,
        现价: c.last_price,
        "涨跌幅(%)": c.change_pct,        // <- 关键: 带 "(%)" 后缀
        涨跌: c.change_amount,
        涨速: null,                       // tencent snapshot 无 -> "—"
        "换手(%)": c.turnover_rate,       // <- 关键: 带 "(%)" 后缀, 后端实时算
        量比: null,                       // tencent snapshot 无 -> "—"
        "振幅(%)": c.amplitude,           // <- 关键: 带 "(%)" 后缀
        成交额: formatReadable(c.turnover_amount),    // 元 -> "1.5亿" / "2300万"
        流通股: formatReadable(c.circulating_shares),  // 股 -> "1.5亿" / "2300万"
        流通市值: formatReadable(c.circulating_market_cap),  // 元 -> "1.5亿" / "2300万"
        市盈率: null,                     // tencent snapshot 无 -> "—"
      })),
    }
  }

  const loadConstituents = async (name: string) => {
    setConstituentsLoading(true)
    setConstituentsData(null)
    try {
      const res = await fetchStyleSectorConstituents(name)
      if (!res.ok) {
        throw new Error(res.error || "加载失败")
      }
      setConstituentsData(mapToIndustryShape(name, res.constituents))
    } catch (e) {
      // drawer 静默失败, 由 drawer 自身的 loading skeleton 状态展示
      setConstituentsData(null)
    } finally {
      setConstituentsLoading(false)
    }
  }

  useEffect(() => {
    void load()
    void loadOverview()
    // 交易时间 5min 一次轮询; 非交易时间 30min 一次 (scheduler 也没在跑, 读 archive)
    const id = window.setInterval(
      () => {
        void loadOverview()
      },
      liveIsTradeTime ? 5 * 60_000 : 30 * 60_000,
    )
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveIsTradeTime])

  const sorted = useMemo(
    () => [...items].sort((a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity)),
    [items],
  )

  return (
    <WorkspaceShell sectionLabel="Market Pulse" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Flame className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Market Pulse
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            市场脉搏的预留页面,后续接入指数快照、板块热力、涨跌停统计、北向资金等实时指标。
          </p>
        </div>
      </div>

      {/* === 页面正文: 统一 24px section 间距, 5 大区块按 spec 顺序堆叠 === */}
      <div className="space-y-6">
      {/* === 大盘成交额 / 主力净流入 (AKShare 双源) === */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              大盘成交额 / 主力净流入
            </h2>
            <p className="text-sm text-muted-foreground">
              全 A 实时成交 + 东方财富主力资金口径
              {overview?.tradingDate ? ` · 交易日 ${overview.tradingDate}` : ""}
              {overviewFetchedAt ? ` · ${overviewFetchedAt} 拉取` : ""}
              {overview?.source && overview.source !== "akshare" ? ` · 来源 ${overview.source}` : ""}
              {overviewCounts?.tradingDate && overview?.tradingDate !== overviewCounts.tradingDate
                ? ` · eltdx ${overviewCounts.tradingDate}`
                : ""}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={loadOverview}
            disabled={overviewLoading}
            title="刷新资金流向 + 市场概况 (eltdx)"
          >
            {overviewLoading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            <span className="ml-1">刷新</span>
          </Button>
        </div>

        {overviewError && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            拉取失败: {overviewError}
          </div>
        )}

        {/* === 统一显示数据: hover/click 历史日 → 用 activePoint; 否则用今日 overview/overviewCounts === */}
        {(() => {
          const display = activePoint
            ? {
                source: "history" as const,
                tradingDate: activePoint.date,
                prevDayTradingDate: null as string | null,
                prevDayFlow: null as Record<string, unknown> | null,
                totalAmount: activePoint.totalAmount,
                stockCount: null as number | null,
                risingCount: activePoint.risingCount,
                fallingCount: activePoint.fallingCount,
                flatCount: activePoint.flatCount,
                limitUpCount: activePoint.limitUpCount,
                limitDownCount: activePoint.limitDownCount,
                mainNetInflow: activePoint.mainNetInflow,
                superLargeNetInflow: activePoint.superLargeNetInflow,
                largeNetInflow: activePoint.largeNetInflow,
                mediumNetInflow: activePoint.mediumNetInflow,
                smallNetInflow: activePoint.smallNetInflow,
              }
            : {
                source: "today" as const,
                tradingDate: overview?.tradingDate ?? null,
                prevDayTradingDate: overview?.prevDayTradingDate ?? null,
                prevDayFlow: (overview?.prevDayFlow as Record<string, unknown> | null) ?? null,
                totalAmount: overviewCounts?.totalAmount ?? overview?.totalAmount ?? null,
                stockCount: overviewCounts?.stockCount ?? overview?.stockCount ?? null,
                risingCount: overviewCounts?.risingCount ?? overview?.risingCount ?? null,
                fallingCount: overviewCounts?.fallingCount ?? overview?.fallingCount ?? null,
                flatCount: overviewCounts?.flatCount ?? overview?.flatCount ?? null,
                limitUpCount: overviewCounts?.limitUpCount ?? overview?.limitUpCount ?? null,
                limitDownCount:
                  overviewCounts?.limitDownCount ?? overview?.limitDownCount ?? null,
                mainNetInflow: overview?.mainNetInflow ?? null,
                superLargeNetInflow: overview?.superLargeNetInflow ?? null,
                largeNetInflow: overview?.largeNetInflow ?? null,
                mediumNetInflow: overview?.mediumNetInflow ?? null,
                smallNetInflow: overview?.smallNetInflow ?? null,
              }

          // 大盘成交额 较昨日差额
          //  (history 视图 prevDayFlow=null, 自然 amountDiff=null → 不渲染)
          const prevDayAmount =
            (display.prevDayFlow as { totalAmount?: number | null } | null)?.totalAmount ?? null
          const amountDiff =
            display.totalAmount != null && prevDayAmount != null
              ? display.totalAmount - prevDayAmount
              : null

          return (
        <div className="space-y-3">
          {display.source === "history" && display.tradingDate && (
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
              <span>已选中 {display.tradingDate} 历史快照</span>
              <button
                type="button"
                className="ml-1 text-amber-700 underline-offset-2 hover:underline"
                onClick={clearReplay}
              >
                返回今日
              </button>
            </div>
          )}

        <div className="grid gap-3 xl:grid-cols-[1.05fr_1fr]">
          {/* 1. 大盘成交额: hero (5xl + 渐变) + 2x2 涨跌家数 */}
          <Card className="flex h-full flex-col border-border/30">
            <CardHeader className="px-4 pb-2 pt-4">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Waves className="size-3.5" />
                  大盘成交额
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  {display.stockCount != null ? `${display.stockCount} 只` : ""}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col px-4 pb-4 pt-0">
              {/* hero: 5xl 大字 + 渐变背景, 跟右卡片 hero 视觉对齐 */}
              <div className="rounded-2xl border border-slate-100 bg-gradient-to-br from-slate-50 via-slate-50/40 to-white px-3 py-2.5">
                <div className="text-xs font-medium text-slate-500">
                  全 A 成交额
                </div>
                <div className="mt-1 text-3xl font-bold tracking-tight tabular-nums text-slate-900">
                  {display.totalAmount != null ? formatYi(display.totalAmount) : "—"}
                </div>
                {/* 较昨日差额: 涨红跌绿, A股惯例 */}
                {amountDiff != null ? (
                  <div className="mt-1 inline-flex items-baseline gap-1 text-xs tabular-nums">
                    <span className="text-slate-400">较昨日</span>
                    {amountDiff > 0 ? (
                      <ArrowUpRight className="size-3 text-red-500" />
                    ) : amountDiff < 0 ? (
                      <ArrowDownRight className="size-3 text-emerald-500" />
                    ) : null}
                    <span
                      className={
                        amountDiff > 0
                          ? "font-semibold text-red-600"
                          : amountDiff < 0
                            ? "font-semibold text-emerald-600"
                            : "text-slate-500"
                      }
                    >
                      {formatYi(amountDiff)}
                    </span>
                  </div>
                ) : null}
              </div>

              {/* 2x2 stats: 涨 / 跌 / 涨停 / 跌停 */}
              <div className="mt-2 grid grid-cols-2 gap-2">
                {/* 涨 */}
                <div className="rounded-xl border border-red-100 bg-red-50/50 px-3 py-2">
                  <div className="flex items-center gap-1 text-[11px] font-medium text-red-600 dark:text-red-400">
                    <ArrowUpRight className="size-3" />
                    <span>上涨</span>
                  </div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-red-600 dark:text-red-400">
                    {formatCount(display.risingCount)}
                  </div>
                </div>
                {/* 跌 */}
                <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 px-3 py-2">
                  <div className="flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                    <ArrowDownRight className="size-3" />
                    <span>下跌</span>
                  </div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                    {formatCount(display.fallingCount)}
                  </div>
                </div>
                {/* 涨停 */}
                <div className="rounded-xl border border-red-100 bg-white px-3 py-2">
                  <div className="text-[11px] font-medium text-slate-500">涨停</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-red-600 dark:text-red-400">
                    {formatCount(display.limitUpCount)}
                  </div>
                </div>
                {/* 跌停 */}
                <div className="rounded-xl border border-emerald-100 bg-white px-3 py-2">
                  <div className="text-[11px] font-medium text-slate-500">跌停</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                    {formatCount(display.limitDownCount)}
                  </div>
                </div>
              </div>

              {/* 平盘 footnote (compact 一行) */}
              <div className="mt-2 text-[10px] text-slate-400">
                平盘 {formatCount(display.flatCount)} 只
              </div>
            </CardContent>
          </Card>

          {/* 2. 资金流向 */}
          {(() => {
            const tradingDate = display.tradingDate
            const prevTradingDate = display.prevDayTradingDate
            const prevFlow = display.prevDayFlow as
              | {
                  mainNetInflow: number | null
                  superLargeNetInflow: number | null
                  largeNetInflow: number | null
                  mediumNetInflow: number | null
                  smallNetInflow: number | null
                }
              | null

            // 格式化日期 badge: "06月12日"
            const dateBadge = (() => {
              if (!tradingDate) return "今日"
              try {
                const d = new Date(tradingDate + "T00:00:00")
                return `${(d.getMonth() + 1).toString().padStart(2, "0")}月${d.getDate().toString().padStart(2, "0")}日`
              } catch { return "今日" }
            })()

            // 格式化 prevDate badge: "06/11"
            const prevDateBadge = prevTradingDate
              ? prevTradingDate.slice(5).replace("-", "/")
              : ""

            // 算 diff
            const diff = (cur: number | null, prev: number | null): number | null =>
              cur != null && prev != null ? cur - prev : null

            const main = display.mainNetInflow
            const mainDiff = diff(main, prevFlow?.mainNetInflow ?? null)

            const superLarge = display.superLargeNetInflow
            const large = display.largeNetInflow
            const medium = display.mediumNetInflow
            const small = display.smallNetInflow

            const moneyFlowData: MoneyFlowData = {
              date: dateBadge,
              prevDate: prevDateBadge,
              main,
              mainDiff,
              superLarge: {
                label: "超大单",
                value: superLarge,
                diff: diff(superLarge, prevFlow?.superLargeNetInflow ?? null),
              },
              large: {
                label: "大单",
                value: large,
                diff: diff(large, prevFlow?.largeNetInflow ?? null),
              },
              medium: {
                label: "中单",
                value: medium,
                diff: diff(medium, prevFlow?.mediumNetInflow ?? null),
              },
              small: {
                label: "小单",
                value: small,
                diff: diff(small, prevFlow?.smallNetInflow ?? null),
              },
            }

            return <MoneyFlowCard data={moneyFlowData} />
          })()}
        </div>
        </div>
          )
        })()}
      </div>

      {/* === 三大指数分时图 === */}
      <IndexKlineDeck
        tradingDate={activeTradingDate}
        replay={isReplayMode}
        pinned={isPinnedReplay}
        onClearPinned={clearReplay}
        isTradeTime={liveIsTradeTime}
      />

      {/* === 市场脉搏 · 历史趋势图 (4 视图复合图 + 洞察小指标) === */}
      <MarketPulsePanel
        defaultView="flow"
        selectedPoint={selectedPoint}
        hoveredPoint={hoveredPoint}
        onPointClick={(_idx, point) => {
          // toggle: 同一根再点 → 取消; 不同的 → 切换
          setSelectedPoint((cur) => (cur?.date === point.date ? null : point))
        }}
        onPointHover={handlePointHover}
      />

      {/* === 风格板块涨跌幅 (29 个, 来自 /api/stock-chart/style-sectors) === */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              风格板块涨跌幅
            </h2>
            <p className="text-sm text-muted-foreground">
              29 个动态股票池, 等权平均涨跌幅 (TDX 风格板块口径)
              {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            <span className="ml-1">刷新</span>
          </Button>
        </div>

        {error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            拉取失败: {error}
          </div>
        )}

        {loading && items.length === 0 ? (
          <div className="h-[420px] w-full animate-pulse rounded-2xl border border-border/30 bg-muted/30" />
        ) : (
            // **h-[420px] 固定高度父容器**: StyleSectorsHeatmap 内部用
            // flex h-full min-h-0 flex-col, h-full 一路吃高度到这里的 420px,
            // 才能让 treemap 拿到稳定 420-legend 高度的 canvas. 不写这个父级
            // h-[420px], heatmap 自己没高度, treemap canvas 就是 0, 渲染怪.
            <div className="h-[420px]">
              <StyleSectorsHeatmap
                items={sorted}
                loading={loading}
                onCellClick={(name) => {
                  setConstituentsStyle(name)
                  setConstituentsOpen(true)
                  void loadConstituents(name)
                }}
              />
            </div>
        )}
      </div>

      {/* === 后续接入模块的占位 === */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {PLACEHOLDER_CARDS.map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="size-4 text-muted-foreground" />
                {item.title}
              </CardTitle>
              <CardDescription>Mock · 待接入</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-5 text-sm text-muted-foreground">
        <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
          <TrendingUp className="size-4" />
          路线
        </div>
        后续把 stock-overview/mock-market.tsx 中的强势板块 / 主力净流入 / 行业轮动 三个核心模块拆解后,逐步迁入本页面。
      </div>
      </div>

      {/* === 风格板块 成分股 drawer (复用 industry-application 的 IndustryConstituentsDrawer) === */}
      <IndustryConstituentsDrawer
        industryCode={constituentsStyle}
        industryName={constituentsStyle}
        open={constituentsOpen}
        onOpenChange={setConstituentsOpen}
        data={constituentsData}
        loading={constituentsLoading}
      />
    </WorkspaceShell>
  )
}
