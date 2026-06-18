/**
 * Card 5: Turnover Activity (成交活跃度)
 */
import { useEffect, useState } from "react"
import { Activity } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentTurnoverActivity,
  fetchMarketSentimentTurnoverActivityHistory,
  type TurnoverActivityResponse,
  type TurnoverActivityHistoryItem,
} from "@/lib/api"

export function TurnoverActivityCard({ date }: { date: string | null }) {
  const [data, setData] = useState<TurnoverActivityResponse | null>(null)
  const [history, setHistory] = useState<TurnoverActivityHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentTurnoverActivity(date ?? undefined),
          fetchMarketSentimentTurnoverActivityHistory(start, end),
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
  const totalAmount = data?.totalAmount ?? null
  const avgAmount = data?.avg20dAmount ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-slate-500"
  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          成交活跃度
        </CardTitle>
        <CardDescription>
          今日成交额 / 过去 20 日平均成交额 · 历史分位
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <SubCardSkeleton />
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score == null ? "—" : score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                成交额 {(rawValue * 100).toFixed(0)}% · 高于过去3年{score!.toFixed(0)}%的时间
              </div>
            )}

            {(totalAmount != null || avgAmount != null) && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                {totalAmount != null && (
                  <span>
                    今日
                    <span className="ml-1 text-foreground">{totalAmount.toFixed(0)}亿</span>
                  </span>
                )}
                {avgAmount != null && (
                  <span>
                    20日均
                    <span className="ml-1 text-foreground">{avgAmount.toFixed(0)}亿</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} color="neutral" formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分 (历史分位)</div>
            </div>

            <div className="mt-2 text-[10px] leading-4 text-muted-foreground">
              阈值: ≥70 放量 (红) · 中性 (slate) · &lt;40 缩量
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}