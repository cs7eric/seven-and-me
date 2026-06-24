import {
  ArrowDownRight,
  Calendar,
  ChevronRight,
  Clock,
  Flame,
  Layers,
  RefreshCcw,
  TrendingDown,
  TrendingUp,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

import { fmtPct, fmtYi } from "../lib/format"
import type { MarketPulse, SchedulerStatus } from "../lib/types"

export function PageHeader({
  onRefresh,
  loading,
  fetchedAt,
  flowElapsedMs,
  scheduler,
  market,
}: {
  onRefresh: () => void
  loading: boolean
  fetchedAt?: string
  flowElapsedMs?: number
  scheduler?: SchedulerStatus | null
  market?: MarketPulse | null
}) {
  const isTradeTime = scheduler?.isTradeTime
  const isTradingDay = scheduler?.isTradingDay
  const tradeDate = market?.strong?.tradeDate ?? market?.rotation?.tradeDate
  const requestedTradeDate =
    market?.strong?.requestedTradeDate ?? market?.rotation?.requestedTradeDate
  const isFallbackTradeDate = Boolean(
    market?.strong?.isFallbackTradeDate ?? market?.rotation?.isFallbackTradeDate
  )
  const sourceKind =
    market?.strong?.sourceKind ?? market?.flow?.sourceKind ?? market?.rotation?.sourceKind
  const source = market?.strong?.source ?? market?.flow?.source ?? market?.rotation?.source

  return (
    <div className="max-w-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <div className="border-b border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-4 sm:p-8 xl:p-10">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0 max-w-3xl space-y-3">
            <div className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
              <Flame className="size-3.5 text-orange-500" />
              行情 · Market Pulse · {fetchedAt ? fetchedAt.slice(0, 19).replace("T", " ") : "—"}
              {isTradeTime ? (
                <Badge
                  variant="outline"
                  className="h-5 border-emerald-200 bg-emerald-50 px-1.5 text-[10px] text-emerald-700"
                >
                  <Clock className="mr-1 size-3" /> 交易时间内
                </Badge>
              ) : isTradingDay ? (
                <Badge
                  variant="outline"
                  className="h-5 border-slate-200 bg-slate-50 px-1.5 text-[10px] text-slate-600"
                >
                  收盘后
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="h-5 border-slate-200 bg-slate-50 px-1.5 text-[10px] text-slate-600"
                >
                  非交易日
                </Badge>
              )}
            </div>
            <h1 className="break-words text-2xl font-semibold leading-tight text-slate-950 sm:text-4xl">
              强势板块 · 主力净流入 · 行业轮动
            </h1>
            <p className="text-sm leading-7 text-slate-600">
              数据源: Postgres 市场快照 · 每 10 分钟自动刷新{isTradeTime ? " (盘内)" : " (盘后/非交易日已停)"} · 15:30 收盘归档
              {typeof flowElapsedMs === "number" ? <> · flow 拉取耗时 {flowElapsedMs}ms</> : null}
            </p>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge variant="outline" className="rounded-full px-2.5 py-1">
                <Calendar className="mr-1 size-3" />
                展示交易日 {tradeDate ?? "—"}
              </Badge>
              <Badge variant="outline" className="rounded-full px-2.5 py-1">
                请求交易日 {requestedTradeDate ?? "—"}
              </Badge>
              <Badge
                variant="outline"
                className={`rounded-full px-2.5 py-1 ${
                  isFallbackTradeDate
                    ? "border-amber-200 bg-amber-50 text-amber-700"
                    : "border-emerald-200 bg-emerald-50 text-emerald-700"
                }`}
              >
                {isFallbackTradeDate ? "已回退上一交易日" : "未回退"}
              </Badge>
              <Badge variant="outline" className="rounded-full px-2.5 py-1">
                sourceKind {sourceKind ?? "—"}
              </Badge>
              <Badge variant="outline" className="max-w-full whitespace-normal break-all rounded-full px-2.5 py-1 text-left">
                source {source ?? "—"}
              </Badge>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:flex sm:items-center">
            <Button variant="outline" size="sm" className="w-full rounded-xl sm:w-auto" onClick={onRefresh} disabled={loading}>
              <RefreshCcw className={`mr-1.5 size-4 ${loading ? "animate-spin" : ""}`} /> 刷新
            </Button>
            <Button
              onClick={onRefresh}
              disabled={loading}
              className="w-full rounded-xl bg-slate-950 text-white hover:bg-slate-800 sm:w-auto"
              size="sm"
            >
              实时刷新 <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function SummaryStrip({ data }: { data: MarketPulse }) {
  const top = data.strong?.top?.[0]
  const bottom = data.strong?.bottom?.[0]
  const inflowTop = data.flow?.inflow?.[0]
  const outflowTop = data.flow?.outflow?.[0]
  const items = [
    {
      label: "领涨",
      name: top?.name ?? "—",
      pct: top?.changePercent ?? null,
      amount: fmtYi(top?.amount),
      tone: "up" as const,
      icon: Flame,
    },
    {
      label: "领跌",
      name: bottom?.name ?? "—",
      pct: bottom?.changePercent ?? null,
      amount: fmtYi(bottom?.amount),
      tone: "down" as const,
      icon: ArrowDownRight,
    },
    {
      label: "主力净流入",
      name: inflowTop?.name ?? "—",
      net: inflowTop?.mainNet,
      leading: inflowTop?.leadingStock,
      tone: "up" as const,
      icon: Layers,
    },
    {
      label: "主力净流出",
      name: outflowTop?.name ?? "—",
      net: outflowTop?.mainNet,
      leading: outflowTop?.leadingStock,
      tone: "down" as const,
      icon: Layers,
    },
  ]

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const Icon = item.icon
        const color =
          item.tone === "up" ? "border-red-200 bg-red-50/40" : "border-emerald-200 bg-emerald-50/40"
        const ink = item.tone === "up" ? "text-red-700" : "text-emerald-700"
        return (
          <div key={item.label} className={`min-w-0 rounded-2xl border ${color} p-4`}>
            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-500">{item.label}</div>
              <Icon className={`size-4 ${ink}`} />
            </div>
            <div className="mt-2 truncate text-xl font-semibold text-slate-950">{item.name}</div>
            <div className={`mt-1 flex flex-wrap items-center gap-2 text-sm tabular-nums ${ink}`}>
              {"net" in item ? <span>{fmtYi(item.net)}</span> : <span>{fmtPct(item.pct)}</span>}
              {"leading" in item && item.leading ? (
                <Badge variant="outline" className="h-4 border-slate-200 bg-white px-1.5 text-[10px] text-slate-600">
                  领涨 {item.leading}
                </Badge>
              ) : null}
              {"amount" in item ? <span className="text-xs text-slate-400">{item.amount}</span> : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function SchedulerStatusBar({
  status,
  onTrigger,
}: {
  status: SchedulerStatus | null
  onTrigger: () => void
}) {
  if (!status) return null

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-xs shadow-sm sm:flex-row sm:flex-wrap sm:items-center sm:px-4">
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
          status.isRunning ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
        }`}
      >
        {status.isRunning ? "● 调度运行中" : "○ 未启动"}
      </span>
      <span className="text-slate-500">盘内 10 分钟 / 收盘 15:30 自动落盘</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">最近盘内: {status.lastInsideRefreshAt ?? "—"}</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">最近收盘: {status.lastCloseSnapshotAt ?? "—"}</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">盘内 {status.totalInside ?? 0} 次 / 收盘 {status.totalClose ?? 0} 次</span>
      <span className="grid grid-cols-1 gap-1.5 sm:ml-auto sm:flex sm:items-center">
        {status.lastRunOk === false ? (
          <Badge variant="outline" className="h-4 border-rose-200 bg-rose-50 px-1.5 text-[10px] text-rose-700">
            <TrendingDown className="mr-1 size-3" /> 失败
          </Badge>
        ) : status.lastRunOk ? (
          <Badge
            variant="outline"
            className="h-4 border-emerald-200 bg-emerald-50 px-1.5 text-[10px] text-emerald-700"
          >
            <TrendingUp className="mr-1 size-3" /> 正常
          </Badge>
        ) : null}
        <Button variant="outline" size="sm" className="h-7 w-full rounded-lg text-[11px] sm:w-auto" onClick={onTrigger}>
          手动 snapshot
        </Button>
      </span>
    </div>
  )
}
