/**
 * Card 8: Style Risk Appetite (风格风险偏好)
 *
 * 风格强弱 = 中证1000 近5日收益率 - 沪深300 近5日收益率
 * spread > 0: 小盘更强 (风险偏好积极), spread < 0: 大盘更强 (避险)
 */
import { useEffect, useState } from "react"
import { Scale } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo, shiftIsoDays } from "../lib/date"
import {
  fetchMarketSentimentStyleRiskAppetite,
  fetchMarketSentimentStyleRiskAppetiteHistory,
  type StyleRiskAppetiteResponse,
  type StyleRiskAppetiteHistoryItem,
} from "@/lib/api"

export function StyleRiskAppetiteCard({ date }: { date: string | null }) {
  const [data, setData] = useState<StyleRiskAppetiteResponse | null>(null)
  const [history, setHistory] = useState<StyleRiskAppetiteHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentStyleRiskAppetite(date ?? undefined),
          fetchMarketSentimentStyleRiskAppetiteHistory(start, end),
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
  const rawValue = data?.rawValue ?? null
  const hs300Return = data?.hs300?.returnPct ?? null
  const csi1000Return = data?.csi1000?.returnPct ?? null

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-emerald-600"
  const directionLabel =
    score == null ? ""
      : score >= 70 ? "小盘强 ↑"
      : score <= 30 ? "大盘强 ↓"
      : "中性"

  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Scale className="size-4 text-muted-foreground" />
          风格风险偏好
        </CardTitle>
        <CardDescription>
          中证1000 5日收益 - 沪深300 5日收益 · 历史分位
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
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className={`text-3xl font-semibold tabular-nums max-sm:text-2xl ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
              {directionLabel && (
                <span className={`text-xs font-medium ${tone}`}>{directionLabel}</span>
              )}
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                中证1000 - 沪深300: {rawValue >= 0 ? "+" : ""}{rawValue.toFixed(2)}%
                <span> · 高于过去3年{score.toFixed(0)}%的时间</span>
              </div>
            )}

            <div className="mt-2 space-y-0.5 text-xs text-muted-foreground tabular-nums">
              <div>
                沪深300: {hs300Return != null ? `${hs300Return >= 0 ? "+" : ""}${hs300Return.toFixed(2)}%` : "—"}
              </div>
              <div>
                中证1000: {csi1000Return != null ? `${csi1000Return >= 0 ? "+" : ""}${csi1000Return.toFixed(2)}%` : "—"}
              </div>
            </div>

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>

            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥70 小盘强</span>
              <span className="text-slate-400">40-70 中性</span>
              <span className="text-emerald-600/70">≤30 大盘强</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
