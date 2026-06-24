/**
 * Card 1: Risk Appetite Spread
 */
import { useEffect, useState } from "react"
import { TrendingUp } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentRiskAppetite,
  fetchMarketSentimentRiskAppetiteHistory,
  type RiskAppetiteResponse,
  type RiskAppetiteHistoryItem,
} from "@/lib/api"

export function RiskAppetiteCard({ date }: { date: string | null }) {
  const [data, setData] = useState<RiskAppetiteResponse | null>(null)
  const [history, setHistory] = useState<RiskAppetiteHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentRiskAppetite(date ?? undefined),
          fetchMarketSentimentRiskAppetiteHistory(start, end),
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
    return () => {
      cancelled = true
    }
  }, [date])

  const score = data?.score ?? null
  const rawValue = data?.rawValue ?? null
  const spread511010 = data?.spread?.["511010"] ?? null
  const spread511090 = data?.spread?.["511090"] ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-emerald-600"
  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingUp className="size-4 text-muted-foreground" />
          Risk Appetite Spread
        </CardTitle>
        <CardDescription>
          沪深300 20日 − (511010 + 511090) / 2 国债 ETF 20日
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
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs leading-5 tabular-nums text-muted-foreground">
                沪深300跑赢债券ETF {rawValue > 0 ? "+" : ""}{rawValue.toFixed(2)}%
                {score != null && <span> · 高于过去3年{score.toFixed(0)}%的时间</span>}
              </div>
            )}

            {(spread511010 != null || spread511090 != null) && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                {spread511010 != null && (
                  <span>
                    511010
                    <span className="ml-1 text-foreground">
                      {spread511010 > 0 ? "+" : ""}
                      {spread511010.toFixed(2)}%
                    </span>
                  </span>
                )}
                {spread511090 != null && (
                  <span>
                    511090
                    <span className="ml-1 text-foreground">
                      {spread511090 > 0 ? "+" : ""}
                      {spread511090.toFixed(2)}%
                    </span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分 (历史分位)</div>
            </div>

            <div className="mt-2 text-[10px] leading-4 text-muted-foreground">
              阈值: ≥70 risk-on (红) · 中性 (slate) · &lt;40 risk-off (绿)
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
