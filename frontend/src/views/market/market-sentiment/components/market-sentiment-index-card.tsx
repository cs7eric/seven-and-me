/**
 * Top Card: Market Sentiment Index (composite, 9 张卡加权合成)
 */
import { useEffect, useState } from "react"
import { Activity, Smile } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Calendar as CalendarUi } from "@/components/ui/calendar"
import { cn } from "@/lib/utils"
import { toLocalDate, toLocalIso } from "@/lib/date-utils"
import { SentimentLine } from "./sentiment-line"
import { CompositeCardSkeleton } from "./skeletons"
import { MSI_LEVEL_META } from "./sub-metric"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentIndex,
  fetchMarketSentimentIndexHistory,
  type MarketSentimentIndexResponse,
  type MarketSentimentIndexHistoryItem,
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
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentIndex(date ?? undefined),
          fetchMarketSentimentIndexHistory(start, end),
        ])
        if (cancelled) return
        setData(snap)
        setHistory(hist.items ?? [])
      } catch {
        if (!cancelled) {
          setData(null)
          setHistory(null)
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

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 55
          ? "text-orange-600"
          : score >= 45
            ? "text-slate-700"
            : score >= 30
              ? "text-blue-600"
              : "text-slate-400"

  // ECharts 折线: 完整 ISO 日期 + value, visualMap 按 value 自动上色
  const sentimentPoints = (history ?? [])
    .slice()
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
    .map((it) => ({
      date: it.tradeDate.slice(5),
      value: it.compositeScore ?? 50,
      level: it.level,
    }))

  return (
    <Card className="border-0 shadow-none bg-muted/50 h-full">
      <CardContent className="h-full">
        {loading ? (
          <CompositeCardSkeleton />
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="grid h-full grid-rows-[3fr_1fr] gap-3">
            {/* 上 3/4: 折线图区 */}
            <div className="flex min-h-0 flex-col gap-2">
              <div className="inline-flex items-center gap-2 rounded-full bg-background px-3 py-1 text-xs font-medium text-muted-foreground self-start">
                <Smile className="size-3.5" />
                Market Sentiment
              </div>
              <div className="flex items-end gap-3">
                <span className={`text-5xl font-semibold tabular-nums ${tone}`}>
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
                  <span className="ml-1 inline-flex items-center gap-1 text-xs text-muted-foreground tabular-nums">
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          type="button"
                          aria-label="选择历史日期"
                          className="inline-flex items-center text-xs text-muted-foreground tabular-nums underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm"
                        >
                          {date ?? data.tradeDate}
                        </button>
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0" align="start">
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
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Activity className="size-3.5" />
                <span>实时情绪指标</span>
                <span className="text-red-600/70">≥70 极热</span>
                <span className="text-orange-600/70">60-70 偏热</span>
                <span className="text-amber-600/70">50-60 偏多</span>
                <span className="text-sky-500/80">40-50 偏弱</span>
                <span className="text-blue-600/70">30-40 低迷</span>
                <span className="text-slate-400">＜30 冰点</span>
                <span className="text-border">·</span>
                <span className="text-xs">顶部 1 张合成指数 + 9 张子卡 / duckdb 持久化 / 工作日自动更新</span>
              </div>
              <div className="min-h-0 flex-1">
                <SentimentLine data={sentimentPoints} height="100%" />
              </div>
            </div>

            {/* 下 1/4: 预留区 (后续接入) */}
            <div className="min-h-0 rounded-xl border border-dashed border-border/40 bg-background/40 flex items-center justify-center text-xs text-muted-foreground">
              预留区 · 下方 1/4
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}