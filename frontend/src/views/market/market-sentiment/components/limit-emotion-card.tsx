/**
 * Card 6: Limit Emotion Summary
 */
import { useEffect, useState } from "react"
import { Flame } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { LEVEL_META, SubMetric } from "./sub-metric"
import { cn } from "@/lib/utils"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentLimitEmotionSummary,
  fetchMarketSentimentLimitEmotionSummaryHistory,
  type LimitEmotionSummary,
  type LimitEmotionSummaryHistoryItem,
} from "@/lib/api"

export function LimitEmotionCard({ date }: { date: string | null }) {
  const [data, setData] = useState<LimitEmotionSummary | null>(null)
  const [history, setHistory] = useState<LimitEmotionSummaryHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentLimitEmotionSummary(date ?? undefined),
          fetchMarketSentimentLimitEmotionSummaryHistory(start, end),
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

  const sparkData = toSparkData(history, (it) => it.compositeScore)
  const level = data?.level ?? "weak"
  const meta = LEVEL_META[level] ?? LEVEL_META.weak
  const composite = data?.compositeScore ?? null

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="size-4 text-muted-foreground" />
          涨跌停情绪综合分
        </CardTitle>
        <CardDescription>
          涨跌停比 40% · 炸板率 30% (反向) · 昨日涨停收益 30%
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <SubCardSkeleton />
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${meta.tone}`}>
                {composite == null ? "—" : composite.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">综合分</span>
              <span
                className={cn(
                  "ml-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  meta.chip
                )}
              >
                {meta.label}
              </span>
            </div>

            {data && (
              <div className="mt-3 grid grid-cols-3 gap-2">
                <SubMetric
                  title="涨跌停比"
                  value={`${data.limitUpCount}/${Math.max(data.limitDownCount, 1)}`}
                  subValue={
                    data.limitUpDownRatio == null ? null : `${data.limitUpDownRatio.toFixed(1)}:1`
                  }
                  score={data.components?.upDownScore ?? null}
                />
                <SubMetric
                  title="炸板率"
                  value={
                    data.breakBoardRate == null
                      ? "—"
                      : `${(data.breakBoardRate * 100).toFixed(1)}%`
                  }
                  subValue={`${data.brokenCount}/${data.touchedCount}`}
                  score={data.components?.breakBoardScore ?? null}
                  invertTone
                />
                <SubMetric
                  title="昨日涨停收益"
                  value={
                    data.yesterdayLimitUpAvgReturn == null
                      ? "—"
                      : `${data.yesterdayLimitUpAvgReturn > 0 ? "+" : ""}${data.yesterdayLimitUpAvgReturn.toFixed(2)}%`
                  }
                  subValue={`n=${data.yesterdayLimitUpCount}`}
                  score={data.components?.yesterdayReturnScore ?? null}
                />
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日综合分</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}