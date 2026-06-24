/**
 * Top Card: Market Sentiment Index (composite, 9 张卡加权合成)
 *
 * 图表为三层叠加 (源自 /poc/sentiment-overlay 迁移):
 *   上 1: 主力净流 (rainfall 风格, 反向轴)
 *   中 3: 情绪分 + 上证指数
 *   下 1: 成交额 (flow 风格, 蓝色面积)
 *
 * 成交额数据源: duckdb.turnover_activity_daily.total_amount (亿元, 端上转回元给 overlay)
 * 主力净流数据源: duckdb.market_overview_daily.main_net_inflow (元, 经 ×1e8 换算)
 * 上证指数数据源: duckdb.index_daily_raw
 * 情绪分数据源:   duckdb.market_sentiment_index_daily
 */
import { useEffect, useMemo, useState } from "react"
import { Activity, Smile } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Calendar as CalendarUi } from "@/components/ui/calendar"
import { cn } from "@/lib/utils"
import { toLocalDate, toLocalIso } from "@/lib/date-utils"
import { SentimentOverlay, type SentimentOverlaySeries } from "./sentiment-overlay"
import { CompositeCardSkeleton } from "./skeletons"
import { MSI_LEVEL_META } from "./sub-metric"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentIndex,
  fetchMarketSentimentIndexHistory,
  fetchMarketSentimentTurnoverActivityHistory,
  fetchIndexDailyHistory,
  fetchMarketOverviewHistory,
  type IndexDailyItem,
  type MarketOverviewHistoryItem,
  type MarketSentimentIndexResponse,
  type MarketSentimentIndexHistoryItem,
  type TurnoverActivityHistoryItem,
} from "@/lib/api"

interface MarketSentimentIndexCardProps {
  date: string | null
  onDateChange: (d: string | null) => void
  onReset: () => void
  maxDate: Date
}

export function MarketSentimentIndexCard({
  date,
  onDateChange,
  onReset,
  maxDate,
}: MarketSentimentIndexCardProps) {
  const [data, setData] = useState<MarketSentimentIndexResponse | null>(null)
  const [history, setHistory] = useState<MarketSentimentIndexHistoryItem[] | null>(null)
  const [shIndex, setShIndex] = useState<IndexDailyItem[] | null>(null)
  const [overview, setOverview] = useState<MarketOverviewHistoryItem[] | null>(null)
  const [turnoverHistory, setTurnoverHistory] = useState<TurnoverActivityHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  // 后端 3 年数据已就绪 (limit_emotion / vol_sentiment / profit_effect / msi 全部 728+ 行)
  const USE_MOCK = false

  useEffect(() => {
    if (USE_MOCK) return
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist, sh, ov, ta] = await Promise.all([
          fetchMarketSentimentIndex(date ?? undefined),
          fetchMarketSentimentIndexHistory(start, end),
          fetchIndexDailyHistory({ code: "000001", start, end }),
          fetchMarketOverviewHistory({ start, end }),
          fetchMarketSentimentTurnoverActivityHistory(start, end),
        ])
        if (cancelled) return
        setData(snap)
        setHistory(hist.items ?? [])
        setShIndex(sh.items ?? [])
        setOverview(ov.items ?? [])
        setTurnoverHistory(ta.items ?? [])
      } catch {
        if (!cancelled) {
          setData(null)
          setHistory(null)
          setShIndex(null)
          setOverview(null)
          setTurnoverHistory(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [date])

  // Mock data — 90 个交易日的合成情绪分, 含均值回归 + 多周期 + 大噪声 + 偶发冲击
  // 目标覆盖 10-90 全档位, 让 50 中性线/红蓝分区都看得出变化
  useEffect(() => {
    if (!USE_MOCK) return
    const mockHistory: MarketSentimentIndexHistoryItem[] = []
    const today = new Date()
    let score = 55 // 从中性开始
    for (let i = 90; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(d.getDate() - i)
      if (d.getDay() === 0 || d.getDay() === 6) continue // 跳过周末
      // 弱均值回归 (loose pull back)
      const drift = (50 - score) * 0.02
      // 多周期叠加 (长周期 + 短周期)
      const cycle = Math.sin(i * 0.09) * 14 + Math.sin(i * 0.21) * 6
      // 大噪声 (±7)
      const noise = (Math.random() - 0.5) * 14
      // 偶发极端冲击 (~6% 概率)
      const shock = Math.random() < 0.06 ? (Math.random() < 0.5 ? -15 : 18) : 0
      score = Math.max(8, Math.min(92, score + drift + cycle * 0.10 + noise + shock))
      const level =
        score >= 70 ? "hot" as const
        : score >= 55 ? "active" as const
        : score >= 45 ? "normal" as const
        : score >= 30 ? "weak" as const
        : "ice" as const
      mockHistory.push({
        tradeDate: d.toISOString().slice(0, 10),
        compositeScore: Math.round(score * 10) / 10,
        level,
      } as unknown as MarketSentimentIndexHistoryItem)
    }
    const last = mockHistory[mockHistory.length - 1]
    const mockData: MarketSentimentIndexResponse = {
      ok: true,
      tradeDate: last.tradeDate,
      compositeScore: last.compositeScore,
      level: last.level,
      componentCount: 9,
      components: {
        vol: 72,
        turnover: 48,
        price_strength: 35,
        risk_appetite: 62,
        breadth: 55,
        limit_emotion: last.compositeScore,
        profit_effect: 58,
        sector_breadth: 44,
        style_risk: 37,
      },
      weights: {
        vol: 0.15, turnover: 0.15, price_strength: 0.10,
        risk_appetite: 0.10, breadth: 0.15, limit_emotion: 0.15,
        profit_effect: 0.10, sector_breadth: 0.05, style_risk: 0.05,
      },
    } as unknown as MarketSentimentIndexResponse

    setData(mockData)
    setHistory(mockHistory)
    setLoading(false)
  }, [USE_MOCK])

  const score = data?.compositeScore ?? null
  const level = data?.level ?? "normal"
  const meta = MSI_LEVEL_META[level] ?? MSI_LEVEL_META.normal

  // 跟 SentimentOverlay tooltip moodColor 同款色阶: ≥70 极热 / ≥60 偏热 / ≥50 偏多 / ≥40 偏弱 / ≥30 低迷 / ＜30 冰点
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 60
          ? "text-orange-600"
          : score >= 50
            ? "text-amber-600"
            : score >= 40
              ? "text-sky-500"
              : score >= 30
                ? "text-blue-600"
                : "text-slate-400"

  // 以 MSI 自身历史作为主时间轴.
  // 上证/主力净流/成交额缺某一天时只让叠加线出现 null, 不再把 MSI 最后一天一起裁掉.
  const sortedHistory = (history ?? [])
    .slice()
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
  const sentimentPoints = sortedHistory.map((it) => ({
    date: it.tradeDate.slice(5),
    value: it.compositeScore ?? 50,
    level: it.level,
  }))

  // 上证指数叠加线: 用完整 YYYY-MM-DD 对齐避免跨年 MM-DD 撞 key.
  const shOverlay = (() => {
    if (!shIndex || shIndex.length === 0) return undefined
    const shMap = new Map(shIndex.map((it) => [it.tradeDate, it.close]))
    const data: Array<{ date: string; value: number }> = sortedHistory.flatMap((it) => {
      const v = shMap.get(it.tradeDate)
      return v == null ? [] : [{ date: it.tradeDate.slice(5), value: v }]
    })
    const hitCount = data.length
    if (hitCount < 2) return undefined
    return {
      name: "上证指数",
      color: "#475569",  // slate-600 全不透明 (card bg-muted/50 浅灰, 浅色糊掉)
      data,
    }
  })()

  /**
   * 主力净流 / 成交额两个 duckdb 叠加线:
   * - 主力净流: duckdb.market_overview_daily.main_net_inflow (接口层是 "亿", 下游转回 "元")
   * - 成交额:   duckdb.turnover_activity_daily.total_amount (接口层是 "亿", 下游转回 "元")
   *
   * 统一按 sortedHistory 的日期 key 对齐, 与情绪分折线 + 上证叠加线共享 x 轴.
   */
  const { mainNetFlowOverlay, amountOverlay } = useMemo(() => {
    const flowMapFromOverview = new Map(
      (overview ?? []).map((it) => [
        it.tradeDate,
        it.mainNetInflow == null ? null : it.mainNetInflow * 1e8,
      ]),
    )
    const amountMapFromTurnover = new Map(
      (turnoverHistory ?? []).map((it) => [
        it.tradeDate,
        it.totalAmount == null ? null : it.totalAmount * 1e8,
      ]),
    )

    const flowData = sortedHistory.map((it) => ({
      date: it.tradeDate.slice(5),
      value: flowMapFromOverview.get(it.tradeDate) ?? null,
    }))
    const amountData = sortedHistory.map((it) => ({
      date: it.tradeDate.slice(5),
      value: amountMapFromTurnover.get(it.tradeDate) ?? null,
    }))

    const flowHitCount = flowData.filter((d) => d.value != null).length
    const amountHitCount = amountData.filter((d) => d.value != null).length
    const filterSeriesData = (items: typeof flowData) =>
      items.flatMap((it) => (it.value == null ? [] : [{ date: it.date, value: it.value }]))

    return {
      mainNetFlowOverlay:
        flowHitCount >= 2
          ? ({ name: "主力净流", color: "#ef4444", data: filterSeriesData(flowData) } as SentimentOverlaySeries)
          : undefined,
      amountOverlay:
        amountHitCount >= 2
          ? ({ name: "成交额", color: "#5470c6", data: filterSeriesData(amountData) } as SentimentOverlaySeries)
          : undefined,
    }
  }, [sortedHistory, overview, turnoverHistory])

  return (
    <Card className="border-0 shadow-none bg-muted/50 h-full">
      <CardContent className="h-full">
        {loading ? (
          <CompositeCardSkeleton />
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="grid h-full grid-rows-[3fr_1fr] gap-3 max-md:grid-rows-[auto_auto]">
            {/* 上 3/4: 折线图区 */}
            <div className="flex min-h-0 flex-col gap-2 max-md:gap-3">
              <div className="inline-flex items-center gap-2 rounded-full bg-background px-3 py-1 text-xs font-medium text-muted-foreground self-start max-sm:px-2.5 max-sm:py-0.5">
                <Smile className="size-3.5" />
                Market Sentiment
              </div>
              <div className="flex flex-wrap items-end gap-x-3 gap-y-1 max-sm:items-start max-sm:gap-x-2">
                <span className={`text-5xl font-semibold tabular-nums max-sm:text-[2.7rem] ${tone}`}>
                  {score.toFixed(1)}
                </span>
                <span className="text-xs text-muted-foreground">/ 100</span>
                <span
                  className={cn(
                    "ml-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                    meta.chip
                  )}
                >
                  {meta.label}
                </span>
                {data?.tradeDate && (
                  <span className="ml-1 inline-flex items-center gap-1 text-xs text-muted-foreground tabular-nums max-sm:ml-0">
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          type="button"
                          aria-label="选择历史日期"
                          className="inline-flex items-center rounded-sm text-xs tabular-nums underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring max-sm:py-1"
                        >
                          {date ?? data.tradeDate}
                        </button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[calc(100vw-1.5rem)] max-w-[18rem] p-0 sm:w-auto sm:max-w-none" align="start">
                        <CalendarUi
                          mode="single"
                          selected={toLocalDate(date ?? data.tradeDate)}
                          onSelect={(d) => onDateChange(d ? toLocalIso(d) : null)}
                          disabled={[
                            { after: maxDate },
                            (day) => {
                              const dow = day.getDay()
                              return dow === 0 || dow === 6
                            },
                          ]}
                          autoFocus
                        />
                      </PopoverContent>
                    </Popover>
                    {date && (
                      <button
                        type="button"
                        onClick={onReset}
                        aria-label="重置为最近交易日"
                        className="inline-flex items-center text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm"
                      >
                        重置
                      </button>
                    )}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-muted-foreground max-sm:leading-4">
                <Activity className="size-3.5" />
                <span>实时情绪指标</span>
                <span className="text-red-600/70 max-sm:basis-full">≥70 极热</span>
                <span className="text-orange-600/70">60-70 偏热</span>
                <span className="text-amber-600/70">50-60 偏多</span>
                <span className="text-sky-500/80">40-50 偏弱</span>
                <span className="text-blue-600/70">30-40 低迷</span>
                <span className="text-slate-400">＜30 冰点</span>
                <span className="text-border">·</span>
                <span className="text-xs max-sm:basis-full max-sm:hidden">顶部 1 张合成指数 + 9 张子卡 / duckdb 持久化 / 工作日自动更新</span>
              </div>
              <div className="min-h-[340px] max-sm:min-h-[420px] flex-1">
                <SentimentOverlay
                  data={sentimentPoints}
                  height="100%"
                  shOverlay={shOverlay}
                  mainNetFlowOverlay={mainNetFlowOverlay}
                  amountOverlay={amountOverlay}
                />
              </div>
            </div>
            {/* 下 1/4: 预留区 (后续接入) */}
            <div className="min-h-0 rounded-xl border border-dashed border-border/40 bg-background/40 flex items-center justify-center text-xs text-muted-foreground max-sm:hidden">
              预留区 · 下方 1/4
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
