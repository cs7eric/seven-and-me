import { useMemo } from "react"
import { TrendingUp } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { bandColor, bandFg, cardChrome, fmtPct, prettyDate, weekday } from "../lib/format"
import type { RotationTrendData } from "../lib/types"

export function RotationTrend({
  data,
  onPick,
}: {
  data: RotationTrendData | null
  onPick: (name: string) => void
}) {
  const dates = data?.dates ?? []
  const filtered = useMemo(
    () => (data?.industries ?? []).filter((item) => item.appearances >= 1).slice(0, 30),
    [data?.industries],
  )
  const tableMinWidth = 320 + dates.length * 72

  if (!filtered.length) {
    return (
      <Card className={cardChrome}>
        <CardHeader className="border-b border-slate-100 pb-5">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M4</div>
            <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              <TrendingUp className="mr-2 inline-block size-5 text-cyan-500" />
              行业轮动历史趋势
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-10 text-center text-sm text-slate-500">
          历史数据不足. 后端 scheduler 每天 15:30 落盘当日快照, 累计 N 天后此视图自动填充.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={cardChrome}>
      <CardHeader className="border-b border-slate-100 pb-5">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">M4</div>
          <CardTitle className="mt-1 text-xl font-semibold tracking-[-0.025em] text-slate-950">
            <TrendingUp className="mr-2 inline-block size-5 text-cyan-500" />
            行业轮动历史趋势
          </CardTitle>
          <CardDescription className="mt-1 text-sm text-slate-500">
            近 {dates.length} 个交易日 · 行业出现频次 / 排名迁移 / 涨跌幅序列 · 数据源: 15:30 落盘快照
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm" style={{ minWidth: `${tableMinWidth}px` }}>
            <colgroup>
              <col className="w-44" />
              <col className="w-16" />
              <col className="w-16" />
              <col className="w-16" />
              <col className="w-16" />
              {dates.map((date) => (
                <col key={date} className="w-[4.5rem]" />
              ))}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 text-xs">
                <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">行业</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">出现</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">最佳</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">平均</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">最新</th>
                {dates.map((date) => (
                  <th key={date} className="border-l border-slate-100 px-2 py-2 text-center text-[10px] font-semibold text-slate-500">
                    <div className="flex flex-col items-center">
                      <span>{prettyDate(date)}</span>
                      <span className="text-[9px] font-normal text-slate-400">{weekday(date)}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((industry) => (
                <tr key={industry.name} className="border-b border-slate-50">
                  <td className="px-3 py-2">
                    <button onClick={() => onPick(industry.name)} className="text-left text-sm font-medium text-slate-900 hover:underline">
                      {industry.name}
                    </button>
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">
                    {industry.appearances}/{dates.length}
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">{industry.bestRank ?? "—"}</td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">{industry.avgRank ?? "—"}</td>
                  <td className="px-2 py-2 text-center">
                    {industry.latestRank == null ? (
                      <span className="text-xs text-slate-400">未上榜</span>
                    ) : (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700 tabular-nums">
                        {industry.latestRank}
                      </span>
                    )}
                  </td>
                  {dates.map((date, index) => {
                    const rank = industry.ranks?.[index]
                    const changePct = industry.changePcts?.[index]
                    if (rank == null) {
                      return (
                        <td key={date} className="border-l border-slate-100 px-2 py-2 text-center text-[10px] text-slate-300">
                          —
                        </td>
                      )
                    }
                    return (
                      <td key={date} className="border-l border-slate-100 px-1 py-1.5">
                        <div
                          className="flex h-9 flex-col items-center justify-center rounded-md px-1 text-center"
                          style={{ background: bandColor(changePct), color: bandFg(changePct) }}
                          title={`${date} 排名 ${rank} ${fmtPct(changePct)}`}
                        >
                          <div className="text-[10px] font-semibold tabular-nums">#{rank}</div>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
