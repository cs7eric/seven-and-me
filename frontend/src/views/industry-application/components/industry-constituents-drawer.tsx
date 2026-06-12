/**
 * 同花顺行业成分股 Drawer
 *
 * 用途: 在「资金流」Tab 点击某一行业时弹出, 展示该行业 (THS 90 行业) 的成分股 14 列行情
 *
 * 数据源 (server 端 join):
 *   - membership: reference/ths-industry/constituents_index.json (50 只 code 列表)
 *   - 14 列行情:  reference/stock-universe/ths_industry/constituents/{code}.json
 *   - 后端端点: GET /api/stock-chart/ths-industry/constituents-file?code={code}
 *   - 进程内按 mtime 缓存, scheduler 重写文件自动失效
 *
 * 渲染:
 *   - 14 列: # / 代码 / 名称 / 现价 / 涨跌幅 / 涨跌 / 涨速 / 换手 / 量比 / 振幅 / 成交额 / 流通股 / 流通市值 / 市盈率
 *   - 涨跌色: 涨红 / 跌绿 (跟资金流表格风格一致)
 *   - 表头可点击排序 (默认按涨跌幅 desc)
 *   - 「名称」列是可点击 button, 点开 StockDetailDialog 看 K 线
 */
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Building2,
  ExternalLink,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer"
import { Skeleton } from "@/components/ui/skeleton"
import { notification } from "@/components/ui/notification"
import { cn } from "@/lib/utils"
import {
  fetchIndustryConstituentsFromIndexByCode,
  type IndustryConstituentsIndexResponse,
  type IndustryConstituentRow,
} from "@/lib/api"
import { StockDetailDialog } from "@/components/stock-detail-dialog"

export interface IndustryConstituentsDrawerProps {
  /**
   * 行业 code (6 位, e.g. "881121")
   * 直接拿这个 code 调 /constituents-file, 不走 name → code 解析
   * 解析失败 / 缺失时为 null
   */
  industryCode: string | null
  /** 行业名称, 顶部展示用 (跟资金流表格的「行业」列一致) */
  industryName: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

// ---------------------------------------------------------------------------
// 表格列 (14 列, 跟 IndustryConstituentRow 对齐, 一列不少)
// ---------------------------------------------------------------------------
type ConstituentSortKey =
  | "序号"
  | "现价"
  | "涨跌幅(%)"
  | "涨跌"
  | "涨速(%)"
  | "换手(%)"
  | "量比"
  | "振幅(%)"
type SortDir = "asc" | "desc"

const COLUMNS: Array<{
  key: keyof IndustryConstituentRow
  label: string
  align: "left" | "right" | "center"
  width?: string
  sortable?: ConstituentSortKey
  format?: (r: IndustryConstituentRow) => React.ReactNode
}> = [
  { key: "序号", label: "#", align: "center", width: "w-10" },
  { key: "代码", label: "代码", align: "left", width: "w-20" },
  { key: "名称", label: "名称", align: "left", width: "min-w-[80px]" },
  { key: "现价", label: "现价", align: "right", width: "w-20" },
  {
    key: "涨跌幅(%)",
    label: "涨跌幅",
    align: "right",
    width: "w-24",
    sortable: "涨跌幅(%)",
    format: (r) => formatSignedPercent(r["涨跌幅(%)"]),
  },
  {
    key: "涨跌",
    label: "涨跌",
    align: "right",
    width: "w-20",
    sortable: "涨跌",
    format: (r) => formatSigned(r["涨跌"]),
  },
  {
    key: "涨速(%)",
    label: "涨速",
    align: "right",
    width: "w-16",
    sortable: "涨速(%)",
    format: (r) => formatSignedPercent(r["涨速(%)"]),
  },
  {
    key: "换手(%)",
    label: "换手",
    align: "right",
    width: "w-16",
    sortable: "换手(%)",
    format: (r) => formatPlain(r["换手(%)"], "%", 2),
  },
  {
    key: "量比",
    label: "量比",
    align: "right",
    width: "w-14",
    sortable: "量比",
    format: (r) => formatPlain(r["量比"], "", 2),
  },
  {
    key: "振幅(%)",
    label: "振幅",
    align: "right",
    width: "w-16",
    sortable: "振幅(%)",
    format: (r) => formatPlain(r["振幅(%)"], "%", 2),
  },
  {
    key: "成交额",
    label: "成交额",
    align: "right",
    width: "w-20",
    format: (r) => formatAmount(r["成交额"]),
  },
  {
    key: "流通股",
    label: "流通股",
    align: "right",
    width: "w-20",
    format: (r) => formatAmount(r["流通股"]),
  },
  {
    key: "流通市值",
    label: "流通市值",
    align: "right",
    width: "w-24",
    format: (r) => formatAmount(r["流通市值"]),
  },
  {
    key: "市盈率",
    label: "市盈率",
    align: "right",
    width: "w-16",
    format: (r) => formatPe(r["市盈率"]),
  },
]

// ---------------------------------------------------------------------------
// 格式化
// ---------------------------------------------------------------------------
function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null
  if (typeof value === "number") return Number.isFinite(value) ? value : null
  const s = String(value).trim()
  if (!s || s === "--") return null
  let mult = 1
  let body = s
  if (s.endsWith("亿")) {
    mult = 1e8
    body = s.slice(0, -1)
  } else if (s.endsWith("万")) {
    mult = 1e4
    body = s.slice(0, -1)
  } else if (s.endsWith("万亿")) {
    mult = 1e12
    body = s.slice(0, -2)
  }
  const cleaned = body.replace(/[%\s,]/g, "")
  const n = Number(cleaned)
  if (!Number.isFinite(n)) return null
  return n * mult
}

function formatSignedPercent(value: number | string | null | undefined): React.ReactNode {
  const n = toNumber(value)
  if (n === null) return <span className="text-slate-400">—</span>
  const color = n > 0 ? "text-red-600" : n < 0 ? "text-emerald-600" : "text-slate-700"
  return (
    <span className={cn("tabular-nums", color)}>
      {n > 0 ? "+" : ""}
      {n.toFixed(2)}%
    </span>
  )
}

function formatSigned(value: number | string | null | undefined): React.ReactNode {
  const n = toNumber(value)
  if (n === null) return <span className="text-slate-400">—</span>
  const color = n > 0 ? "text-red-600" : n < 0 ? "text-emerald-600" : "text-slate-700"
  return (
    <span className={cn("tabular-nums", color)}>
      {n > 0 ? "+" : ""}
      {n.toFixed(2)}
    </span>
  )
}

function formatPlain(value: number | string | null | undefined, suffix: string, digits = 2): React.ReactNode {
  const n = toNumber(value)
  if (n === null) return <span className="text-slate-400">—</span>
  return (
    <span className="tabular-nums text-slate-700">
      {n.toFixed(digits)}
      {suffix}
    </span>
  )
}

function formatAmount(value: string | number | null | undefined): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-400">—</span>
  }
  return <span className="tabular-nums text-slate-700">{String(value)}</span>
}

function formatPe(value: string | number | null | undefined): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-400">—</span>
  }
  const s = String(value).trim()
  if (!s || s === "--" || s === "亏损") {
    return <span className="text-slate-400">{s || "—"}</span>
  }
  const n = Number(s)
  if (!Number.isFinite(n)) {
    return <span className="text-slate-700">{s}</span>
  }
  return <span className="tabular-nums text-slate-700">{n.toFixed(2)}</span>
}

function formatFetchedAt(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (v: number) => v.toString().padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function describeTradingMode(
  mode: "trading" | "trading_day_off_hours" | "non_trading_day" | undefined,
): string {
  switch (mode) {
    case "trading":
      return "盘内"
    case "trading_day_off_hours":
      return "盘后/午休"
    case "non_trading_day":
      return "非交易日"
    default:
      return "—"
  }
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------
export function IndustryConstituentsDrawer({
  industryCode,
  industryName,
  open,
  onOpenChange,
}: IndustryConstituentsDrawerProps) {
  const [data, setData] = useState<IndustryConstituentsIndexResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [sortKey, setSortKey] = useState<ConstituentSortKey>("涨跌幅(%)")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  // 点击某只成分股 -> 弹出个股详情 dialog
  const [selectedStock, setSelectedStock] = useState<{
    code: string
    name: string
  } | null>(null)
  const [stockDialogOpen, setStockDialogOpen] = useState(false)

  const load = useCallback(async (code: string) => {
    setLoading(true)
    try {
      const payload = await fetchIndustryConstituentsFromIndexByCode(code)
      if (!payload.ok) {
        throw new Error(payload.error || "加载失败")
      }
      setData(payload)
    } catch (err) {
      const code = (err as Error & { code?: string }).code
      if (code !== "NOT_CACHED") {
        notification.danger({
          title: "加载失败",
          description: err instanceof Error ? err.message : "未知错误",
        })
      }
    } finally {
      setLoading(false)
    }
  }, [])

  // 行业 code 变化 / drawer 重新打开时重拉
  useEffect(() => {
    if (!open || !industryCode) {
      setData(null)
      return
    }
    void load(industryCode)
  }, [open, industryCode, load])

  const sortedRows = useMemo(() => {
    const rows = (data?.rows ?? []) as IndustryConstituentRow[]
    const key = sortKey
    const dir = sortDir
    return [...rows].sort((a, b) => {
      const av = toNumber((a as unknown as Record<string, unknown>)[key] as number | string | null)
      const bv = toNumber((b as unknown as Record<string, unknown>)[key] as number | string | null)
      const an = av === null ? Number.NEGATIVE_INFINITY : av
      const bn = bv === null ? Number.NEGATIVE_INFINITY : bv
      if (an === bn) return 0
      return dir === "asc" ? an - bn : bn - an
    })
  }, [data, sortKey, sortDir])

  const onHeaderClick = (key: ConstituentSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const rising = useMemo(() => {
    if (!data?.rows) return 0
    return data.rows.filter((r) => toNumber(r["涨跌幅(%)"]) && toNumber(r["涨跌幅(%)"])! > 0).length
  }, [data])

  const falling = useMemo(() => {
    if (!data?.rows) return 0
    return data.rows.filter((r) => toNumber(r["涨跌幅(%)"]) && toNumber(r["涨跌幅(%)"])! < 0).length
  }, [data])

  return (
    <Drawer open={open} onOpenChange={onOpenChange} direction="right">
      <DrawerContent className="left-auto right-0 top-0 mt-0 h-screen w-full max-w-6xl rounded-none border-l data-[vaul-drawer-direction=right]:sm:max-w-6xl">
        <DrawerHeader className="border-b border-slate-100">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <DrawerTitle className="flex items-center gap-2 text-base">
                <Building2 className="size-4 text-slate-600" />
                {data?.name ?? industryName ?? "—"}
                {data?.code ? (
                  <Badge variant="outline" className="border-slate-200 bg-slate-50 font-mono text-[10px] text-slate-600">
                    {data.code}
                  </Badge>
                ) : null}
                {data?.matched !== undefined && data?.count !== undefined && data.count > 0 ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "border-slate-200 bg-slate-50 text-[10px] text-slate-600",
                      data.matched < data.count && "border-amber-300 bg-amber-50 text-amber-700",
                    )}
                  >
                    行情 {data.matched}/{data.count}
                  </Badge>
                ) : null}
              </DrawerTitle>
              <DrawerDescription className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                <span>同花顺行业成分股 · 14 列行情</span>
                {data?.snapshotDate ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "border-slate-200 bg-slate-50 text-[10px] font-normal",
                      data.tradingHoursMode === "trading" && "border-blue-200 bg-blue-50 text-blue-700",
                      data.tradingHoursMode === "non_trading_day" && "border-amber-200 bg-amber-50 text-amber-700",
                    )}
                  >
                    快照 {data.snapshotDate} · {describeTradingMode(data.tradingHoursMode)}
                  </Badge>
                ) : null}
                {data?.rowsFetchedAt ? (
                  <>
                    <span>·</span>
                    <span>
                      抓取: <span className="text-slate-700">{formatFetchedAt(data.rowsFetchedAt)}</span>
                    </span>
                  </>
                ) : null}
                {data?.rows?.length ? (
                  <>
                    <span>·</span>
                    <span className="text-red-600">{rising} 涨</span>
                    <span className="text-slate-300">/</span>
                    <span className="text-emerald-600">{falling} 跌</span>
                  </>
                ) : null}
              </DrawerDescription>
            </div>
          </div>
        </DrawerHeader>

        <div className="flex-1 overflow-auto">
          {loading && !data ? (
            <div className="space-y-2 p-6">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase text-slate-500">
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
                          onClick={isSort ? () => onHeaderClick(col.sortable as ConstituentSortKey) : undefined}
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
                        {data?.error ? `加载失败: ${data.error}` : "暂无数据"}
                      </td>
                    </tr>
                  ) : (
                    sortedRows.map((row, idx) => (
                      <tr key={`${row["代码"]}-${idx}`} className="hover:bg-slate-50/60">
                        {COLUMNS.map((col) => {
                          if (col.format) {
                            return (
                              <td
                                key={col.label}
                                className={cn(
                                  "whitespace-nowrap px-3 py-1.5",
                                  col.align === "right" && "text-right",
                                  col.align === "center" && "text-center",
                                  col.align === "left" && "text-left",
                                )}
                              >
                                {col.format(row)}
                              </td>
                            )
                          }
                          // 名称列: button, 点击打开个股详情 dialog
                          if (col.key === "名称") {
                            const stockCode = String(row["代码"] ?? "")
                            const stockName = String(row["名称"] ?? "")
                            return (
                              <td
                                key={col.label}
                                className="whitespace-nowrap px-3 py-1.5 font-medium text-slate-900"
                              >
                                <button
                                  type="button"
                                  className="cursor-pointer rounded px-1 py-0.5 text-left text-slate-900 transition hover:bg-slate-100 hover:text-blue-600"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    if (!stockCode) return
                                    setSelectedStock({ code: stockCode, name: stockName || stockCode })
                                    setStockDialogOpen(true)
                                  }}
                                  title={`查看 ${stockName || stockCode} 详情`}
                                >
                                  {stockName || "—"}
                                </button>
                              </td>
                            )
                          }
                          const raw = (row as unknown as Record<string, unknown>)[col.key as string]
                          return (
                            <td
                              key={col.label}
                              className={cn(
                                "whitespace-nowrap px-3 py-1.5",
                                col.key === "序号" && "text-center tabular-nums text-slate-500",
                                col.key === "代码" && "font-mono text-xs text-slate-600",
                                col.align === "right" && "text-right tabular-nums",
                              )}
                            >
                              {raw === null || raw === undefined || raw === "" ? "—" : String(raw)}
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
        </div>

        <DrawerFooter className="border-t border-slate-100">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1">
                <span className="inline-block size-2 rounded-full bg-red-500" />
                上涨
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block size-2 rounded-full bg-emerald-500" />
                下跌
              </span>
              <span className="text-slate-400">
                · 数据源 constituents_index.json (membership) + stock-universe/ths_industry/constituents/{data?.code || "code"}.json (14 列行情)
              </span>
            </div>
            {data?.code ? (
              <a
                className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900"
                href={`https://q.10jqka.com.cn/thshy/detail/code/${data.code}/`}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="size-3" />
                同花顺源页
              </a>
            ) : null}
          </div>
        </DrawerFooter>
      </DrawerContent>

      <StockDetailDialog
        open={stockDialogOpen}
        onOpenChange={setStockDialogOpen}
        stockCode={selectedStock?.code ?? null}
        stockName={selectedStock?.name ?? null}
        industryName={industryName}
      />
    </Drawer>
  )
}
