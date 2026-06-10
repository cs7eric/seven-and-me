/**
 * 同花顺行业成分股 Drawer
 *
 * 用途: 在「资金流」Tab 点击某一行业时弹出, 展示该行业 (来自 THS 90 行业) 的全部成分股
 *       涨幅 / 涨跌 / 涨速 / 换手 / 量比 / 振幅 / 成交额 / 流通股 / 流通市值 / 市盈率
 *       全部由后端 /api/stock-chart/ths-industry/constituents?name=... 实时返回
 *       (走 hexin-v 破解, 数据源 q.10jqka.com.cn)
 *
 * 落盘位置: reference/ths-industry/constituents/{code}.json
 *
 * 交互:
 *   - 打开时自动拉一次 (走磁盘缓存, 网络挂掉就 stale)
 *   - 右上角「刷新」按钮强制重爬
 *   - 表头列点击排序 (默认按涨跌幅 desc, 跟资金流表格风格一致)
 *   - 空数据 / 错误 / 加载中 都有明确状态
 */
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Building2,
  ExternalLink,
  RefreshCw,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Drawer,
  DrawerClose,
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
  fetchIndustryConstituentsFromFile,
  refreshIndustryConstituentsByName,
  type IndustryConstituentRow,
  type IndustryConstituentsByNameResponse,
} from "@/lib/api"

// 表格列: 跟 IndustryConstituentRow 的 14 列对齐, 一列不少
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
  // 兼容 "4.65" / "4.65%" / "1.29亿" / "7.51" / "--"
  const s = String(value).trim()
  if (!s || s === "--") return null
  // 处理 "1.29亿" / "25.48亿" 这类中文单位
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
  } else if (s.endsWith("千亿")) {
    mult = 1e11
    body = s.slice(0, -2)
  } else if (s.endsWith("百亿")) {
    mult = 1e10
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

function formatSigned(value: number | string | null | undefined): React.ReactNode {
  const n = toNumber(value)
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

/**
 * 金额字段: 后端返的是 "1.29亿" / "25.48亿" 这种带单位的字符串
 * 前端做原样展示 (跟资金流表格的「流入资金(亿)」风格一致)
 */
function formatAmount(value: number | string | null | undefined): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-400">—</span>
  }
  return <span className="tabular-nums text-slate-700">{String(value)}</span>
}

/** 市盈率可能为 "--" / "亏损" / 负数等, 单独处理 */
function formatPe(value: number | string | null | undefined): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-400">—</span>
  }
  const s = String(value).trim()
  if (!s || s === "--" || s === "亏损" || s === "—") {
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

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------
export interface IndustryConstituentsDrawerProps {
  /** 行业名称 (跟资金流表格的「行业」列一致, 走 name → code 服务端解析) */
  industryName: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function IndustryConstituentsDrawer({
  industryName,
  open,
  onOpenChange,
}: IndustryConstituentsDrawerProps) {
  const [data, setData] = useState<IndustryConstituentsByNameResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [sortKey, setSortKey] = useState<ConstituentSortKey>("涨跌幅(%)")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const load = useCallback(
    async (name: string, refresh: boolean) => {
      if (refresh) setRefreshing(true)
      else setLoading(true)
      try {
        if (refresh) {
          // 显式刷新: 强制重爬网络 (走 hexin-v, 落盘到 reference/ths-industry/constituents/{code}.json)
          const payload = await refreshIndustryConstituentsByName(name)
          if (!payload.ok) {
            throw new Error(payload.error || "加载失败")
          }
          setData(payload)
        } else {
          // 默认打开: 纯读磁盘落盘文件, 不打网络, 不爬 q.10jqka
          // 磁盘没有 (404) 时 fallback 到网络, 提示一下
          try {
            const payload = await fetchIndustryConstituentsFromFile(name)
            setData(payload)
          } catch (err) {
            const code = (err as Error & { code?: string }).code
            if (code === "NOT_CACHED") {
              notification.info({
                title: "暂无磁盘缓存",
                description: `行业 ${name} 还没落盘, 已自动从网络拉取一次`,
              })
              const fallback = await refreshIndustryConstituentsByName(name)
              if (!fallback.ok) {
                throw new Error(fallback.error || "加载失败")
              }
              setData(fallback)
            } else {
              throw err
            }
          }
        }
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
    [],
  )

  // 行业变化 / drawer 重新打开时重拉
  useEffect(() => {
    if (!open || !industryName) {
      // 关闭时清空, 避免下次打开看到上一行业残留
      setData(null)
      return
    }
    void load(industryName, false)
  }, [open, industryName, load])

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

  const handleRefresh = () => {
    if (!industryName) return
    void load(industryName, true)
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
      <DrawerContent
        className="left-auto right-0 top-0 mt-0 h-screen w-full max-w-3xl rounded-none border-l data-[vaul-drawer-direction=right]:sm:max-w-3xl"
      >
        <DrawerHeader className="border-b border-slate-100">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <DrawerTitle className="flex items-center gap-2 text-base">
                <Building2 className="size-4 text-slate-600" />
                {industryName ?? "—"}
                {data?.code ? (
                  <Badge variant="outline" className="border-slate-200 bg-slate-50 font-mono text-[10px] text-slate-600">
                    {data.code}
                  </Badge>
                ) : null}
                {data?.stale ? (
                  <Badge variant="outline" className="ml-1 border-amber-300 bg-amber-50 text-amber-700">
                    缓存数据
                  </Badge>
                ) : null}
              </DrawerTitle>
              <DrawerDescription className="mt-1 text-xs text-slate-500">
                <span>同花顺行业成分股 · 14 列实时行情</span>
                {data?.fetchedAt ? (
                  <>
                    <span className="mx-1.5">·</span>
                    <span>抓取时间: {formatFetchedAt(data.fetchedAt)}</span>
                  </>
                ) : null}
                {data?.totalPages ? (
                  <>
                    <span className="mx-1.5">·</span>
                    <span>
                      共 {data.totalPages} 页 · {(data.count ?? data.rows.length)} 只成分股
                    </span>
                  </>
                ) : null}
                {data?.rows?.length ? (
                  <>
                    <span className="mx-1.5">·</span>
                    <span className="text-red-600">{rising} 涨</span>
                    <span className="mx-1 text-slate-300">/</span>
                    <span className="text-emerald-600">{falling} 跌</span>
                  </>
                ) : null}
              </DrawerDescription>
              {data?.stale && data.staleReason ? (
                <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">
                  最近一次抓取失败, 展示的是磁盘缓存. 原因: {data.staleReason}
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5"
                onClick={handleRefresh}
                disabled={refreshing || loading || !industryName}
              >
                <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
                刷新
              </Button>
              <DrawerClose asChild>
                <Button size="sm" variant="ghost" className="h-8">
                  关闭
                </Button>
              </DrawerClose>
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
                      <td
                        colSpan={COLUMNS.length}
                        className="px-6 py-12 text-center text-sm text-slate-400"
                      >
                        {data?.error ? `加载失败: ${data.error}` : "暂无数据, 点击「刷新」手动抓取"}
                      </td>
                    </tr>
                  ) : (
                    sortedRows.map((row, idx) => (
                      <tr
                        key={`${row["代码"]}-${idx}`}
                        className="hover:bg-slate-50/60"
                      >
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
                          // 名称列: 留作后面可能加点击跳转个股
                          if (col.key === "名称") {
                            return (
                              <td
                                key={col.label}
                                className={cn("whitespace-nowrap px-3 py-1.5 font-medium text-slate-900")}
                              >
                                {row["名称"]}
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
                · 数据源 q.10jqka.com.cn · 落盘 reference/ths-industry/constituents
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
    </Drawer>
  )
}
