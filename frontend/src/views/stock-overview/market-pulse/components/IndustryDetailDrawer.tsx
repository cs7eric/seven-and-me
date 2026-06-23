import { useEffect, useState } from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { notification } from "@/components/ui/notification"
import { fetchIndustryDetail } from "@/lib/api"

import { BAND, bandColor, bandFg, fmtAmount, fmtPct, fmtYi } from "../lib/format"
import type { IndustryDetail } from "../lib/types"

export function IndustryDetailDrawer({
  name,
  onClose,
}: {
  name: string | null
  onClose: () => void
}) {
  const [data, setData] = useState<IndustryDetail | null>(null)
  const visibleData = data?.name === name ? data : null
  const loading = Boolean(name) && visibleData == null

  useEffect(() => {
    if (!name) return
    let cancelled = false
    fetchIndustryDetail(name)
      .then((result) => {
        if (!cancelled) setData(result as IndustryDetail)
      })
      .catch((error) => {
        if (!cancelled) notification.error(`钻入失败: ${error?.message ?? error}`)
      })
    return () => {
      cancelled = true
    }
  }, [name])

  if (!name) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-slate-900/30 backdrop-blur-sm" onClick={onClose} />
      <div className="flex h-full w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-100 p-5">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">行业钻入</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="text-2xl font-semibold tracking-[-0.025em] text-slate-950">{name}</span>
              {visibleData?.changePct != null ? (
                <span
                  className="rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums"
                  style={{ background: bandColor(visibleData.changePct), color: bandFg(visibleData.changePct) }}
                >
                  {fmtPct(visibleData.changePct)}
                </span>
              ) : null}
            </div>
            {visibleData?.stockCount != null ? (
              <div className="mt-1 text-xs text-slate-500">
                共 {visibleData.stockCount} 家公司
                {visibleData.mainNet != null ? <> · 净流入 {fmtYi(visibleData.mainNet)}</> : null}
              </div>
            ) : null}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full">
            <X className="size-4" />
          </Button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {loading ? (
            <div className="p-10 text-center text-sm text-slate-500">加载中...</div>
          ) : !visibleData?.ok ? (
            <div className="p-10 text-center text-sm text-rose-500">{visibleData?.error ?? "暂无数据"}</div>
          ) : (
            <>
              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">领涨股</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-[11px] text-slate-500">名称</div>
                      <div className="mt-0.5 font-semibold text-slate-900">{visibleData.leadingStock ?? "—"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-slate-500">当日涨跌幅</div>
                    <div
                      className="mt-0.5 font-semibold tabular-nums"
                      style={{
                        color:
                           bandColor(visibleData.leadingChangePct) === BAND.flat
                             ? "#475569"
                             : bandColor(visibleData.leadingChangePct),
                       }}
                     >
                       {fmtPct(visibleData.leadingChangePct)}
                     </div>
                   </div>
                   {visibleData.leadingQuote ? (
                     <>
                      <div>
                        <div className="text-[11px] text-slate-500">最新价</div>
                        <div className="mt-0.5 tabular-nums">
                          {(visibleData.leadingQuote.lastPrice as number | null)?.toFixed?.(2) ?? "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] text-slate-500">成交额</div>
                        <div className="mt-0.5 tabular-nums">{fmtAmount(visibleData.leadingQuote.amount as number)}</div>
                      </div>
                    </>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">30 天主力净流入走势 (领涨股)</CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    数据源 eltdx 200742 · seed = {visibleData.leadingFlowSeed ?? "—"}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {!visibleData.leadingFlow30d?.length ? (
                    <div className="p-6 text-center text-xs text-slate-500">暂无数据</div>
                  ) : (
                    <FlowMiniChart rows={visibleData.leadingFlow30d} />
                  )}
                </CardContent>
              </Card>

              {visibleData.leadingKLine && visibleData.leadingKLine.length > 0 ? (
                <Card className="rounded-xl border-slate-200">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold text-slate-900">60 日 K 线 (领涨股)</CardTitle>
                    <CardDescription className="text-xs text-slate-500">{visibleData.leadingKLine.length} bars</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <KLineMini bars={visibleData.leadingKLine} />
                  </CardContent>
                </Card>
              ) : null}

              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">成分股</CardTitle>
                </CardHeader>
                <CardContent>
                  {visibleData.constituents && visibleData.constituents.length > 0 ? (
                    <div className="text-sm text-slate-700">成分股列表 (待接入)</div>
                  ) : (
                    <div className="text-xs text-slate-500">
                      akshare 90 行业接口不返回成分股列表; 当前显示 {visibleData.stockCount ?? "—"} 家公司数
                      {visibleData.leadingStock ? (
                        <> + 1 只领涨股 = <span className="font-semibold text-slate-700">{visibleData.leadingStock}</span></>
                      ) : null}
                      <br />
                      <span className="text-slate-400">若需成分股明细, 需要接 tq/ths web 端接口或本地个股-行业映射表.</span>
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function FlowMiniChart({ rows }: { rows: Array<{ date?: string; mainNet?: number }> }) {
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(row.mainNet ?? 0)))

  return (
    <div className="flex h-32 items-end gap-1.5">
      {rows.slice(-30).map((row, index) => {
        const value = row.mainNet ?? 0
        const ratio = Math.abs(value) / maxAbs
        const height = Math.max(2, Math.round(ratio * 100))
        const isUp = value >= 0
        return (
          <div key={`${row.date ?? index}-${index}`} className="group relative flex h-full flex-1 items-end">
            <div
              className={`w-full rounded-t ${isUp ? "bg-red-500" : "bg-emerald-500"}`}
              style={{ height: `${height}%` }}
              title={`${row.date}  主力 ${fmtYi(value)}`}
            />
          </div>
        )
      })}
    </div>
  )
}

function KLineMini({ bars }: { bars: Array<Record<string, unknown>> }) {
  const closes = bars.map((bar) => Number(bar.close) || 0).filter((value) => value > 0)
  if (closes.length < 2) {
    return <div className="p-6 text-center text-xs text-slate-500">K 线数据不足</div>
  }

  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const width = 100 / closes.length

  return (
    <div className="flex h-32 items-end">
      {closes.map((close, index) => {
        const ratio = max === min ? 0.5 : (close - min) / (max - min)
        return (
          <div key={index} className="flex-1" style={{ width: `${width}%` }}>
            <div
              className="mx-auto h-24 w-1 rounded"
              style={{
                background: index === 0 ? "#94a3b8" : closes[index] >= closes[index - 1] ? "#ef4444" : "#22c55e",
                height: `${Math.max(8, ratio * 96)}px`,
              }}
              title={`#${index} close=${close.toFixed(2)}`}
            />
          </div>
        )
      })}
    </div>
  )
}
