/**
 * Card 2: Market Breadth (4 张子卡)
 */
import { useEffect, useState } from "react"
import { Layers } from "lucide-react"
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

export function MarketBreadthCard({ date }: { date: string | null }) {
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

  const w1 = 0.40, w2 = 0.35, w3 = 0.25
  const adv = data?.pctAdvancing ?? 0
  const ma20 = data?.pctAboveMa20 ?? 0
  const ma60 = data?.pctAboveMa60 ?? 0
  const rawComposite = w1 * adv + w2 * ma20 + w3 * ma60
  // 优先用后端 percentile score (跟 MSI 一致), 无则 fallback 本地 raw 值
  const composite = data?.breadthScore ?? rawComposite

  const tone =
    composite == null || data == null
      ? "text-slate-700"
      : composite >= 70
        ? "text-red-600"
        : composite >= 40
          ? "text-amber-600"
          : "text-emerald-600"
  const levelLabel =
    composite >= 70 ? "强势" : composite >= 40 ? "中性" : "弱势"
  const levelBadge =
    composite >= 70
      ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
      : composite >= 40
        ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"

  const sparkData = toSparkData(
    history,
    (it) => it.breadthScore ?? (w1 * (it.pctAdvancing ?? 0) + w2 * (it.pctAboveMa20 ?? 0) + w3 * (it.pctAboveMa60 ?? 0)),
  )

  const rows: Array<{ label: string; pct: number; weight: number }> = [
    { label: "上涨占比", pct: adv, weight: w1 * 100 },
    { label: "MA20 占比", pct: ma20, weight: w2 * 100 },
    { label: "MA60 占比", pct: ma60, weight: w3 * 100 },
  ]

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-muted-foreground" />
          Market Breadth
        </CardTitle>
        <CardDescription>
          加权合成: 40%上涨 + 35%MA20 + 25%MA60
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <SubCardSkeleton />
        ) : data == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="space-y-3">
            {/* 综合得分 */}
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className={`text-3xl font-semibold tabular-nums max-sm:text-2xl ${tone}`}>
                {composite.toFixed(1)}
              </span>
              <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${levelBadge}`}>
                {levelLabel}
              </span>
            </div>

            {/* 子项 */}
            <div className="space-y-1.5">
              {rows.map((r) => (
                <div key={r.label} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <span className="w-16 shrink-0 text-muted-foreground">{r.label}</span>
                  <div className="flex-1 h-2 rounded-full bg-muted/30 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-foreground/20 transition-all"
                      style={{ width: `${Math.min(r.pct, 100)}%` }}
                    />
                  </div>
                  <span className="w-12 shrink-0 text-right tabular-nums text-foreground/80">
                    {r.pct.toFixed(1)}%
                  </span>
                  <span className="w-8 shrink-0 text-right text-muted-foreground">{r.weight}%</span>
                </div>
              ))}
            </div>

            {/* Sparkline */}
            <div className="-mx-1">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => `${v.toFixed(1)}分`}
              />
            </div>

            {/* 等级说明 */}
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥70 强势</span>
              <span className="text-amber-600/70">40-70 中性</span>
              <span className="text-emerald-600/70">＜40 弱势</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
