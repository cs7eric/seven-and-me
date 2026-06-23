import { Flame, TrendingUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { bandColor, bandFg, cardChrome, fmtPct, fmtYi } from "../lib/format"
import type { MarketPulse } from "../lib/types"
import { EmptyCard } from "./EmptyCard"

export function StrongSectors({
  data,
  onPick,
}: {
  data: MarketPulse["strong"] | undefined
  onPick: (name: string) => void
}) {
  const top = data?.top ?? []
  const bottom = data?.bottom ?? []

  if (!top.length) {
    return <EmptyCard title="强势板块" description="暂无数据" />
  }

  return (
    <Card className={cardChrome}>
      <CardHeader className="border-b border-slate-100 pb-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M1</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <Flame className="mr-2 inline-block size-5 text-orange-500" />
              强势板块
            </CardTitle>
            <CardDescription className="mt-1 text-sm text-slate-500">
              akshare 同花顺 90 行业当日涨跌幅排序 · 点击卡片钻入
            </CardDescription>
          </div>
          <Badge variant="outline" className="rounded-full px-3 py-1 text-xs text-slate-500">
            <TrendingUp className="mr-1 size-3" /> 共 {data?.count ?? top.length + bottom.length} 行业
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-5">
        <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          {top.map((sector) => (
            <div
              key={sector.name}
              onClick={() => onPick(sector.name)}
              className="group flex cursor-pointer flex-col justify-between rounded-xl border border-slate-200/60 bg-white p-3.5 transition-shadow hover:border-slate-300 hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-900">{sector.name}</div>
                  {sector.leadingStock ? (
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      领涨 <span className="font-medium text-slate-700">{sector.leadingStock}</span>
                      {sector.leadingChangePct != null ? (
                        <span
                          className="ml-1 tabular-nums"
                          style={{
                            color:
                              bandColor(sector.leadingChangePct) === "#9E9E9E"
                                ? "#475569"
                                : bandColor(sector.leadingChangePct),
                          }}
                        >
                          {fmtPct(sector.leadingChangePct)}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div
                  className="rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums"
                  style={{
                    background: bandColor(sector.changePercent),
                    color: bandFg(sector.changePercent),
                  }}
                >
                  {fmtPct(sector.changePercent)}
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                {typeof sector.stockCount === "number" ? (
                  <span className="tabular-nums">{sector.stockCount}只</span>
                ) : (
                  <span />
                )}
                <span className="tabular-nums">净额 {fmtYi(sector.amount)}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 border-t border-slate-100 pt-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">弱势</div>
          <div className="flex flex-wrap gap-2">
            {bottom.map((sector) => (
              <button
                key={`bottom-${sector.name}`}
                onClick={() => onPick(sector.name)}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs transition-colors hover:border-slate-300 hover:bg-slate-100"
              >
                <span className="text-slate-700">{sector.name}</span>
                <span
                  className="font-semibold tabular-nums"
                  style={{
                    color:
                      bandColor(sector.changePercent) === "#9E9E9E"
                        ? "#475569"
                        : bandColor(sector.changePercent),
                  }}
                >
                  {fmtPct(sector.changePercent)}
                </span>
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
