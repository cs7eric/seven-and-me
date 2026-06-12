import { useEffect, useMemo, useState } from "react"
import { Activity, ArrowDownRight, ArrowUpRight, Flame, Loader2, RefreshCw, TrendingUp, Waves, Wallet } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { fetchStyleSectors, fetchMarketOverviewAkshare, type StyleSectorItem, type MarketOverview } from "@/lib/api"

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

function changeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-muted-foreground"
  if (pct > 0.05) return "text-red-600 dark:text-red-400"
  if (pct < -0.05) return "text-emerald-600 dark:text-emerald-400"
  return "text-muted-foreground"
}

function changeBg(pct: number | null | undefined): string {
  if (pct == null) return "bg-muted/40"
  if (pct > 0.05) return "bg-red-50 dark:bg-red-950/30"
  if (pct < -0.05) return "bg-emerald-50 dark:bg-emerald-950/30"
  return "bg-muted/40"
}

function formatPct(pct: number | null | undefined): string {
  if (pct == null) return "—"
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(2)}%`
}

/** 成交额 / 主力净流入 数值格式化: 元 → 亿 / 万 */
function formatYi(v: number | null | undefined): string {
  if (v == null) return "—"
  const abs = Math.abs(v)
  if (abs >= 100) return `${v.toFixed(0)}亿`
  if (abs >= 1) return `${v.toFixed(2)}亿`
  return `${(v * 10000).toFixed(0)}万`
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
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-2xl border border-border/30 bg-muted/30"
              />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sorted.map((item) => (
              <Card key={item.name} className={`${changeBg(item.change_pct)} border-border/30`}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center justify-between text-sm font-medium text-foreground">
                    <span className="truncate">{item.name}</span>
                    <span className={`tabular-nums text-base font-semibold ${changeColor(item.change_pct)}`}>
                      {formatPct(item.change_pct)}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-xs text-muted-foreground tabular-nums">
                    样本 {item.valid_size} / {item.sample_size} 只
                  </p>
                </CardContent>
              </Card>
            ))}
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
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={loadOverview}
            disabled={overviewLoading}
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
          {/* 1. 大盘成交额 */}
          <Card className="border-border/30">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Waves className="size-3.5" />
                  全 A 成交额
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="text-2xl font-semibold tabular-nums text-foreground">
                {formatYi(overview?.totalAmount)}
              </div>
              <div className="mt-1 text-xs text-muted-foreground tabular-nums">
                成交 {formatWanShou(overview?.totalVolume)} · {formatCount(overview?.stockCount)} 只
              </div>
            </CardContent>
          </Card>

          {/* 2. 主力净流入 (东方财富口径, 推算数据, 非交易所官方) */}
          <Card
            className={
              overview?.mainNetInflow == null
                ? "border-border/30"
                : overview.mainNetInflow >= 0
                  ? "border-red-200/60 bg-red-50/30 dark:border-red-900/40 dark:bg-red-950/10"
                  : "border-emerald-200/60 bg-emerald-50/30 dark:border-emerald-900/40 dark:bg-emerald-950/10"
            }
          >
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Wallet className="size-3.5" />
                  主力净流入
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  东方财富
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div
                className={`text-2xl font-semibold tabular-nums ${
                  overview?.mainNetInflow == null
                    ? "text-foreground"
                    : overview.mainNetInflow >= 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-emerald-600 dark:text-emerald-400"
                }`}
              >
                {overview?.mainNetInflow == null
                  ? "—"
                  : overview.mainNetInflow >= 0
                    ? `+${formatYi(overview.mainNetInflow)}`
                    : formatYi(overview.mainNetInflow)}
              </div>
              <div className="mt-1 grid grid-cols-2 gap-x-2 text-[10px] text-muted-foreground tabular-nums">
                <span>超大单 {formatYi(overview?.superLargeNetInflow)}</span>
                <span>大单 {formatYi(overview?.largeNetInflow)}</span>
                <span>中单 {formatYi(overview?.mediumNetInflow)}</span>
                <span>小单 {formatYi(overview?.smallNetInflow)}</span>
              </div>
            </CardContent>
          </Card>

          {/* 3. 涨跌家数 */}
          <Card className="border-border/30">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Activity className="size-3.5" />
                  涨跌家数
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex items-baseline gap-2">
                <span className="inline-flex items-center gap-0.5 text-xl font-semibold tabular-nums text-red-600 dark:text-red-400">
                  <ArrowUpRight className="size-4" />
                  {formatCount(overview?.risingCount)}
                </span>
                <span className="text-sm text-muted-foreground">/</span>
                <span className="inline-flex items-center gap-0.5 text-xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                  <ArrowDownRight className="size-4" />
                  {formatCount(overview?.fallingCount)}
                </span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground tabular-nums">
                平 {formatCount(overview?.flatCount)} · 涨停 {formatCount(overview?.limitUpCount)} · 跌停{" "}
                {formatCount(overview?.limitDownCount)}
              </div>
            </CardContent>
          </Card>

          {/* 4. 主力资金分档 (超大单 / 大单 / 中单 / 小单) — 占位用, 实际数据已在 #2 卡片里 */}
          <Card className="border-border/30 bg-muted/20">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Flame className="size-3.5" />
                  资金流向
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="text-xs leading-5 text-muted-foreground">
                {overview?.mainNetInflow == null ? (
                  <span>暂未拉到主力资金流数据</span>
                ) : (
                  <>
                    主力 = 超大单 + 大单。红色为净流入，绿色为净流出。
                    <div className="mt-1 text-[10px] text-muted-foreground/70">
                      推算口径，非交易所官方发布
                    </div>
                  </>
                )}
              </div>
            </CardContent>
          </Card>
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
    </WorkspaceShell>
  )
}
