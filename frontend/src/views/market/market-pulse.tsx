import { useEffect, useMemo, useState } from "react"
import { Activity, ArrowDownRight, ArrowUpRight, Flame, Loader2, RefreshCw, TrendingUp, Waves, Wallet } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { fetchStyleSectors, fetchMarketOverviewAkshare, fetchMarketOverviewEltdx, fetchStyleSectorConstituents, triggerMarketOverviewEltdxRefresh, type StyleSectorItem, type MarketOverview, type MarketOverviewEltdx, type IndustryConstituentsIndexResponse, type StyleSectorConstituent } from "@/lib/api"
import { StyleSectorsHeatmap } from "./components/style-sectors-heatmap"
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
// 子组件: FlowMiniCard
// ---------------------------------------------------------------------------
type FlowValue = {
  label: string
  value: number | null
  diff: number | null
}

function FlowMiniCard({ item }: { item: FlowValue }) {
  const tone = moneyTone(item.value)
  const diffTone = moneyTone(item.diff)

  return (
    <div className={`rounded-2xl border ${tone.border} ${tone.bg} px-3 py-3`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-slate-500">{item.label}</div>
        <div className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${diffTone.soft}`}>
          较昨日 {_formatYi(item.diff)}
        </div>
      </div>
      <div className={`mt-2 text-xl font-bold tracking-tight ${tone.text}`}>
        {_formatYi(item.value)}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 子组件: FlowStructureBar
// ---------------------------------------------------------------------------
function FlowStructureBar({ items }: { items: FlowValue[] }) {
  const valid = items.filter((x) => x.value != null && Number.isFinite(x.value))
  const totalAbs = valid.reduce((s, x) => s + Math.abs(x.value || 0), 0)
  if (totalAbs <= 0) return null

  return (
    <div className="rounded-2xl border border-slate-100 bg-white px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold text-slate-700">资金结构</div>
        <div className="text-[11px] text-slate-400">按绝对值占比</div>
      </div>

      {/* 色块条 */}
      <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100">
        {valid.map((item) => {
          const pct = Math.abs(item.value || 0) / totalAbs
          const tone = moneyTone(item.value)
          return (
            <div
              key={item.label}
              className={tone.bar}
              style={{ width: `${pct * 100}%` }}
              title={`${item.label} ${_formatPct(pct * 100)}`}
            />
          )
        })}
      </div>

      {/* 4 个百分比标签 */}
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {valid.map((item) => {
          const pct = Math.abs(item.value || 0) / totalAbs
          const tone = moneyTone(item.value)
          return (
            <div key={item.label} className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${tone.bar}`} />
                <span className="text-[11px] text-slate-500">{item.label}</span>
              </div>
              <div className={`mt-0.5 text-xs font-semibold ${tone.text}`}>
                {_formatPct(pct * 100)}
              </div>
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
  const mainDiffTone = moneyTone(data.mainDiff)

  const items = [data.superLarge, data.large, data.medium, data.small]

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      {/* 头部 */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-slate-900">资金流向</div>
          <div className="mt-1 text-xs text-slate-500">东方财富 · 主力 = 超大单 + 大单</div>
        </div>
        <div className="rounded-full bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-500">
          {data.date}
        </div>
      </div>

      {/* hero */}
      <div className={`rounded-3xl border ${mainTone.border} ${mainTone.bg} p-4`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-medium text-slate-500">今日主力净流入</div>
            <div className={`mt-2 text-4xl font-bold tracking-tight ${mainTone.text}`}>
              {_formatYi(data.main)}
            </div>
            <div className="mt-2 text-xs text-slate-500">超大单 + 大单合计</div>
          </div>
          <div className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${mainDiffTone.soft}`}>
            较 {data.prevDate} {_formatYi(data.mainDiff)}
          </div>
        </div>
      </div>

      {/* 2x2 分项卡片 */}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {items.map((item) => (
          <FlowMiniCard key={item.label} item={item} />
        ))}
      </div>

      {/* 资金结构条 */}
      <div className="mt-3">
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
      overview?.isTradeTime ? 5 * 60_000 : 30 * 60_000,
    )
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview?.isTradeTime])

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

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {/* 1. 市场概况: 全A成交额 + 涨跌家数 (eltdx, 独立持久化) */}
          <Card className="border-border/30">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Waves className="size-3.5" />
                  市场概况
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  {overviewCounts?.stockCount != null ? `${overviewCounts.stockCount} 只` : overview?.stockCount != null ? `${overview.stockCount} 只` : ""}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {/* 全A成交额 hero */}
              <div className="text-2xl font-semibold tabular-nums text-foreground">
                {overviewCounts?.totalAmount != null
                  ? formatYi(overviewCounts.totalAmount)
                  : overview?.totalAmount != null
                    ? formatYi(overview.totalAmount)
                    : "—"}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">
                成交额 · 全A
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="inline-flex items-center gap-0.5 text-lg font-semibold tabular-nums text-red-600 dark:text-red-400">
                  <ArrowUpRight className="size-3.5" />
                  {formatCount(overviewCounts?.risingCount ?? overview?.risingCount)}
                </span>
                <span className="text-xs text-muted-foreground">/</span>
                <span className="inline-flex items-center gap-0.5 text-lg font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                  <ArrowDownRight className="size-3.5" />
                  {formatCount(overviewCounts?.fallingCount ?? overview?.fallingCount)}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
                <span>平 {formatCount(overviewCounts?.flatCount ?? overview?.flatCount)}</span>
                <span className="text-red-500">
                  涨停 {formatCount(overviewCounts?.limitUpCount ?? overview?.limitUpCount)}
                </span>
                <span className="text-emerald-500">
                  跌停 {formatCount(overviewCounts?.limitDownCount ?? overview?.limitDownCount)}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* 2. 资金流向 (按 spec 重写: 主结论 + 两组辅助信息) */}
          {(() => {
            const tradingDate = overview?.tradingDate ?? null
            const prevTradingDate = overview?.prevDayTradingDate ?? null
            const prevFlow = overview?.prevDayFlow

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

            const main = overview?.mainNetInflow ?? null
            const mainDiff = diff(main, prevFlow?.mainNetInflow ?? null)

            const superLarge = overview?.superLargeNetInflow ?? null
            const large = overview?.largeNetInflow ?? null
            const medium = overview?.mediumNetInflow ?? null
            const small = overview?.smallNetInflow ?? null

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
