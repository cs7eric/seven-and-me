/**
 * 股票详情 Dialog
 *
 * 用途: 在成分股 drawer 里点击某只股票时弹出, 展示该个股的详情
 *
 * 布局:
 *   - 占屏幕宽度 2/3 (max-w-[min(1200px,66.67vw)])
 *   - 顶部 header: 股票名 + 代码 + 行业 + 关闭按钮 (单行)
 *   - 主体: grid-cols-10, 左 7 份 IndicatorToolbar + ChartPanel, 右 3 份内容区 (占位)
 *
 * 数据:
 *   - K 线 / MA / 副图指标: 复用 stock-chart 的 IndicatorToolbar + ChartPanel
 *   - fetchStockKlines 按 period / adjust 拉
 *   - 右侧 4 个 section 仍是占位, 后期按需接入
 */
import { useCallback, useEffect, useState } from "react"
import { Building2, ExternalLink, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { fetchStockKlines } from "@/lib/api"
import { ChartPanel } from "@/views/stock-chart/components/chart-panel"
import { IndicatorToolbar } from "@/views/stock-chart/components/indicator-toolbar"
import type { StockAdjust, StockKlineBar, StockPeriod, StockSignalPoint } from "@/views/stock-chart/lib/types"

export interface StockDetailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 股票代码, 例如 "300970" / "600597" */
  stockCode: string | null
  /** 股票名称 */
  stockName: string | null
  /** 所在行业名称, 顶部 badge 用 */
  industryName?: string | null
}

// K 线工具栏的默认值 (跟 stock-chart lib/store.ts 保持一致, 但少 MA 主图指标,
// 因为 IndicatorToolbar 用 activeIndicators 控制副图, MA 走 maLines)
const DEFAULT_PERIOD: StockPeriod = "1d"
const DEFAULT_ADJUST: StockAdjust = "qfq"
const DEFAULT_INDICATORS: string[] = ["BOLL", "MACD", "AMOUNT"]
const DEFAULT_MA_LINES: number[] = [5, 10, 30]

// 右侧内容区 section, 后期接入数据时按这里填
const RIGHT_SECTIONS: Array<{
  key: string
  title: string
  rows: Array<{ label: string; hint: string }>
}> = [
  {
    key: "basic",
    title: "股票基本信息",
    rows: [
      { label: "现价", hint: "实时行情接入" },
      { label: "今开 / 昨收", hint: "—" },
      { label: "最高 / 最低", hint: "—" },
      { label: "成交量 / 成交额", hint: "—" },
      { label: "总市值 / 流通市值", hint: "—" },
      { label: "市盈率 / 市净率", hint: "—" },
    ],
  },
  {
    key: "indicators",
    title: "技术指标快照",
    rows: [
      { label: "MA5 / MA10 / MA20", hint: "—" },
      { label: "MACD / KDJ / RSI", hint: "—" },
      { label: "BOLL 上下轨", hint: "—" },
    ],
  },
  {
    key: "fundamental",
    title: "财务指标",
    rows: [
      { label: "EPS / 每股净资产", hint: "—" },
      { label: "ROE / ROA", hint: "—" },
      { label: "营收 / 净利润同比", hint: "—" },
    ],
  },
  {
    key: "news",
    title: "近期公告 / 新闻",
    rows: [
      { label: "公告列表", hint: "— 条" },
      { label: "研报 / 评级", hint: "— 条" },
    ],
  },
]

export function StockDetailDialog({
  open,
  onOpenChange,
  stockCode,
  stockName,
  industryName,
}: StockDetailDialogProps) {
  const [period, setPeriod] = useState<StockPeriod>(DEFAULT_PERIOD)
  const [adjust, setAdjust] = useState<StockAdjust>(DEFAULT_ADJUST)
  const [indicators, setIndicators] = useState<string[]>(DEFAULT_INDICATORS)
  const [maLines, setMaLines] = useState<number[]>(DEFAULT_MA_LINES)
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [barsLoading, setBarsLoading] = useState(false)

  const hasStock = !!stockCode && !!stockName

  const handleToggleIndicator = useCallback((key: string) => {
    setIndicators((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }, [])

  const handleToggleMALine = useCallback((line: number) => {
    setMaLines((prev) => {
      const next = prev.includes(line)
        ? prev.filter((l) => l !== line)
        : [...prev, line]
      return next.sort((a, b) => a - b)
    })
  }, [])

  // 拉 K 线: stockCode / period / adjust 任一变化都重新拉
  useEffect(() => {
    if (!open || !hasStock) return
    let active = true
    setBarsLoading(true)
    fetchStockKlines({
      targetType: "stock",
      symbol: stockCode,
      name: stockName,
      period,
      adjust,
    })
      .then((res) => {
        if (!active) return
        setBars(res.items || [])
      })
      .catch(() => {
        if (active) setBars([])
      })
      .finally(() => {
        if (active) setBarsLoading(false)
      })
    return () => {
      active = false
    }
  }, [open, hasStock, stockCode, stockName, period, adjust])

  // 关闭时清空 bars 避免下次打开看到残留
  useEffect(() => {
    if (!open) {
      setBars([])
      setBarsLoading(false)
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // 关掉 shadcn 自带右上角 X (我们在 header 自己画一个)
        showCloseButton={false}
        // 宽度: 屏幕的 90vw, 上限 1600px (留 5vw 边距, 比 2/3 更宽松)
        className={cn(
          "left-1/2 top-1/2 w-[min(1600px,90vw)] max-w-[min(1600px,calc(100vw-4rem))] translate-x-[-50%] translate-y-[-50%] gap-0 overflow-hidden p-0",
          "grid-rows-[auto_1fr] sm:max-w-[min(1600px,calc(100vw-4rem))]",
        )}
      >
        <DialogHeader className="flex flex-row items-center justify-between gap-3 border-b border-slate-100 px-6 py-3.5 text-left">
          <div className="min-w-0 flex-1">
            <DialogTitle className="flex items-center gap-2 text-base">
              <span className="truncate font-mono text-slate-500">{stockCode}</span>
              <span className="text-slate-300">·</span>
              <span className="truncate font-semibold text-slate-900">
                {stockName ?? "—"}
              </span>
              {hasStock ? (
                <a
                  className="ml-0.5 inline-flex items-center gap-1 rounded text-slate-400 transition hover:text-slate-700"
                  href={`https://stockpage.10jqka.com.cn/${stockCode}/`}
                  target="_blank"
                  rel="noreferrer"
                  title="同花顺个股页"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              ) : null}
              {industryName ? (
                <Badge
                  variant="outline"
                  className="border-slate-200 bg-slate-50 text-[10px] text-slate-600"
                >
                  <Building2 className="mr-0.5 size-3" />
                  {industryName}
                </Badge>
              ) : null}
            </DialogTitle>
            <DialogDescription className="mt-0.5 text-xs text-slate-500">
              个股详情 · K 线 + 基本面 (右侧区域为占位, 后期接入数据)
            </DialogDescription>
          </div>
          <DialogClose asChild>
            <Button size="icon-sm" variant="ghost" className="size-8" aria-label="关闭">
              <X className="size-4" />
            </Button>
          </DialogClose>
        </DialogHeader>

        <div className="grid h-[min(880px,calc(100vh-8rem))] grid-cols-10 overflow-hidden">
          {/* 左侧 K 线图: 7 份 (70%) */}
          <div className="col-span-7 flex flex-col border-r border-slate-100 bg-slate-50/30">
            <div className="border-b border-slate-100 bg-white px-4 py-2">
              <IndicatorToolbar
                period={period}
                adjust={adjust}
                activeIndicators={indicators}
                maLines={maLines}
                onPeriodChange={setPeriod}
                onAdjustChange={setAdjust}
                onToggleIndicator={handleToggleIndicator}
                onToggleMALine={handleToggleMALine}
                compact
              />
            </div>
            <div className="flex-1 overflow-hidden p-3">
              {hasStock ? (
                barsLoading && bars.length === 0 ? (
                  <div className="flex h-full w-full flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-4 w-48" />
                    <div className="flex-1">
                      <Skeleton className="h-full w-full" />
                    </div>
                    <Skeleton className="h-3 w-40" />
                  </div>
                ) : (
                  <div className="h-full w-full rounded-xl border border-slate-200 bg-white">
                    <ChartPanel
                      bars={bars}
                      annotations={[]}
                      overlayAnnotations={[]}
                      bsSignals={[] as StockSignalPoint[]}
                      manualSignalMode={null}
                      onManualSignalCreate={() => undefined}
                      symbol={stockCode}
                      period={period}
                      indicators={indicators}
                      maLines={maLines}
                    />
                  </div>
                )
              ) : (
                <EmptyPlaceholder />
              )}
            </div>
          </div>

          {/* 右侧内容区: 3 份 (30%) */}
          <div className="col-span-3 flex flex-col bg-white">
            <div className="border-b border-slate-100 px-4 py-2.5 text-xs font-medium text-slate-600">
              详情面板
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {RIGHT_SECTIONS.map((section) => (
                <section
                  key={section.key}
                  className="rounded-xl border border-slate-100 bg-white p-3"
                >
                  <div className="mb-2 text-xs font-semibold text-slate-700">
                    {section.title}
                  </div>
                  <ul className="space-y-1.5">
                    {section.rows.map((row) => (
                      <li
                        key={row.label}
                        className="flex items-center justify-between text-[11px] text-slate-500"
                      >
                        <span className="text-slate-600">{row.label}</span>
                        <span className="tabular-nums text-slate-400">{row.hint}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function EmptyPlaceholder() {
  return (
    <div className="flex h-full w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white text-xs text-slate-400">
      请选择股票
    </div>
  )
}
