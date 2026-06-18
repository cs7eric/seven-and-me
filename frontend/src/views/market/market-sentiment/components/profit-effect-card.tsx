/**
 * Card 9: Profit Effect (赚钱效应) — 市场情绪指数分项④
 *
 * score = 60% × 近5日上涨占比 + 40% × (100 - 60日新低占比)
 * score ≥ 60 → 赚钱面宽, score ≥ 40 → 中性, < 40 → 亏钱效应
 */
import { useEffect, useState } from "react"
import { Activity } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentProfitEffect,
  fetchMarketSentimentProfitEffectHistory,
  type ProfitEffectResponse,
  type ProfitEffectHistoryItem,
} from "@/lib/api"

export function ProfitEffectCard({ date }: { date: string | null }) {
  const [data, setData] = useState<ProfitEffectResponse | null>(null)
  const [history, setHistory] = useState<ProfitEffectHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentProfitEffect(date ?? undefined),
          fetchMarketSentimentProfitEffectHistory(start, end),
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

  const score = data?.score ?? null
  const up5dPct = data?.up5dPct ?? null
  const newLow60dPct = data?.newLow60dPct ?? null

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 60
        ? "text-red-600"
        : score >= 40
          ? "text-amber-600"
          : "text-emerald-600"

  const levelLabel =
    score == null ? ""
      : score >= 60 ? "赚钱面宽"
      : score >= 40 ? "中性"
      : "亏钱效应"

  const sparkData = toSparkData(history, (it) => it.score)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          市场情绪指数分项④：赚钱效应
        </CardTitle>
        <CardDescription>
          60%×近5日上涨 + 40%×(100-60日新低)
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
            <div className="flex items-baseline gap-3">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className={`text-xs font-medium ${tone}`}>{levelLabel}</span>
            </div>

            <div className="mt-2 space-y-0.5 text-xs text-muted-foreground tabular-nums">
              <div>近5日上涨占比: {up5dPct != null ? `${up5dPct.toFixed(1)}%` : "—"}</div>
              <div>60日新低占比: {newLow60dPct != null ? `${newLow60dPct.toFixed(1)}%` : "—"}</div>
            </div>

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>

            <div className="mt-1 flex gap-3 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥60 赚钱面宽</span>
              <span className="text-amber-600/70">40-60 中性</span>
              <span className="text-emerald-600/70">＜40 亏钱效应</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}