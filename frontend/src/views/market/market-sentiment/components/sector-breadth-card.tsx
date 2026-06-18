/**
 * Card 4: Sector Breadth
 */
import { useEffect, useState } from "react"
import { Layers } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sparkline } from "./sparkline"
import { SubCardSkeleton } from "./skeletons"
import { toSparkData } from "../lib/spark"
import { isoDateNDaysAgo } from "../lib/date"
import {
  fetchMarketSentimentSectorBreadth,
  fetchMarketSentimentSectorBreadthHistory,
  type SectorBreadthItem,
} from "@/lib/api"

export function SectorBreadthCard({ date }: { date: string | null }) {
  const [data, setData] = useState<SectorBreadthItem | null>(null)
  const [history, setHistory] = useState<SectorBreadthItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentSectorBreadth(date ?? undefined),
          fetchMarketSentimentSectorBreadthHistory(30, end),
        ])
        if (cancelled) return
        if (snap.ok && snap.total > 0) {
          setData({
            tradeDate: snap.tradeDate,
            advancing: snap.advancing,
            declining: snap.declining,
            flat: snap.flat,
            total: snap.total,
            advancePct: snap.advancePct,
            source: snap.source,
            elapsedMs: snap.elapsedMs,
            fromCache: snap.fromCache,
          })
        } else {
          setData(null)
        }
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

  const advPct = data ? data.advancePct * 100 : null
  // score 优先用后端返回的 0-100 (advancePct × 100), fallback 同样算法
  const score100 = data?.score ?? advPct
  const tone =
    score100 == null
      ? "text-slate-700"
      : score100 >= 50
        ? "text-red-600"
        : score100 >= 30
          ? "text-amber-600"
          : "text-emerald-600"
  const sparkData = toSparkData(
    history,
    (it) => it.score ?? it.advancePct * 100,
  )

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-muted-foreground" />
          Sector Breadth
        </CardTitle>
        <CardDescription>
          同花顺 90 行业 上涨数 / 总数
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
                {advPct == null ? "—" : `${advPct.toFixed(1)}%`}
              </span>
              {data && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {data.advancing}/{data.total}
                </span>
              )}
            </div>

            {data && (
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-muted-foreground">
                <span>
                  上涨 <span className="ml-1 text-red-600">{data.advancing}</span>
                </span>
                <span>
                  下跌 <span className="ml-1 text-emerald-600">{data.declining}</span>
                </span>
                {data.flat > 0 && (
                  <span>
                    平盘 <span className="ml-1 text-foreground">{data.flat}</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => `${v.toFixed(1)}%`} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日 advance_pct</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}