/**
 * 行业 / 概念 同花顺式涨跌总览热力图
 *
 * 布局: 单一长方形容器 + CSS grid 子格
 * 颜色: A股风格 (涨=红, 跌=绿), 强度按 |change_pct| 量化
 * 排序: 默认按 change_pct 降序, 可切换 振幅/成交额/跌幅
 */
import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Building2, RefreshCw, Sparkles } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

import type { SectorOverviewItem } from "../lib/types"

interface Props {
  items: SectorOverviewItem[]
  loading: boolean
  onRefresh: () => void
  lastUpdated: string | null
}

type SortKey = "change_pct" | "change_pct_abs" | "amplitude_pct" | "amount"
type SortDir = "desc" | "asc"

const SORT_LABEL: Record<SortKey, string> = {
  change_pct: "涨幅",
  change_pct_abs: "振幅",
  amplitude_pct: "振幅%",
  amount: "成交额",
}

const PALETTE_STOPS = 9 // 颜色档位数 (含中性)

/**
 * 把 |change_pct| 映射到 9 档色阶 (A股风格)。
 * 0% -> 灰白; 0-1% -> 浅红/浅绿; 5%+ -> 深红/深绿
 */
function tierForChange(pct: number, maxAbs: number): number {
  const abs = Math.abs(pct)
  if (abs === 0) return 0
  // 用 maxAbs 自适应: 避免所有 0.x% 涨跌幅都打成同一档浅色
  const normalized = Math.min(abs / Math.max(maxAbs, 0.5), 1)
  return Math.min(Math.ceil(normalized * (PALETTE_STOPS - 1)), PALETTE_STOPS - 1)
}

function cellStyle(tier: number, up: boolean): {
  bg: string
  text: string
  border: string
} {
  if (tier === 0) {
    return {
      bg: "bg-slate-50",
      text: "text-slate-500",
      border: "border-slate-200",
    }
  }
  // 涨=红 (red), 跌=绿 (green)
  // tier 1 -> 100, 2 -> 200, ..., 8 -> 800
  const intensity = (tier + 1) * 100
  const bg = up ? `bg-red-${intensity}` : `bg-green-${intensity}`
  // 文字: tier >= 4 用白色, 否则深色
  const text = tier >= 4 ? "text-white" : up ? "text-red-900" : "text-green-900"
  const border = tier >= 4 ? "border-transparent" : up ? "border-red-200" : "border-green-200"
  return { bg, text, border }
}

function fmtPct(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}%`
}

function fmtAmount(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value) || value === 0) return ""
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return value.toFixed(0)
}

export function SectorHeatmap({ items, loading, onRefresh, lastUpdated }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("change_pct")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const [kindFilter, setKindFilter] = useState<"all" | "industry" | "concept">("all")

  const filtered = useMemo(() => {
    const arr = items.filter((it) =>
      kindFilter === "all" ? true : it.kind === kindFilter,
    )
    const sorted = [...arr].sort((a, b) => {
      const key = sortKey
      const va = (a[key] as number | null | undefined) ?? 0
      const vb = (b[key] as number | null | undefined) ?? 0
      return sortDir === "desc" ? vb - va : va - vb
    })
    return sorted
  }, [items, sortKey, sortDir, kindFilter])

  // 用于色阶归一化: max(|change_pct|) 决定分档区间
  const maxAbsChange = useMemo(() => {
    let max = 0
    for (const it of items) {
      const v = Math.abs(it.change_pct ?? 0)
      if (v > max) max = v
    }
    return max
  }, [items])

  const industryCount = useMemo(() => items.filter((i) => i.kind === "industry").length, [items])
  const conceptCount = useMemo(() => items.filter((i) => i.kind === "concept").length, [items])

  return (
    <Card className="h-full rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
      <CardHeader className="border-b border-slate-200/60 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="inline-flex size-7 items-center justify-center rounded-xl bg-slate-950 text-white">
                <Building2 className="size-3.5" />
              </span>
              板块涨跌总览
              <span className="text-xs font-normal text-slate-400">
                同花顺式
              </span>
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
              <Badge variant="outline" className="rounded-full border-blue-200 bg-blue-50 text-blue-700">
                <Building2 className="mr-1 size-3" />
                行业 {industryCount}
              </Badge>
              <Badge variant="outline" className="rounded-full border-violet-200 bg-violet-50 text-violet-700">
                <Sparkles className="mr-1 size-3" />
                概念 {conceptCount}
              </Badge>
              <span>· 共 {items.length} 个标的</span>
              {lastUpdated ? (
                <span>· 数据 {new Date(lastUpdated).toLocaleString("zh-CN", { hour12: false })}</span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <KindToggle kindFilter={kindFilter} setKindFilter={setKindFilter} />
            <SortPicker
              sortKey={sortKey}
              setSortKey={setSortKey}
              sortDir={sortDir}
              setSortDir={setSortDir}
            />
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading}>
              <RefreshCw className={cn("mr-1 size-3.5", loading && "animate-spin")} />
              {loading ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="h-[calc(100%-5.5rem)] p-3">
        {items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            {loading ? "拉取行情中…" : "暂无数据"}
          </div>
        ) : (
          <div
            className="grid h-full gap-1.5 overflow-auto"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
              gridAutoRows: "minmax(60px, 1fr)",
              alignContent: "start",
            }}
          >
            {filtered.map((it) => (
              <Cell key={it.full_code} item={it} maxAbs={maxAbsChange} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Cell({ item, maxAbs }: { item: SectorOverviewItem; maxAbs: number }) {
  const pct = item.change_pct ?? 0
  const tier = tierForChange(pct, maxAbs)
  const up = pct > 0
  const style = cellStyle(tier, up)
  const Icon = item.kind === "industry" ? Building2 : Sparkles
  return (
    <div
      className={cn(
        "group relative flex flex-col items-stretch justify-between overflow-hidden rounded-lg border p-2 transition-all",
        style.bg,
        style.text,
        style.border,
        "hover:z-10 hover:scale-[1.04] hover:shadow-md",
      )}
      title={`${item.name} (${item.full_code})\n最新: ${(item.last_price ?? 0).toFixed(2)}\n涨跌: ${fmtPct(pct)}\n振幅: ${fmtPct(item.amplitude_pct)}\n成交额: ${fmtAmount(item.amount)}\n来源: ${item.kind === "industry" ? "申万行业" : "概念主题"}`}
    >
      <div className="flex items-start justify-between gap-1">
        <Icon
          className={cn(
            "size-3 shrink-0 opacity-70",
            item.kind === "industry" ? "" : "opacity-90",
          )}
        />
        {pct !== 0 ? (
          up ? (
            <ArrowUp className="size-3 shrink-0 opacity-70" />
          ) : (
            <ArrowDown className="size-3 shrink-0 opacity-70" />
          )
        ) : null}
      </div>
      <div className="truncate text-[11px] font-medium leading-tight">{item.name}</div>
      <div className="flex items-baseline justify-between gap-1 font-mono">
        <span className="text-sm font-bold leading-none tracking-tight">
          {fmtPct(pct, Math.abs(pct) < 1 ? 2 : 2)}
        </span>
        {item.amount && item.amount > 0 ? (
          <span className="text-[9px] opacity-70">{fmtAmount(item.amount)}</span>
        ) : null}
      </div>
    </div>
  )
}

function KindToggle({
  kindFilter,
  setKindFilter,
}: {
  kindFilter: "all" | "industry" | "concept"
  setKindFilter: (v: "all" | "industry" | "concept") => void
}) {
  return (
    <div className="flex h-8 items-center rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px]">
      {(
        [
          { v: "all", label: "全部" },
          { v: "industry", label: "行业" },
          { v: "concept", label: "概念" },
        ] as const
      ).map((opt) => (
        <button
          key={opt.v}
          onClick={() => setKindFilter(opt.v)}
          className={cn(
            "h-7 rounded-md px-2 font-medium transition-colors",
            kindFilter === opt.v
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function SortPicker({
  sortKey,
  setSortKey,
  sortDir,
  setSortDir,
}: {
  sortKey: SortKey
  setSortKey: (v: SortKey) => void
  sortDir: SortDir
  setSortDir: (v: SortDir) => void
}) {
  return (
    <div className="flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1 text-[11px]">
      <span className="px-1 text-slate-500">排序</span>
      <select
        value={sortKey}
        onChange={(e) => setSortKey(e.target.value as SortKey)}
        className="h-7 rounded-md border border-transparent bg-transparent px-1 text-slate-700 outline-none focus:border-slate-200"
      >
        {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
          <option key={k} value={k}>
            {SORT_LABEL[k]}
          </option>
        ))}
      </select>
      <button
        onClick={() => setSortDir(sortDir === "desc" ? "asc" : "desc")}
        className="flex h-7 items-center gap-0.5 rounded-md border border-transparent px-1.5 text-slate-700 hover:border-slate-200"
        title="切换排序方向"
      >
        {sortDir === "desc" ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />}
        <span className="text-[10px]">{sortDir === "desc" ? "降" : "升"}</span>
      </button>
    </div>
  )
}
