/**
 * Stock Overview · 行情 (Market Pulse) 页面 - 接真接口版本.
 *
 * 接口 (backend/api/stock_chart.py):
 *  GET /api/stock-chart/market-pulse/strong?topN=10
 *  GET /api/stock-chart/market-pulse/capital-flow?days=30&topN=20
 *  GET /api/stock-chart/market-pulse/rotation?days=10&topN=10&refresh=0
 *  GET /api/stock-chart/market-pulse/all
 *
 * 三个模块:
 *  1. 强势板块 - TDX 56 行业指数实时, 按 change_pct 排序
 *  2. 主力净流入 - eltdx 200742 (200742) 按种子股近 30 天数据, 取当日 + 连入/连出天数
 *  3. 行业轮动 - 每天收盘后落盘的 Top N 快照, 后续直接读盘
 */
import { useCallback, useEffect, useState } from "react"
import {
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  ChevronRight,
  Flame,
  Layers,
  RefreshCcw,
  Shuffle,
  TrendingUp,
} from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { notification } from "@/components/ui/notification"

import { fetchMarketPulse } from "@/lib/api"

// =============================================================================
// 类型 (和后端一致)
// =============================================================================
type StrongRow = {
  code6: string
  name: string
  fullCode?: string
  lastPrice?: number
  change?: number
  changePercent?: number
  amount?: number
}
type FlowRow = {
  code6: string
  name: string
  date?: string
  mainNet: number
  largeNet: number
  mediumNet: number
  smallNet: number
  consecutiveDays: number
}
type RotationItem = { code6: string; name: string; changePct: number; rank: number; amount?: number }
type RotationRow = { date: string; topN: number; items: RotationItem[] }
type MarketPulse = {
  ok: boolean
  strong: { ok: boolean; top: StrongRow[]; bottom: StrongRow[]; fetchedAt?: string }
  flow:   { ok: boolean; inflow: FlowRow[]; outflow: FlowRow[]; inflowCount?: number; outflowCount?: number; elapsedMs?: number; days?: number }
  rotation: { ok: boolean; dates: string[]; rows: RotationRow[]; topN?: number }
}

// =============================================================================
// 9 档涨跌色 (跟 sector-heatmap 一致)
// =============================================================================
const BAND = {
  upExtreme: "#B71C1C", upStrong: "#D32F2F", upMid: "#F44336", upLight: "#EF9A9A", flat: "#9E9E9E",
  downLight: "#A5D6A7", downMid: "#4CAF50", downStrong: "#2E7D32", downExtreme: "#1B5E20",
} as const

function bandColor(pct: number | null | undefined) {
  if (pct == null || !Number.isFinite(pct)) return BAND.flat
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

// =============================================================================
// 工具
// =============================================================================
function prettyDate(d: string) { return d.slice(5) }
function weekday(d: string) {
  const t = new Date(`${d}T00:00:00Z`).getUTCDay()
  return ["日", "一", "二", "三", "四", "五", "六"][t]
}

// =============================================================================
// 顶部
// =============================================================================
function PageHeader({ onRefresh, loading, fetchedAt, flowElapsedMs }: {
  onRefresh: () => void
  loading: boolean
  fetchedAt?: string
  flowElapsedMs?: number
}) {
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <div className="border-b border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-6 sm:p-8 xl:p-10">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
              <Flame className="size-3.5 text-orange-500" />
              行情 · Market Pulse · {fetchedAt ? fetchedAt.slice(0, 19).replace("T", " ") : "—"}
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-[-0.045em] text-slate-950 sm:text-4xl">
              强势板块 · 主力净流入 · 行业轮动
            </h1>
            <p className="text-sm leading-7 text-slate-600">
              数据源: TDX 56 行业指数 (eltdx) · eltdx 200742 主力资金 · 每日收盘 Top N 落盘快照
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
    { label: "领涨",  name: top?.name ?? "—",     pct: top?.changePercent ?? null, amount: fmtAmount(top?.amount), tone: "up"   as const, icon: Flame },
    { label: "领跌",  name: bot?.name ?? "—",     pct: bot?.changePercent ?? null, amount: fmtAmount(bot?.amount), tone: "down" as const, icon: ArrowDownRight },
    { label: "主力净流入", name: inTop?.name ?? "—", net: inTop?.mainNet,  streak: inTop?.consecutiveDays, tone: "up"   as const, icon: Layers },
    { label: "主力净流出", name: outTop?.name ?? "—", net: outTop?.mainNet, streak: outTop?.consecutiveDays, tone: "down" as const, icon: Layers },
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
              {"streak" in it && typeof it.streak === "number" && it.streak !== 0 ? (
                <Badge variant="outline" className={`h-4 px-1.5 text-[10px] ${it.streak > 0 ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
                  {it.streak > 0 ? `连入 ${it.streak}天` : `连出 ${-it.streak}天`}
                </Badge>
              ) : null}
              <span className="text-xs text-slate-400">成交 {it.amount}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------- 1. 强势板块 ----------
function StrongSectors({ data }: { data: MarketPulse["strong"] }) {
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
              TDX 56 行业指数, 按当日涨跌幅排序
            </CardDescription>
          </div>
          <Badge variant="outline" className="rounded-full px-3 py-1 text-xs text-slate-500">
            <TrendingUp className="mr-1 size-3" /> 涨 {top.length} / 跌 {bottom.length}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-5">
        <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          {top.map((s) => (
            <div
              key={`${s.code6}-${s.name}`}
              className="group flex cursor-pointer flex-col justify-between rounded-xl border border-slate-200/60 bg-white p-3.5 transition-shadow hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-900">{s.name}</div>
                  <div className="mt-0.5 text-[11px] text-slate-400">{s.code6}</div>
                </div>
                <div
                  className="rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums"
                  style={{ background: bandColor(s.changePercent), color: bandFg(s.changePercent) }}
                >
                  {fmtPct(s.changePercent)}
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                <span className="tabular-nums">{s.lastPrice?.toFixed(2) ?? "—"}</span>
                <span className="tabular-nums">成交 {fmtAmount(s.amount)}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 border-t border-slate-100 pt-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">弱势</div>
          <div className="flex flex-wrap gap-2">
            {bottom.map((s) => (
              <div
                key={`bot-${s.code6}-${s.name}`}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs"
              >
                <span className="text-slate-700">{s.name}</span>
                <span className="font-semibold tabular-nums" style={{ color: bandColor(s.changePercent) === BAND.flat ? "#475569" : bandColor(s.changePercent) }}>
                  {fmtPct(s.changePercent)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------- 2. 主力净流入 ----------
function CapitalFlow({ data }: { data: MarketPulse["flow"] }) {
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
              eltdx 200742 主力资金走势 · 近 {data?.days ?? 30} 个交易日 · 单位: 元
            </CardDescription>
          </div>
          <Badge variant="outline" className="rounded-full px-3 py-1 text-xs text-slate-500">
            流入 {data?.inflowCount ?? inflow.length} / 流出 {data?.outflowCount ?? outflow.length}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-5 md:grid-cols-2">
        <FlowColumn title="净流入" tone="up" rows={inflow} maxAbs={maxAbs} />
        <FlowColumn title="净流出" tone="down" rows={outflow} maxAbs={maxAbs} />
      </CardContent>
    </Card>
  )
}

function FlowColumn({ title, tone, rows, maxAbs }: { title: string; tone: "up" | "down"; rows: FlowRow[]; maxAbs: number }) {
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
            <div key={r.code6} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-800">{r.name}</span>
                  <span className="text-[10px] text-slate-400">{r.code6}</span>
                </div>
                <div className="flex items-center gap-2 tabular-nums">
                  <span className={`font-semibold ${isUp ? "text-red-700" : "text-emerald-700"}`}>
                    {isUp ? "+" : ""}{(r.mainNet / 1e8).toFixed(2)}亿
                  </span>
                  {r.consecutiveDays > 0 ? (
                    <Badge variant="outline" className="h-4 border-red-200 bg-red-50 px-1.5 text-[10px] text-red-700">
                      连入 {r.consecutiveDays}天
                    </Badge>
                  ) : r.consecutiveDays < 0 ? (
                    <Badge variant="outline" className="h-4 border-emerald-200 bg-emerald-50 px-1.5 text-[10px] text-emerald-700">
                      连出 {-r.consecutiveDays}天
                    </Badge>
                  ) : null}
                </div>
              </div>
              <div className="relative h-2 rounded-full bg-slate-200/70">
                <div
                  className={`absolute top-0 h-2 rounded-full ${isUp ? "bg-red-500" : "bg-emerald-500"}`}
                  style={{ width: `${w}%`, left: isUp ? 0 : "auto", right: isUp ? "auto" : 0 }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------- 3. 行业轮动 (日期 × 行业 Top N) ----------
function IndustryRotation({ data, onRefreshSnapshot }: { data: MarketPulse["rotation"]; onRefreshSnapshot: () => void }) {
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

  // 横向日期数 (取最大 topN, 避免某些天 < topN 报错)
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
                          <div
                            className="flex h-12 flex-col items-center justify-center rounded-md px-1.5 text-center"
                            style={{ background: bandColor(item.changePct), color: bandFg(item.changePct) }}
                            title={`${item.name} (${item.code6}) 当日 ${fmtPct(item.changePct)}`}
                          >
                            <div className="truncate text-xs font-semibold leading-4">{item.name}</div>
                            <div className="text-[10px] font-medium tabular-nums leading-3.5 opacity-90">{fmtPct(item.changePct)}</div>
                          </div>
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

// ---------- 兜底空卡 ----------
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
export default function MarketPulse() {
  const [data, setData] = useState<MarketPulse | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchMarketPulse()
      setData(res as MarketPulse)
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
    } catch (e: any) {
      notification.error(`刷新快照失败: ${e?.message ?? e}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <WorkspaceShell>
      <div className="h-[calc(100svh-4rem)] space-y-4 overflow-y-auto p-3 sm:p-4">
        <PageHeader
          onRefresh={load}
          loading={loading}
          fetchedAt={data?.strong?.fetchedAt}
          flowElapsedMs={data?.flow?.elapsedMs}
        />
        {data ? <SummaryStrip data={data} /> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <StrongSectors data={data?.strong} />
          <CapitalFlow data={data?.flow} />
        </div>
        <IndustryRotation data={data?.rotation} onRefreshSnapshot={refreshSnapshot} />
      </div>
    </WorkspaceShell>
  )
}
