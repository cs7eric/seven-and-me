/**
 * Card 3: 252 日新高
 */
import { useEffect, useState } from "react"
import { TrendingUp } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentMaCount,
  fetchMarketSentimentMaCountHistory,
  type MaCountResponse,
  type MaCountHistoryItem,
} from "@/lib/api"

export function NewHigh252dCard({ date }: { date: string | null }) {
  const [data, setData] = useState<MaCountResponse | null>(null)
  const [history, setHistory] = useState<MaCountHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentMaCount(date ?? undefined),
          fetchMarketSentimentMaCountHistory(start, end),
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

  const total = data?.totalEligible ?? 0
  const pct = data?.pctNewHigh252d ?? null
  const cnt = data?.newHigh252dCount ?? null
  const score = data?.newHigh252dScore ?? null
  const rawValue = data?.newHigh252dRawValue ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-amber-600"
          : "text-slate-700"
  const sparkData = toSparkData(history, (it) => it.newHigh252dScore ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingUp className="size-4 text-muted-foreground" />
          252日新高
        </CardTitle>
        <CardDescription>
          创 252 日新高占比 · 历史分位
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <SubCardSkeleton />
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>
            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                {cnt} / {total} 只 ({rawValue.toFixed(1)}%)
                <span> · 高于过去3年{score.toFixed(0)}%的时间</span>
              </div>
            )}
            {total > 0 && cnt != null && !rawValue && (
              <div className="mt-1 text-xs text-muted-foreground">
                {cnt} / {total} 只
              </div>
            )}
            <div className="-mx-1 mt-2">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}