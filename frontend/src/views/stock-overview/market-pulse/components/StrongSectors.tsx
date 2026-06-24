import { Flame, TrendingUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

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
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M1</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <Flame className="mr-2 inline-block size-5 text-orange-500" />
              强势板块
            </CardTitle>
            <CardDescription className="mt-1 text-sm text-slate-500">
              akshare 同花顺 90 行业当日涨跌幅排序 · 点击卡片钻入
            </CardDescription>
          </div>
          <Badge variant="outline" className="w-fit rounded-full px-3 py-1 text-xs text-slate-500">
            <TrendingUp className="mr-1 size-3" /> 共 {data?.count ?? top.length + bottom.length} 行业
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-5">
        <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {top.map((sector) => (
            <div
              key={sector.name}
              onClick={() => onPick(sector.name)}
              className="group flex min-w-0 cursor-pointer flex-col justify-between rounded-xl border border-slate-200/60 bg-white p-2.5 transition-shadow hover:border-slate-300 hover:shadow-md sm:p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-xs font-semibold text-slate-900 sm:text-sm">{sector.name}</div>
                  {sector.leadingStock ? (
                    <div className="mt-0.5 hidden text-[11px] text-slate-500 sm:block">
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
                  className="rounded-md px-2 py-0.5 text-[10px] font-semibold tabular-nums sm:text-xs"
                  style={{
                    background: bandColor(sector.changePercent),
                    color: bandFg(sector.changePercent),
                  }}
                >
                  {fmtPct(sector.changePercent)}
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[10px] text-slate-500 sm:mt-2 sm:text-[11px]">
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
          <Tabs defaultValue="top" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="top" className="text-xs">领涨</TabsTrigger>
              <TabsTrigger value="bottom" className="text-xs">领跌</TabsTrigger>
            </TabsList>
            <TabsContent value="top" className="mt-3">
              <div className="flex flex-wrap gap-2">
                {top.slice(0, 6).map((sector) => (
                  <button
                    key={`top-${sector.name}`}
                    onClick={() => onPick(sector.name)}
                    className="inline-flex max-w-full items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs transition-colors hover:border-slate-300 hover:bg-slate-100"
                  >
                    <span className="truncate text-slate-700">{sector.name}</span>
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
            </TabsContent>
            <TabsContent value="bottom" className="mt-3">
              <div className="flex flex-wrap gap-2">
                {bottom.slice(0, 6).map((sector) => (
                  <button
                    key={`bottom-${sector.name}`}
                    onClick={() => onPick(sector.name)}
                    className="inline-flex max-w-full items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs transition-colors hover:border-slate-300 hover:bg-slate-100"
                  >
                    <span className="truncate text-slate-700">{sector.name}</span>
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
            </TabsContent>
          </Tabs>
        </div>
      </CardContent>
    </Card>
  )
}
