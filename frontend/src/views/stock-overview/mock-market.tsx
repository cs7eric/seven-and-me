/**
 * Stock Overview · 行情 (Market Pulse) 页面.
 *
 * 三个核心模块 + 趋势:
 *  1. 强势板块 (Strong Sectors)      - akshare 90 行业当日 Top N, 卡片点击钻入
 *  2. 主力净流入 (Capital Flow)       - akshare 90 行业真实资金流
 *  3. 行业轮动 (Rotation)             - 每天 15:30 落盘的 Top N 快照
 *  4. 行业轮动历史趋势 (Rotation Trend) - 跨日 Top 10 趋势: 出现/消失/排名变化
 *
 * 自动刷新:
 *  - 交易时间内 (9:30-11:30, 13:00-15:00) 每 10 分钟轮询一次
 *  - 后端 scheduler 在同一时间间隔里落盘当日 snapshot
 */
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  ChevronRight,
  Clock,
  Flame,
  Layers,
  RefreshCcw,
  Shuffle,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { notification } from "@/components/ui/notification"

import {
  fetchMarketPulse,
  fetchMarketPulseRotationTrend,
  fetchIndustryDetail,
  fetchMarketPulseSchedulerStatus,
  triggerMarketPulseSnapshot,
  fetchIndustryConstituents,
} from "@/lib/api"

// =============================================================================
// 类型
// =============================================================================
type StrongRow = {
  name: string
  changePct?: number
  changePercent?: number
  amount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  stockCount?: number
}
type FlowRow = {
  name: string
  changePct?: number
  mainNet: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  leadingPrice?: number | null
}
type RotationItem = {
  name: string
  changePct: number
  rank: number
  mainNet?: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
}
type RotationRow = { date: string; topN: number; items: RotationItem[] }

type MarketPulse = {
  ok: boolean
  strong: { ok: boolean; top: StrongRow[]; bottom: StrongRow[]; fetchedAt?: string; count?: number }
  flow:   { ok: boolean; inflow: FlowRow[]; outflow: FlowRow[]; inflowCount?: number; outflowCount?: number; elapsedMs?: number; kind?: string; source?: string; unit?: string }
  rotation: { ok: boolean; dates: string[]; rows: RotationRow[]; topN?: number }
}

type TrendIndustry = {
  name: string
  appearances: number
  avgRank: number | null
  bestRank: number | null
  worstRank: number | null
  latestRank: number | null
  latestChangePct: number | null
  ranks: (number | null)[]
  changePcts: (number | null)[]
}
type RotationTrend = {
  ok: boolean
  topN: number
  days: number
  dates: string[]
  industries: TrendIndustry[]
}

type IndustryDetail = {
  ok: boolean
  name: string
  changePct?: number
  mainNet?: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  leadingQuote?: Record<string, unknown> | null
  leadingKLine?: Array<Record<string, unknown>>
  leadingFlow30d?: Array<{ date?: string; mainNet?: number; largeNet?: number; mediumNet?: number; smallNet?: number }>
  leadingFlowSeed?: string
  constituents?: unknown[]
  error?: string
}

type ConstituentRow = {
  rank?: number
  code6: string
  name: string
  price?: number
  changePct?: number
  change?: number
  turnoverRate?: number
  volumeRatio?: number
  amplitude?: number
  amountText?: string
  marketCapText?: string
  pe?: string
}
type ConstituentsPayload = {
  ok: boolean
  name: string
  pages: number
  pageRowCounts: number[]
  fetchedAt: string
  rows: ConstituentRow[]
  error?: string
}

type SchedulerStatus = {
  isRunning?: boolean
  schedulerStartedAt?: string
  lastRunAt?: string | null
  lastRunOk?: boolean | null
  lastInsideRefreshAt?: string | null
  lastCloseSnapshotAt?: string | null
  totalInside?: number
  totalClose?: number
  insideIntervalSeconds?: number
  closeSnapshotCron?: string
  isTradeTime?: boolean
  isTradingDay?: boolean
  now?: string
  lastTopN?: Array<{ name?: string; changePct?: number }>
}

// =============================================================================
// 9 档涨跌色
// =============================================================================
const BAND = {
  upExtreme: "#B71C1C", upStrong: "#D32F2F", upMid: "#F44336", upLight: "#EF9A9A", flat: "#9E9E9E",
  downLight: "#A5D6A7", downMid: "#4CAF50", downStrong: "#2E7D32", downExtreme: "#1B5E20",
} as const

function bandColor(pct: number | null | undefined) {
  if (pct == null || !Number.isFinite(pct) || Math.abs(pct) > 50) return BAND.flat
  if (pct >= 10) return BAND.upExtreme
  if (pct >= 5) return BAND.upStrong
  if (pct >= 2) return BAND.upMid
  if (pct >= 0.5) return BAND.upLight
  if (pct <= -10) return BAND.downExtreme
  if (pct <= -5) return BAND.downStrong
  if (pct <= -2) return BAND.downMid
  if (pct <= -0.5) return BAND.downLight
  return BAND.flat
}
function bandFg(pct: number | null | undefined) {
  if (pct == null) return "#ffffff"
  if (Math.abs(pct) < 0.5) return "#ffffff"
  if (pct >= 0.5 && pct < 2) return "#7f1d1d"
  if (pct <= -0.5 && pct > -2) return "#14532d"
  return "#ffffff"
}
const fmtPct = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`
const fmtAmount = (v: number | null | undefined) => {
  if (v == null) return "—"
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(1)}亿`
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return String(Math.round(v))
}
const fmtYi = (v: number | null | undefined) => {
  if (v == null) return "—"
  return `${v >= 0 ? "+" : ""}${(v / 1e8).toFixed(2)}亿`
}
const cardChrome = "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.045)]"
const prettyDate = (d: string) => d.slice(5)
function weekday(d: string) {
  const t = new Date(`${d}T00:00:00Z`).getUTCDay()
  return ["日", "一", "二", "三", "四", "五", "六"][t]
}

// =============================================================================
// 顶部
// =============================================================================
function PageHeader({
  onRefresh, loading, fetchedAt, flowElapsedMs, scheduler,
}: {
  onRefresh: () => void
  loading: boolean
  fetchedAt?: string
  flowElapsedMs?: number
  scheduler?: SchedulerStatus | null
}) {
  const isTradeTime = scheduler?.isTradeTime
  const isTradingDay = scheduler?.isTradingDay
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <div className="border-b border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-6 sm:p-8 xl:p-10">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
              <Flame className="size-3.5 text-orange-500" />
              行情 · Market Pulse · {fetchedAt ? fetchedAt.slice(0, 19).replace("T", " ") : "—"}
              {isTradeTime ? (
                <Badge variant="outline" className="ml-2 h-5 border-emerald-200 bg-emerald-50 px-1.5 text-[10px] text-emerald-700">
                  <Clock className="mr-1 size-3" /> 交易时间内
                </Badge>
              ) : isTradingDay ? (
                <Badge variant="outline" className="ml-2 h-5 border-slate-200 bg-slate-50 px-1.5 text-[10px] text-slate-600">
                  收盘后
                </Badge>
              ) : (
                <Badge variant="outline" className="ml-2 h-5 border-slate-200 bg-slate-50 px-1.5 text-[10px] text-slate-600">
                  非交易日
                </Badge>
              )}
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-[-0.045em] text-slate-950 sm:text-4xl">
              强势板块 · 主力净流入 · 行业轮动
            </h1>
            <p className="text-sm leading-7 text-slate-600">
              数据源: akshare 同花顺 90 行业资金流 · 每 10 分钟自动刷新{isTradeTime ? " (盘内)" : " (盘后/非交易日已停)"} · 15:30 收盘落盘
              {typeof flowElapsedMs === "number" ? <> · flow 拉取耗时 {flowElapsedMs}ms</> : null}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="rounded-xl" onClick={onRefresh} disabled={loading}>
              <RefreshCcw className={`mr-1.5 size-4 ${loading ? "animate-spin" : ""}`} /> 刷新
            </Button>
            <Button onClick={onRefresh} disabled={loading} className="rounded-xl bg-slate-950 text-white hover:bg-slate-800" size="sm">
              实时刷新 <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------- 顶部 4 张概要卡 ----------
function SummaryStrip({ data }: { data: MarketPulse }) {
  const top = data.strong?.top?.[0]
  const bot = data.strong?.bottom?.[0]
  const inTop = data.flow?.inflow?.[0]
  const outTop = data.flow?.outflow?.[0]
  const items = [
    { label: "领涨",  name: top?.name ?? "—",     pct: top?.changePercent ?? null, amount: fmtYi(top?.amount), tone: "up"   as const, icon: Flame },
    { label: "领跌",  name: bot?.name ?? "—",     pct: bot?.changePercent ?? null, amount: fmtYi(bot?.amount), tone: "down" as const, icon: ArrowDownRight },
    { label: "主力净流入", name: inTop?.name ?? "—", net: inTop?.mainNet,  leading: inTop?.leadingStock, tone: "up"   as const, icon: Layers },
    { label: "主力净流出", name: outTop?.name ?? "—", net: outTop?.mainNet, leading: outTop?.leadingStock, tone: "down" as const, icon: Layers },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((it) => {
        const Icon = it.icon
        const color = it.tone === "up" ? "border-red-200 bg-red-50/40" : "border-emerald-200 bg-emerald-50/40"
        const ink = it.tone === "up" ? "text-red-700" : "text-emerald-700"
        return (
          <div key={it.label} className={`rounded-2xl border ${color} p-4`}>
            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-500">{it.label}</div>
              <Icon className={`size-4 ${ink}`} />
            </div>
            <div className="mt-2 text-xl font-semibold tracking-[-0.03em] text-slate-950">{it.name}</div>
            <div className={`mt-1 flex items-center gap-2 text-sm tabular-nums ${ink}`}>
              {"net" in it ? <span>{fmtYi(it.net)}</span> : <span>{fmtPct(it.pct)}</span>}
              {"leading" in it && it.leading ? (
                <Badge variant="outline" className="h-4 border-slate-200 bg-white px-1.5 text-[10px] text-slate-600">
                  领涨 {it.leading}
                </Badge>
              ) : null}
              <span className="text-xs text-slate-400">{it.amount}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------- 1. 强势板块 ----------
function StrongSectors({ data, onPick }: { data: MarketPulse["strong"]; onPick: (name: string) => void }) {
  const top = data?.top ?? []
  const bottom = data?.bottom ?? []
  if (!top.length) return <EmptyCard title="强势板块" desc="暂无数据" />
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
          {top.map((s) => (
            <div
              key={s.name}
              onClick={() => onPick(s.name)}
              className="group flex cursor-pointer flex-col justify-between rounded-xl border border-slate-200/60 bg-white p-3.5 transition-shadow hover:border-slate-300 hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-900">{s.name}</div>
                  {s.leadingStock ? (
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      领涨 <span className="font-medium text-slate-700">{s.leadingStock}</span>
                      {s.leadingChangePct != null ? (
                        <span
                          className="ml-1 tabular-nums"
                          style={{ color: bandColor(s.leadingChangePct) === BAND.flat ? "#475569" : bandColor(s.leadingChangePct) }}
                        >
                          {fmtPct(s.leadingChangePct)}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div
                  className="rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums"
                  style={{ background: bandColor(s.changePercent), color: bandFg(s.changePercent) }}
                >
                  {fmtPct(s.changePercent)}
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                {typeof s.stockCount === "number" ? (
                  <span className="tabular-nums">{s.stockCount}只</span>
                ) : <span />}
                <span className="tabular-nums">
                  净额 {fmtYi(s.amount)}
                </span>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 border-t border-slate-100 pt-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">弱势</div>
          <div className="flex flex-wrap gap-2">
            {bottom.map((s) => (
              <button
                key={`bot-${s.name}`}
                onClick={() => onPick(s.name)}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs transition-colors hover:border-slate-300 hover:bg-slate-100"
              >
                <span className="text-slate-700">{s.name}</span>
                <span className="font-semibold tabular-nums" style={{ color: bandColor(s.changePercent) === BAND.flat ? "#475569" : bandColor(s.changePercent) }}>
                  {fmtPct(s.changePercent)}
                </span>
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------- 2. 主力净流入 ----------
function CapitalFlow({ data, onPick }: { data: MarketPulse["flow"]; onPick: (name: string) => void }) {
  const inflow = data?.inflow ?? []
  const outflow = data?.outflow ?? []
  if (!inflow.length && !outflow.length) return <EmptyCard title="行业主力净流入" desc="暂无数据" />
  const maxAbs = Math.max(
    ...inflow.map((x) => Math.abs(x.mainNet)),
    ...outflow.map((x) => Math.abs(x.mainNet)),
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
        <FlowColumn title="净流入" tone="up"   rows={inflow}  maxAbs={maxAbs} onPick={onPick} />
        <FlowColumn title="净流出" tone="down" rows={outflow} maxAbs={maxAbs} onPick={onPick} />
      </CardContent>
    </Card>
  )
}

function FlowColumn({
  title, tone, rows, maxAbs, onPick,
}: { title: string; tone: "up" | "down"; rows: FlowRow[]; maxAbs: number; onPick: (name: string) => void }) {
  const isUp = tone === "up"
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
      <div className={`mb-3 flex items-center gap-2 text-sm font-semibold ${isUp ? "text-red-700" : "text-emerald-700"}`}>
        {isUp ? <ArrowUpRight className="size-4" /> : <ArrowDownRight className="size-4" />}
        {title} ({rows.length})
      </div>
      <div className="space-y-2.5">
        {rows.map((r) => {
          const w = Math.max(6, Math.min(100, (Math.abs(r.mainNet) / maxAbs) * 100))
          return (
            <div key={r.name} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => onPick(r.name)}
                    className="font-medium text-slate-800 hover:underline"
                  >
                    {r.name}
                  </button>
                  {r.changePct != null ? (
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
                      style={{ background: bandColor(r.changePct), color: bandFg(r.changePct) }}
                    >
                      {fmtPct(r.changePct)}
                    </span>
                  ) : null}
                  {typeof r.stockCount === "number" ? (
                    <span className="text-[10px] text-slate-400">{r.stockCount}只</span>
                  ) : null}
                  {r.leadingStock ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
                      领涨
                      <span className="font-semibold text-slate-800">{r.leadingStock}</span>
                      {r.leadingChangePct != null ? (
                        <span
                          className="tabular-nums"
                          style={{ color: bandColor(r.leadingChangePct) === BAND.flat ? "#475569" : bandColor(r.leadingChangePct) }}
                        >
                          {fmtPct(r.leadingChangePct)}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-2 tabular-nums">
                  <span className={`font-semibold ${isUp ? "text-red-700" : "text-emerald-700"}`}>
                    {isUp ? "+" : ""}{r.mainNet.toFixed(2)}亿
                  </span>
                </div>
              </div>
              <div className="relative h-2 rounded-full bg-slate-200/70">
                <div
                  className={`absolute top-0 h-2 rounded-full ${isUp ? "bg-red-500" : "bg-emerald-500"}`}
                  style={{ width: `${w}%`, left: isUp ? 0 : "auto", right: isUp ? "auto" : 0 }}
                />
              </div>
              {r.inflow != null || r.outflow != null ? (
                <div className="flex items-center gap-2 text-[10px] text-slate-500 tabular-nums">
                  <span>流入 {r.inflow?.toFixed(2) ?? "—"}亿</span>
                  <span>流出 {r.outflow?.toFixed(2) ?? "—"}亿</span>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------- 3. 行业轮动 (日期 × 行业 Top N) ----------
function IndustryRotation({ data, onRefreshSnapshot, onPick }: {
  data: MarketPulse["rotation"]
  onRefreshSnapshot: () => void
  onPick: (name: string) => void
}) {
  const dates: string[] = data?.dates ?? []
  const rows: RotationRow[] = data?.rows ?? []
  const topN = data?.topN ?? rows[0]?.topN ?? 10

  if (!rows.length) {
    return (
      <Card className={cardChrome}>
        <CardHeader className="border-b border-slate-100 pb-5">
          <div>
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
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="rounded-full px-3 py-1 text-xs text-slate-500">
              <Calendar className="mr-1 size-3" /> {dates[0]} ~ {dates[dates.length - 1]} · {dates.length} 个交易日
            </Badge>
            <Button variant="outline" size="sm" className="rounded-xl" onClick={onRefreshSnapshot}>
              <RefreshCcw className="mr-1.5 size-4" /> 刷新今日快照
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-20" />
              {dates.map((d) => <col key={d} />)}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60">
                <th className="sticky left-0 z-10 bg-slate-50/95 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">排名</th>
                {dates.map((d) => (
                  <th key={d} className="border-l border-slate-100 px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    <div className="flex flex-col items-center gap-0.5">
                      <span>{prettyDate(d)}</span>
                      <span className="text-[10px] font-normal text-slate-400">{weekday(d)}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: topN }).map((_, idx) => {
                const rank = idx + 1
                return (
                  <tr key={rank} className="border-b border-slate-50">
                    <td className="sticky left-0 z-10 bg-white px-3 py-2 align-middle text-xs text-slate-500">
                      <div className="flex items-center gap-2">
                        <span className={`tabular-nums ${rank <= 3 ? "font-semibold text-slate-900" : "text-slate-500"}`}>{rank}</span>
                        {rank === 1 ? <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">TOP</span> : null}
                      </div>
                    </td>
                    {dates.map((d) => {
                      const row = rows.find((r) => r.date === d)
                      const item = row?.items?.[idx]
                      if (!item) return <td key={d} className="border-l border-slate-100 px-2 py-2 text-center text-slate-300">—</td>
                      return (
                        <td key={d} className="border-l border-slate-100 px-2 py-1.5">
                          <button
                            onClick={() => onPick(item.name)}
                            className="flex h-12 w-full flex-col items-center justify-center rounded-md px-1.5 text-center transition-opacity hover:opacity-80"
                            style={{ background: bandColor(item.changePct), color: bandFg(item.changePct) }}
                            title={`${item.name} 当日 ${fmtPct(item.changePct)}`}
                          >
                            <div className="truncate text-xs font-semibold leading-4">{item.name}</div>
                            <div className="text-[10px] font-medium tabular-nums leading-3.5 opacity-90">{fmtPct(item.changePct)}</div>
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
            { c: BAND.upExtreme, t: "≥+10%" }, { c: BAND.upStrong, t: "+5~+10%" }, { c: BAND.upMid, t: "+2~+5%" },
            { c: BAND.upLight, t: "+0.5~+2%" }, { c: BAND.flat, t: "±0.5%" },
            { c: BAND.downLight, t: "-2~-0.5%" }, { c: BAND.downMid, t: "-5~-2%" },
            { c: BAND.downStrong, t: "-10~-5%" }, { c: BAND.downExtreme, t: "≤-10%" },
          ].map((b) => (
            <span key={b.t} className="inline-flex items-center gap-1.5">
              <span className="size-3 rounded-sm" style={{ background: b.c }} />
              <span className="tabular-nums">{b.t}</span>
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------- 4. 轮动历史趋势 ----------
function RotationTrend({ data, onPick }: { data: RotationTrend | null; onPick: (name: string) => void }) {
  const dates: string[] = data?.dates ?? []
  const industries: TrendIndustry[] = data?.industries ?? []
  // 只展示"近 10 个交易日"出现次数 >= 2 的行业, 减少噪音
  const filtered = useMemo(
    () => industries.filter((i) => i.appearances >= 1).slice(0, 30),
    [industries]
  )

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
          <table className="w-full table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-44" />
              <col className="w-16" />
              <col className="w-16" />
              <col className="w-16" />
              <col className="w-16" />
              {dates.map((d) => <col key={d} />)}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 text-xs">
                <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">行业</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">出现</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">最佳</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">平均</th>
                <th className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">最新</th>
                {dates.map((d) => (
                  <th key={d} className="border-l border-slate-100 px-2 py-2 text-center text-[10px] font-semibold text-slate-500">
                    <div className="flex flex-col items-center">
                      <span>{prettyDate(d)}</span>
                      <span className="text-[9px] font-normal text-slate-400">{weekday(d)}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((it) => (
                <tr key={it.name} className="border-b border-slate-50">
                  <td className="px-3 py-2">
                    <button
                      onClick={() => onPick(it.name)}
                      className="text-left text-sm font-medium text-slate-900 hover:underline"
                    >
                      {it.name}
                    </button>
                  </td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">{it.appearances}/{dates.length}</td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">{it.bestRank ?? "—"}</td>
                  <td className="px-2 py-2 text-center tabular-nums text-xs text-slate-700">{it.avgRank ?? "—"}</td>
                  <td className="px-2 py-2 text-center">
                    {it.latestRank == null ? (
                      <span className="text-xs text-slate-400">未上榜</span>
                    ) : (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700 tabular-nums">
                        {it.latestRank}
                      </span>
                    )}
                  </td>
                  {dates.map((d, idx) => {
                    const rank = it.ranks?.[idx]
                    const cp = it.changePcts?.[idx]
                    if (rank == null) {
                      return <td key={d} className="border-l border-slate-100 px-2 py-2 text-center text-[10px] text-slate-300">—</td>
                    }
                    return (
                      <td key={d} className="border-l border-slate-100 px-1 py-1.5">
                        <div
                          className="flex h-9 flex-col items-center justify-center rounded-md px-1 text-center"
                          style={{ background: bandColor(cp), color: bandFg(cp) }}
                          title={`${d} 排名 ${rank} ${fmtPct(cp)}`}
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

// ---------- 5. 行业钻入 (M1 卡片点击) ----------
function IndustryDetailDrawer({
  name, onClose,
}: { name: string | null; onClose: () => void }) {
  const [data, setData] = useState<IndustryDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!name) {
      setData(null)
      return
    }
    let cancelled = false
    setLoading(true)
    fetchIndustryDetail(name)
      .then((r) => { if (!cancelled) setData(r as IndustryDetail) })
      .catch((e) => { if (!cancelled) notification.error(`钻入失败: ${e?.message ?? e}`) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
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
              {data?.changePct != null ? (
                <span
                  className="rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums"
                  style={{ background: bandColor(data.changePct), color: bandFg(data.changePct) }}
                >
                  {fmtPct(data.changePct)}
                </span>
              ) : null}
            </div>
            {data?.stockCount != null ? (
              <div className="mt-1 text-xs text-slate-500">
                共 {data.stockCount} 家公司
                {data.mainNet != null ? <> · 净流入 {fmtYi(data.mainNet)}</> : null}
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
          ) : !data?.ok ? (
            <div className="p-10 text-center text-sm text-rose-500">{data?.error ?? "暂无数据"}</div>
          ) : (
            <>
              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">领涨股</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-[11px] text-slate-500">名称</div>
                    <div className="mt-0.5 font-semibold text-slate-900">{data.leadingStock ?? "—"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-slate-500">当日涨跌幅</div>
                    <div className="mt-0.5 font-semibold tabular-nums" style={{ color: bandColor(data.leadingChangePct) === BAND.flat ? "#475569" : bandColor(data.leadingChangePct) }}>
                      {fmtPct(data.leadingChangePct)}
                    </div>
                  </div>
                  {data.leadingQuote ? (
                    <>
                      <div>
                        <div className="text-[11px] text-slate-500">最新价</div>
                        <div className="mt-0.5 tabular-nums">
                          {(data.leadingQuote.lastPrice as number | null)?.toFixed?.(2) ?? "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] text-slate-500">成交额</div>
                        <div className="mt-0.5 tabular-nums">{fmtAmount(data.leadingQuote.amount as number)}</div>
                      </div>
                    </>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">30 天主力净流入走势 (领涨股)</CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    数据源 eltdx 200742 · seed = {data.leadingFlowSeed ?? "—"}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {!data.leadingFlow30d?.length ? (
                    <div className="p-6 text-center text-xs text-slate-500">暂无数据</div>
                  ) : (
                    <FlowMiniChart rows={data.leadingFlow30d} />
                  )}
                </CardContent>
              </Card>

              {data.leadingKLine && data.leadingKLine.length > 0 ? (
                <Card className="rounded-xl border-slate-200">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold text-slate-900">60 日 K 线 (领涨股)</CardTitle>
                    <CardDescription className="text-xs text-slate-500">
                      {data.leadingKLine.length} bars
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <KLineMini bars={data.leadingKLine} />
                  </CardContent>
                </Card>
              ) : null}

              <Card className="rounded-xl border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-slate-900">成分股</CardTitle>
                </CardHeader>
                <CardContent>
                  {data.constituents && data.constituents.length > 0 ? (
                    <div className="text-sm text-slate-700">成分股列表 (待接入)</div>
                  ) : (
                    <div className="text-xs text-slate-500">
                      akshare 90 行业接口不返回成分股列表; 当前显示 {data.stockCount ?? "—"} 家公司数
                      {data.leadingStock ? (
                        <> + 1 只领涨股 = <span className="font-semibold text-slate-700">{data.leadingStock}</span></>
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
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.mainNet ?? 0)))
  return (
    <div className="flex h-32 items-end gap-1.5">
      {rows.slice(-30).map((r, i) => {
        const v = r.mainNet ?? 0
        const ratio = Math.abs(v) / maxAbs
        const h = Math.max(2, Math.round(ratio * 100))
        const isUp = v >= 0
        return (
          <div key={`${r.date ?? i}-${i}`} className="group relative flex h-full flex-1 items-end">
            <div
              className={`w-full rounded-t ${isUp ? "bg-red-500" : "bg-emerald-500"}`}
              style={{ height: `${h}%` }}
              title={`${r.date}  主力 ${fmtYi(v)}`}
            />
          </div>
        )
      })}
    </div>
  )
}

function KLineMini({ bars }: { bars: Array<Record<string, unknown>> }) {
  // 简单可视化: 用 close 画一条线 + 颜色按 close vs 起点
  const closes = bars.map((b) => Number(b.close) || 0).filter((v) => v > 0)
  if (closes.length < 2) {
    return <div className="p-6 text-center text-xs text-slate-500">K 线数据不足</div>
  }
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const w = 100 / closes.length
  return (
    <div className="flex h-32 items-end">
      {closes.map((c, i) => {
        const ratio = max === min ? 0.5 : (c - min) / (max - min)
        return (
          <div key={i} className="flex-1" style={{ width: `${w}%` }}>
            <div
              className="mx-auto h-24 w-1 rounded"
              style={{
                background: i === 0 ? "#94a3b8" : closes[i] >= closes[i - 1] ? "#ef4444" : "#22c55e",
                height: `${Math.max(8, ratio * 96)}px`,
              }}
              title={`#${i} close=${c.toFixed(2)}`}
            />
          </div>
        )
      })}
    </div>
  )
}

// ---------- 6. scheduler 状态条 ----------
function SchedulerStatusBar({
  status, onTrigger,
}: { status: SchedulerStatus | null; onTrigger: () => void }) {
  if (!status) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs shadow-sm">
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${status.isRunning ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
        {status.isRunning ? "● 调度运行中" : "○ 未启动"}
      </span>
      <span className="text-slate-500">盘内 10 分钟 / 收盘 15:30 自动落盘</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">
        最近盘内: {status.lastInsideRefreshAt ?? "—"}
      </span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">
        最近收盘: {status.lastCloseSnapshotAt ?? "—"}
      </span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500">盘内 {status.totalInside ?? 0} 次 / 收盘 {status.totalClose ?? 0} 次</span>
      <span className="ml-auto flex items-center gap-1.5">
        {status.lastRunOk === false ? (
          <Badge variant="outline" className="h-4 border-rose-200 bg-rose-50 px-1.5 text-[10px] text-rose-700">
            <TrendingDown className="mr-1 size-3" /> 失败
          </Badge>
        ) : status.lastRunOk ? (
          <Badge variant="outline" className="h-4 border-emerald-200 bg-emerald-50 px-1.5 text-[10px] text-emerald-700">
            <TrendingUp className="mr-1 size-3" /> 正常
          </Badge>
        ) : null}
        <Button variant="outline" size="sm" className="h-7 rounded-lg text-[11px]" onClick={onTrigger}>
          手动 snapshot
        </Button>
      </span>
    </div>
  )
}

function EmptyCard({ title, desc }: { title: string; desc: string }) {
  return (
    <Card className={cardChrome}>
      <CardHeader>
        <CardTitle className="text-base text-slate-900">{title}</CardTitle>
        <CardDescription className="text-sm text-slate-500">{desc}</CardDescription>
      </CardHeader>
    </Card>
  )
}

// =============================================================================
// 入口
// =============================================================================
const INSIDE_REFRESH_MS = 10 * 60 * 1000  // 10 分钟

export default function MarketPulse() {
  const [data, setData] = useState<MarketPulse | null>(null)
  const [trend, setTrend] = useState<RotationTrend | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [m, t, s] = await Promise.all([
        fetchMarketPulse(),
        fetchMarketPulseRotationTrend(10, 10).catch(() => null),
        fetchMarketPulseSchedulerStatus().catch(() => null),
      ])
      setData(m as MarketPulse)
      if (t) setTrend(t as RotationTrend)
      if (s) setScheduler(s as SchedulerStatus)
    } catch (e: any) {
      notification.error(`行情数据加载失败: ${e?.message ?? e}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshSnapshot = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchMarketPulse({ refreshRotation: true })
      setData(res as MarketPulse)
      notification.success("今日 Top 快照已落盘")
      // 顺手刷新趋势
      const t = await fetchMarketPulseRotationTrend(10, 10).catch(() => null)
      if (t) setTrend(t as RotationTrend)
    } catch (e: any) {
      notification.error(`刷新快照失败: ${e?.message ?? e}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const triggerScheduler = useCallback(async () => {
    setLoading(true)
    try {
      await triggerMarketPulseSnapshot()
      notification.success("已手动触发今日 snapshot")
      await load()
    } catch (e: any) {
      notification.error(`手动 snapshot 失败: ${e?.message ?? e}`)
    } finally {
      setLoading(false)
    }
  }, [load])

  // 初次加载
  useEffect(() => { load() }, [load])

  // 交易时间内 10 分钟自动刷新
  useEffect(() => {
    if (!scheduler?.isTradeTime) return
    const timer = setInterval(() => { load() }, INSIDE_REFRESH_MS)
    return () => clearInterval(timer)
  }, [scheduler?.isTradeTime, load])

  return (
    <WorkspaceShell>
      <div className="h-[calc(100svh-4rem)] space-y-4 overflow-y-auto p-3 sm:p-4">
        <PageHeader
          onRefresh={load}
          loading={loading}
          fetchedAt={data?.strong?.fetchedAt}
          flowElapsedMs={data?.flow?.elapsedMs}
          scheduler={scheduler}
        />
        <SchedulerStatusBar status={scheduler} onTrigger={triggerScheduler} />
        {data ? <SummaryStrip data={data} /> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <StrongSectors data={data?.strong} onPick={setPicked} />
          <CapitalFlow data={data?.flow} onPick={setPicked} />
        </div>
        <IndustryRotation data={data?.rotation} onRefreshSnapshot={refreshSnapshot} onPick={setPicked} />
        <RotationTrend data={trend} onPick={setPicked} />
      </div>
      <IndustryDetailDrawer name={picked} onClose={() => setPicked(null)} />
    </WorkspaceShell>
  )
}
