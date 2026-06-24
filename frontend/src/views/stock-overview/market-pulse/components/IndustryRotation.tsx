import { Calendar, RefreshCcw, Shuffle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { BAND, bandColor, bandFg, cardChrome, fmtPct, prettyDate, weekday } from "../lib/format"
import type { MarketPulse, RotationRow } from "../lib/types"

export function IndustryRotation({
  data,
  onRefreshSnapshot,
  onPick,
}: {
  data: MarketPulse["rotation"] | undefined
  onRefreshSnapshot: () => void
  onPick: (name: string) => void
}) {
  const dates = data?.dates ?? []
  const rows: RotationRow[] = data?.rows ?? []
  const topN = data?.topN ?? rows[0]?.topN ?? 10

  if (!rows.length) {
    return (
      <Card className={cardChrome}>
        <CardHeader className="border-b border-slate-100 pb-5">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M3</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <Shuffle className="mr-2 inline-block size-5 text-indigo-500" />
              行业轮动 · 日 Top {topN}
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-10 text-center text-sm text-slate-500">
          暂无快照. 点击下方"刷新今日快照"先生成 {new Date().toISOString().slice(0, 10)}.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={cardChrome}>
      <CardHeader className="border-b border-slate-100 pb-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M3</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <Shuffle className="mr-2 inline-block size-5 text-indigo-500" />
              行业轮动 · 日 Top {topN}
            </CardTitle>
            <CardDescription className="mt-1 text-sm text-slate-500">
              每个交易日, 按 TDX 56 行业指数当日涨跌幅排序, 取前 {topN}。横轴日期 (最新在左), 纵轴排名。
            </CardDescription>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:flex sm:items-center">
            <Badge variant="outline" className="w-fit rounded-full px-3 py-1 text-xs text-slate-500">
              <Calendar className="mr-1 size-3" /> {dates[0]} ~ {dates[dates.length - 1]} · {dates.length} 个交易日
            </Badge>
            <Button variant="outline" size="sm" className="w-full rounded-xl sm:w-auto" onClick={onRefreshSnapshot}>
              <RefreshCcw className="mr-1.5 size-4" /> 刷新今日快照
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="min-w-[760px] table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-20" />
              {dates.map((date) => (
                <col key={date} />
              ))}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60">
                <th className="sticky left-0 z-10 bg-slate-50/95 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  排名
                </th>
                {dates.map((date) => (
                  <th
                    key={date}
                    className="border-l border-slate-100 px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500"
                  >
                    <div className="flex flex-col items-center gap-0.5">
                      <span>{prettyDate(date)}</span>
                      <span className="text-[10px] font-normal text-slate-400">{weekday(date)}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: topN }).map((_, index) => {
                const rank = index + 1
                return (
                  <tr key={rank} className="border-b border-slate-50">
                    <td className="sticky left-0 z-10 bg-white px-3 py-2 align-middle text-xs text-slate-500">
                      <div className="flex items-center gap-2">
                        <span className={`tabular-nums ${rank <= 3 ? "font-semibold text-slate-900" : "text-slate-500"}`}>
                          {rank}
                        </span>
                        {rank === 1 ? (
                          <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                            TOP
                          </span>
                        ) : null}
                      </div>
                    </td>
                    {dates.map((date) => {
                      const row = rows.find((item) => item.date === date)
                      const item = row?.items?.[index]
                      if (!item) {
                        return (
                          <td key={date} className="border-l border-slate-100 px-2 py-2 text-center text-slate-300">
                            —
                          </td>
                        )
                      }
                      return (
                        <td key={date} className="border-l border-slate-100 px-2 py-1.5">
                          <button
                            onClick={() => onPick(item.name)}
                            className="flex h-12 w-full flex-col items-center justify-center rounded-md px-1.5 text-center transition-opacity hover:opacity-80"
                            style={{ background: bandColor(item.changePct), color: bandFg(item.changePct) }}
                            title={`${item.name} 当日 ${fmtPct(item.changePct)}`}
                          >
                            <div className="truncate text-xs font-semibold leading-4">{item.name}</div>
                            <div className="text-[10px] font-medium tabular-nums leading-3.5 opacity-90">
                              {fmtPct(item.changePct)}
                            </div>
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50/40 px-4 py-3 text-[11px] text-slate-500">
          <span className="font-semibold text-slate-600">色阶:</span>
          {[
            { c: BAND.upExtreme, t: "≥+10%" },
            { c: BAND.upStrong, t: "+5~+10%" },
            { c: BAND.upMid, t: "+2~+5%" },
            { c: BAND.upLight, t: "+0.5~+2%" },
            { c: BAND.flat, t: "±0.5%" },
            { c: BAND.downLight, t: "-2~-0.5%" },
            { c: BAND.downMid, t: "-5~-2%" },
            { c: BAND.downStrong, t: "-10~-5%" },
            { c: BAND.downExtreme, t: "≤-10%" },
          ].map((band) => (
            <span key={band.t} className="inline-flex items-center gap-1.5">
              <span className="size-3 rounded-sm" style={{ background: band.c }} />
              <span className="tabular-nums">{band.t}</span>
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
