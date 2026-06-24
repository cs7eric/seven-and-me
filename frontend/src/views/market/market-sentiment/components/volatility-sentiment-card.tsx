/**
 * Card 7: Volatility Sentiment
 */
import { useEffect, useState } from "react"
import { Activity } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import { cn } from "@/lib/utils"
import {
  fetchMarketSentimentVolatilitySentiment,
  fetchMarketSentimentVolatilitySentimentHistory,
  type VolatilitySentimentResponse,
  type VolatilitySentimentItem,
} from "@/lib/api"

export function VolatilitySentimentCard({ date }: { date: string | null }) {
  const [data, setData] = useState<VolatilitySentimentResponse | null>(null)
  const [history, setHistory] = useState<VolatilitySentimentItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentVolatilitySentiment(date ?? undefined),
          fetchMarketSentimentVolatilitySentimentHistory(start, end),
        ])
        if (cancelled) return
        setData(snap.ok ? snap : null)
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
    return () => {
      cancelled = true
    }
  }, [date])

  const score = data?.sentimentScore ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-emerald-600"
        : score >= 40
          ? "text-slate-700"
          : "text-red-600"
  const sparkData = toSparkData(history, (it) => it.sentimentScore)
  const vol = data?.realizedVol20d ?? null
  const pct = data?.percentile1y ?? null
  const dailyRet = data?.dailyReturnPct ?? null
  const dailyRetText =
    dailyRet == null ? null : `${dailyRet > 0 ? "+" : ""}${dailyRet.toFixed(2)}%`
  const dailyRetTone =
    dailyRet == null
      ? "text-foreground"
      : dailyRet > 0
        ? "text-red-600"
        : dailyRet < 0
          ? "text-emerald-600"
          : "text-foreground"

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          Volatility Sentiment
        </CardTitle>
        <CardDescription>
          沪深300 20 日年化波动率 → 1 年分位 → 反向得分 (高分=平静)
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <SubCardSkeleton />
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className={`text-3xl font-semibold tabular-nums max-sm:text-2xl ${tone}`}>
                {score == null ? "—" : score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">情绪得分</span>
            </div>

            {(vol != null || pct != null || dailyRet != null) && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                {vol != null && (
                  <span>
                    vol
                    <span className="ml-1 text-foreground">{vol.toFixed(2)}%</span>
                  </span>
                )}
                {pct != null && (
                  <span>
                    pct
                    <span className="ml-1 text-foreground">{(pct * 100).toFixed(0)}%</span>
                  </span>
                )}
                {dailyRetText && (
                  <span>
                    当日
                    <span className={cn("ml-1", dailyRetTone)}>{dailyRetText}</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                color="inverse"
                formatter={(v) => v.toFixed(1)}
              />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
