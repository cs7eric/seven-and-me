import { ArrowDownRight, ArrowUpRight, Layers } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { bandColor, bandFg, cardChrome, fmtPct } from "../lib/format"
import type { FlowRow, MarketPulse } from "../lib/types"
import { EmptyCard } from "./EmptyCard"

export function CapitalFlow({
  data,
  onPick,
}: {
  data: MarketPulse["flow"] | undefined
  onPick: (name: string) => void
}) {
  const inflow = data?.inflow ?? []
  const outflow = data?.outflow ?? []

  if (!inflow.length && !outflow.length) {
    return <EmptyCard title="行业主力净流入" description="暂无数据" />
  }

  const maxAbs = Math.max(
    ...inflow.map((item) => Math.abs(item.mainNet)),
    ...outflow.map((item) => Math.abs(item.mainNet)),
    1
  )

  return (
    <Card className={cardChrome}>
      <CardHeader className="border-b border-slate-100 pb-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M2</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <Layers className="mr-2 inline-block size-5 text-rose-500" />
              行业主力净流入
            </CardTitle>
            <CardDescription className="mt-1 text-sm text-slate-500">
              akshare 同花顺 90 行业资金流 · 单位: 亿 · 点击行业名钻入
            </CardDescription>
          </div>
          <Badge variant="outline" className="rounded-full px-3 py-1 text-xs text-slate-500">
            流入 {data?.inflowCount ?? inflow.length} / 流出 {data?.outflowCount ?? outflow.length}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-5 md:grid-cols-2">
        <FlowColumn title="净流入" tone="up" rows={inflow} maxAbs={maxAbs} onPick={onPick} />
        <FlowColumn title="净流出" tone="down" rows={outflow} maxAbs={maxAbs} onPick={onPick} />
      </CardContent>
    </Card>
  )
}

function FlowColumn({
  title,
  tone,
  rows,
  maxAbs,
  onPick,
}: {
  title: string
  tone: "up" | "down"
  rows: FlowRow[]
  maxAbs: number
  onPick: (name: string) => void
}) {
  const isUp = tone === "up"

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
      <div className={`mb-3 flex items-center gap-2 text-sm font-semibold ${isUp ? "text-red-700" : "text-emerald-700"}`}>
        {isUp ? <ArrowUpRight className="size-4" /> : <ArrowDownRight className="size-4" />}
        {title} ({rows.length})
      </div>
      <div className="max-h-[28rem] space-y-2.5 overflow-y-auto pr-1">
        {rows.map((row) => {
          const width = Math.max(6, Math.min(100, (Math.abs(row.mainNet) / maxAbs) * 100))
          return (
            <div key={row.name} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <button onClick={() => onPick(row.name)} className="font-medium text-slate-800 hover:underline">
                    {row.name}
                  </button>
                  {row.changePct != null ? (
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
                      style={{ background: bandColor(row.changePct), color: bandFg(row.changePct) }}
                    >
                      {fmtPct(row.changePct)}
                    </span>
                  ) : null}
                  {typeof row.stockCount === "number" ? (
                    <span className="text-[10px] text-slate-400">{row.stockCount}只</span>
                  ) : null}
                  {row.leadingStock ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
                      领涨
                      <span className="font-semibold text-slate-800">{row.leadingStock}</span>
                      {row.leadingChangePct != null ? (
                        <span
                          className="tabular-nums"
                          style={{
                            color:
                              bandColor(row.leadingChangePct) === "#9E9E9E"
                                ? "#475569"
                                : bandColor(row.leadingChangePct),
                          }}
                        >
                          {fmtPct(row.leadingChangePct)}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-2 tabular-nums">
                  <span className={`font-semibold ${isUp ? "text-red-700" : "text-emerald-700"}`}>
                    {isUp ? "+" : ""}
                    {row.mainNet.toFixed(2)}亿
                  </span>
                </div>
              </div>
              <div className="relative h-2 rounded-full bg-slate-200/70">
                <div
                  className={`absolute top-0 h-2 rounded-full ${isUp ? "bg-red-500" : "bg-emerald-500"}`}
                  style={{ width: `${width}%`, left: isUp ? 0 : "auto", right: isUp ? "auto" : 0 }}
                />
              </div>
              {row.inflow != null || row.outflow != null ? (
                <div className="flex items-center gap-2 text-[10px] text-slate-500 tabular-nums">
                  <span>流入 {row.inflow?.toFixed(2) ?? "—"}亿</span>
                  <span>流出 {row.outflow?.toFixed(2) ?? "—"}亿</span>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
