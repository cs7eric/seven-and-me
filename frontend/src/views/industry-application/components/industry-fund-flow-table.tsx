/**
 * 同花顺全行业主力资金表格
 *
 * 数据源: GET /api/stock-chart/ths-industry/fund-flow
 * 字段 (跟 guide 原文一致, 中文表头):
 *   序号 / 行业 / 行业指数涨跌幅 / 流入资金(亿) / 流出资金(亿) / 净额(亿) /
 *   公司家数 / 领涨股 / 领涨股涨跌幅 / 当前价(元)
 *
 * 交互:
 *   - "刷新" 按钮: 强制重爬 (POST /api/stock-chart/ths-industry/fund-flow/refresh)
 *   - top 切换: 全量 / Top 50 / Top 20 / Top 10
 *   - 涨跌幅 / 净额 列点击排序 (默认按净额 desc)
 *   - stale=true 时 (爬失败) 标黄 + 提示原因
 */
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Building2,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { notification } from "@/components/ui/notification"
import {
  fetchIndustryFundFlow,
  refreshIndustryFundFlow,
  type IndustryFundFlowResponse,
  type IndustryFundFlowRow,
} from "@/lib/api"

const TOP_OPTIONS: Array<{ value: number | null; label: string }> = [
  { value: null, label: "全部" },
  { value: 50, label: "Top 50" },
  { value: 20, label: "Top 20" },
  { value: 10, label: "Top 10" },
]

type SortKey = "行业指数涨跌幅" | "流入资金(亿)" | "流出资金(亿)" | "净额(亿)" | "领涨股涨跌幅"
type SortDir = "asc" | "desc"

type ColumnKey = keyof IndustryFundFlowRow | "sortable"

// 跟 guide 表头顺序保持一致 (pandas dropna 之后的列, 序号后插)
const COLUMNS: Array<{
  key: ColumnKey
  label: string
  align?: "left" | "right" | "center"
  width?: string
  sortable?: SortKey
  format?: (row: IndustryFundFlowRow) => React.ReactNode
}> = [
  { key: "序号", label: "#", align: "center", width: "w-12" },
  { key: "行业", label: "行业", align: "left", width: "min-w-[120px]" },
  {
    key: "sortable",
    label: "行业指数涨跌幅",
    align: "right",
    width: "w-32",
    sortable: "行业指数涨跌幅",
    format: (r) => formatPercent(r["行业指数涨跌幅"]),
  },
  {
    key: "sortable",
    label: "流入资金(亿)",
    align: "right",
    width: "w-28",
    sortable: "流入资金(亿)",
    format: (r) => formatYi(r["流入资金(亿)"]),
  },
  {
    key: "sortable",
    label: "流出资金(亿)",
    align: "right",
    width: "w-28",
    sortable: "流出资金(亿)",
    format: (r) => formatYi(r["流出资金(亿)"]),
  },
  {
    key: "sortable",
    label: "净额(亿)",
    align: "right",
    width: "w-28",
    sortable: "净额(亿)",
    format: (r) => formatNet(r["净额(亿)"]),
  },
  {
    key: "公司家数",
    label: "公司家数",
    align: "right",
    width: "w-20",
    format: (r) => formatInt(r["公司家数"]),
  },
  { key: "领涨股", label: "领涨股", align: "left", width: "min-w-[100px]" },
  {
    key: "sortable",
    label: "领涨股涨跌幅",
    align: "right",
    width: "w-28",
    sortable: "领涨股涨跌幅",
    format: (r) => formatPercent(r["领涨股涨跌幅"]),
  },
  {
    key: "当前价(元)",
    label: "当前价(元)",
    align: "right",
    width: "w-24",
    format: (r) => formatPrice(r["当前价(元)"]),
  },
]

// ---------------------------------------------------------------------------
// 格式化工具
// ---------------------------------------------------------------------------
function toFinite(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null
  if (typeof value === "number") return Number.isFinite(value) ? value : null
  // 可能是 "4.65%" / "4.65"
  const cleaned = String(value).replace(/[%\s]/g, "")
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : null
}

function formatYi(value: number | string | null | undefined): string {
  const n = toFinite(value)
  if (n === null) return "—"
  return n.toFixed(2)
}

function formatNet(value: number | string | null | undefined): React.ReactNode {
  const n = toFinite(value)
  if (n === null) return <span className="text-slate-400">—</span>
  const positive = n > 0
  const negative = n < 0
  const color = positive
    ? "text-red-600"
    : negative
      ? "text-emerald-600"
      : "text-slate-700"
  return (
    <span className={cn("font-medium tabular-nums", color)}>
      {positive ? "+" : ""}
      {n.toFixed(2)}
    </span>
  )
}

function formatPercent(value: number | string | null | undefined): React.ReactNode {
  const n = toFinite(value)
  if (n === null) return <span className="text-slate-400">—</span>
  const positive = n > 0
  const negative = n < 0
  const color = positive
    ? "text-red-600"
    : negative
      ? "text-emerald-600"
      : "text-slate-700"
  return (
    <span className={cn("tabular-nums", color)}>
      {positive ? "+" : ""}
      {n.toFixed(2)}%
    </span>
  )
}

function formatInt(value: number | string | null | undefined): string {
  const n = toFinite(value)
  if (n === null) return "—"
  return Math.round(n).toLocaleString("zh-CN")
}

function formatPrice(value: number | string | null | undefined): string {
  const n = toFinite(value)
  if (n === null) return "—"
  return n.toFixed(2)
}

function formatFetchedAt(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (v: number) => v.toString().padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------
export function IndustryFundFlowTable() {
  const [data, setData] = useState<IndustryFundFlowResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [top, setTop] = useState<number | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>("净额(亿)")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  // 排序只在客户端做, 不打到后端 (后端已经按净额 desc 排好, 我们切也行)

  const load = useCallback(
    async (refresh: boolean) => {
      if (refresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      try {
        const payload = refresh
          ? await refreshIndustryFundFlow()
          : await fetchIndustryFundFlow(top ? { top } : {})
        if (!payload.ok) {
          throw new Error(payload.error || "加载失败")
        }
        setData(payload)
      } catch (err) {
        notification.danger({
          title: refresh ? "刷新失败" : "加载失败",
          description: err instanceof Error ? err.message : "未知错误",
        })
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [top],
  )

  // 首次 / top 变化时拉一次 (refresh 走手动按钮)
  useEffect(() => {
    void load(false)
  }, [load])

  // 排序后的 rows
  const sortedRows = useMemo(() => {
    const rows = (data?.rows ?? []) as IndustryFundFlowRow[]
    const key = sortKey
    const dir = sortDir
    return [...rows].sort((a, b) => {
      const av = toFinite((a as unknown as Record<string, unknown>)[key] as number | string | null)
      const bv = toFinite((b as unknown as Record<string, unknown>)[key] as number | string | null)
      const an = av === null ? Number.NEGATIVE_INFINITY : av
      const bn = bv === null ? Number.NEGATIVE_INFINITY : bv
      if (an === bn) return 0
      return dir === "asc" ? an - bn : bn - an
    })
  }, [data, sortKey, sortDir])

  const onHeaderClick = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  return (
    <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <CardHeader className="border-b border-slate-100">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Building2 className="size-4 text-slate-600" />
              同花顺全行业主力资金
              {data?.stale ? (
                <Badge variant="outline" className="ml-1 border-amber-300 bg-amber-50 text-amber-700">
                  缓存数据
                </Badge>
              ) : null}
            </CardTitle>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span>
                数据源: <code className="rounded bg-slate-100 px-1">data.10jqka.com.cn/funds/hyzj1</code>
              </span>
              <span>·</span>
              <span>
                抓取时间: <span className="text-slate-700">{formatFetchedAt(data?.fetchedAt)}</span>
              </span>
              {data?.totalPages ? (
                <>
                  <span>·</span>
                  <span>
                    共 {data.totalPages} 页 · {data.rowCount ?? data.rows.length} 个行业
                  </span>
                </>
              ) : null}
            </div>
            {data?.stale && data.staleReason ? (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">
                最近一次抓取失败, 展示的是磁盘缓存. 原因: {data.staleReason}
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center rounded-xl border border-slate-200 bg-white p-0.5 text-xs">
              {TOP_OPTIONS.map((opt) => (
                <button
                  key={String(opt.value)}
                  onClick={() => setTop(opt.value)}
                  className={cn(
                    "rounded-lg px-2.5 py-1 transition",
                    top === opt.value
                      ? "bg-slate-950 text-white"
                      : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              onClick={() => void load(true)}
              disabled={refreshing || loading}
            >
              <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
              刷新
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {loading && !data ? (
          <div className="space-y-2 p-6">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  {COLUMNS.map((col) => {
                    const isSort = col.sortable
                    const active = isSort && sortKey === col.sortable
                    return (
                      <th
                        key={col.label}
                        className={cn(
                          "whitespace-nowrap px-3 py-2.5 font-medium",
                          col.align === "right" && "text-right",
                          col.align === "center" && "text-center",
                          col.align === "left" && "text-left",
                          isSort && "cursor-pointer select-none hover:text-slate-700",
                        )}
                        onClick={isSort ? () => onHeaderClick(col.sortable as SortKey) : undefined}
                      >
                        <span className="inline-flex items-center gap-1">
                          {col.label}
                          {isSort ? (
                            active ? (
                              sortDir === "desc" ? (
                                <ArrowDown className="size-3" />
                              ) : (
                                <ArrowUp className="size-3" />
                              )
                            ) : (
                              <ArrowDownUp className="size-3 opacity-30" />
                            )
                          ) : null}
                        </span>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sortedRows.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="px-6 py-12 text-center text-sm text-slate-400">
                      暂无数据, 点击「刷新」手动抓取
                    </td>
                  </tr>
                ) : (
                  sortedRows.map((row, idx) => (
                    <tr key={`${row["行业"]}-${idx}`} className="hover:bg-slate-50/60">
                      {COLUMNS.map((col) => {
                        if (col.key === "sortable" && col.format) {
                          return (
                            <td
                              key={col.label}
                              className={cn(
                                "whitespace-nowrap px-3 py-2",
                                col.align === "right" && "text-right",
                                col.align === "center" && "text-center",
                                col.align === "left" && "text-left",
                              )}
                            >
                              {col.format(row)}
                            </td>
                          )
                        }
                        const raw = (row as unknown as Record<string, unknown>)[col.key as string]
                        const isRank = col.key === "序号"
                        const isIndustry = col.key === "行业"
                        const isLeader = col.key === "领涨股"
                        return (
                          <td
                            key={col.label}
                            className={cn(
                              "whitespace-nowrap px-3 py-2",
                              isRank && "text-center tabular-nums text-slate-500",
                              isIndustry && "font-medium text-slate-900",
                              isLeader && "text-slate-700",
                              !isRank && !isIndustry && !isLeader && col.align === "right" && "text-right tabular-nums",
                              col.width,
                            )}
                          >
                            {isRank
                              ? ((data?.rows ?? []).indexOf(row) + 1)
                              : raw === null || raw === undefined || raw === ""
                                ? "—"
                                : String(raw)}
                          </td>
                        )
                      })}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block size-2 rounded-full bg-red-500" />
            资金净流入
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block size-2 rounded-full bg-emerald-500" />
            资金净流出
          </span>
          {top ? (
            <span className="text-slate-400">
              · 已截取 Top {top}
            </span>
          ) : null}
        </div>
        <div className="inline-flex items-center gap-2">
          <Button
            size="icon-sm"
            variant="ghost"
            disabled
            className="size-7"
            aria-label="上一页"
          >
            <ChevronLeft className="size-3.5" />
          </Button>
          <span className="tabular-nums text-slate-400">
            {sortedRows.length} 行
          </span>
          <Button
            size="icon-sm"
            variant="ghost"
            disabled
            className="size-7"
            aria-label="下一页"
          >
            <ChevronRight className="size-3.5" />
          </Button>
        </div>
      </div>
    </Card>
  )
}

// 避免 Tree-shake 报警
export { TrendingUp, TrendingDown }
