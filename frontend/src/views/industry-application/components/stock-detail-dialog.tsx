/**
 * 股票详情 Dialog
 *
 * 用途: 在成分股 drawer 里点击某只股票时弹出, 展示该个股的详情
 *
 * 布局:
 *   - 占屏幕宽度 2/3 (max-w-[min(1200px,66.67vw)])
 *   - 顶部 header: 股票名 + 代码 + 行业 + 关闭按钮 (单行)
 *   - 主体: grid-cols-10, 左 7 份 IndicatorToolbar + ChartPanel, 右 3 份内容区
 *
 * 数据:
 *   - K 线 / MA / 副图指标: 复用 stock-chart 的 IndicatorToolbar + ChartPanel
 *   - fetchStockKlines 按 period / adjust 拉
 *   - 右侧内容:
 *     - 股票基本信息: 取 K线最后一根 (现价/今开/昨收/最高/最低/成交量) +
 *       stock-meta (总市值/流通市值) + F10 valuation (PE/PB)
 *     - 技术指标快照: MA/MACD/KDJ/BOLL (前端 indicator-utils 算)
 *     - 财务指标: F10 finance-report (zcfzb) + business-composition (主营构成)
 *     - 近期公告 / 新闻 / 路演 / 研报: F10 announcements / news / roadshows / company-news
 */
import { useCallback, useEffect, useMemo, useState } from "react"
import { Building2, ExternalLink, FileText, Megaphone, Newspaper, Presentation, X } from "lucide-react"

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
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import {
  fetchStockKlines,
  fetchStockMeta,
  fetchStockValuation,
  fetchStockBusinessComposition,
  fetchStockFinanceReport,
  fetchStockAnnouncements,
  fetchStockNews,
  fetchStockRoadshows,
  fetchStockCompanyNews,
  type StockAnnouncementsResponse,
  type StockBusinessCompositionResponse,
  type StockCompanyNewsResponse,
  type StockMetaResponse,
  type StockNewsResponse,
  type StockRoadshowsResponse,
  type StockValuationResponse,
} from "@/lib/api"
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

// 资产负债表里常用 T 字段含义 (T 编号在不同 report_type 下含义不同, 这里只覆盖 zcfzb)
// 字段名映射实际写在下面 balanceSnapshot 的 keyMetrics 里
// 参考: eltdx 同花顺 F10 接口字段

function formatPrice(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—"
  return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatVolume(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n) || n <= 0) return "—"
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
  return n.toLocaleString("zh-CN")
}

function formatMarketCap(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n) || n <= 0) return "—"
  // stock-meta 返回的就是元
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)} 万亿`
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  return n.toLocaleString("zh-CN")
}

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

  // 右侧 3 个数据卡的状态
  const [meta, setMeta] = useState<StockMetaResponse | null>(null)
  const [valuation, setValuation] = useState<StockValuationResponse | null>(null)
  const [businessComp, setBusinessComp] = useState<StockBusinessCompositionResponse | null>(null)
  const [financeReport, setFinanceReport] = useState<Awaited<ReturnType<typeof fetchStockFinanceReport>> | null>(null)
  const [announcements, setAnnouncements] = useState<StockAnnouncementsResponse | null>(null)
  const [news, setNews] = useState<StockNewsResponse | null>(null)
  const [roadshows, setRoadshows] = useState<StockRoadshowsResponse | null>(null)
  const [companyNews, setCompanyNews] = useState<StockCompanyNewsResponse | null>(null)
  const [f10Loading, setF10Loading] = useState(false)

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

  // 拉右侧 3 个 F10 数据 (只在股票切换时拉一次, 不随 period/adjust 重拉)
  useEffect(() => {
    if (!open || !hasStock || !stockCode) return
    let active = true
    setF10Loading(true)
    setMeta(null)
    setValuation(null)
    setBusinessComp(null)
    setFinanceReport(null)
    setAnnouncements(null)
    setNews(null)
    setRoadshows(null)
    setCompanyNews(null)

    Promise.allSettled([
      fetchStockMeta({ targetType: "stock", symbol: stockCode }),
      fetchStockValuation(stockCode, { limit: 5 }),
      fetchStockBusinessComposition(stockCode, { limit: 6 }),
      fetchStockFinanceReport(stockCode, "zcfzb"),
      fetchStockAnnouncements(stockCode),
      fetchStockNews(stockCode),
      fetchStockRoadshows(stockCode),
      fetchStockCompanyNews(stockCode, { section: "gsyj" }),
    ]).then(([m, v, b, f, a, n, r, cn]) => {
      if (!active) return
      if (m.status === "fulfilled") setMeta(m.value)
      if (v.status === "fulfilled") setValuation(v.value)
      if (b.status === "fulfilled") setBusinessComp(b.value)
      if (f.status === "fulfilled") setFinanceReport(f.value)
      if (a.status === "fulfilled") setAnnouncements(a.value)
      if (n.status === "fulfilled") setNews(n.value)
      if (r.status === "fulfilled") setRoadshows(r.value)
      if (cn.status === "fulfilled") setCompanyNews(cn.value)
    }).finally(() => {
      if (active) setF10Loading(false)
    })

    return () => {
      active = false
    }
  }, [open, hasStock, stockCode])

  // 关闭时清空所有数据避免下次打开看到残留
  useEffect(() => {
    if (!open) {
      setBars([])
      setBarsLoading(false)
      setMeta(null)
      setValuation(null)
      setBusinessComp(null)
      setFinanceReport(null)
      setAnnouncements(null)
      setNews(null)
      setRoadshows(null)
      setCompanyNews(null)
    }
  }, [open])

  // 派生: 最新一根 K 线 + 上一根 (用于现价/昨收对比)
  const latestBar = useMemo(() => (bars.length > 0 ? bars[bars.length - 1] : null), [bars])
  const prevBar = useMemo(() => (bars.length > 1 ? bars[bars.length - 2] : null), [bars])

  // 派生: 主营构成 - 按产品分组 (取每组前 3 条)
  const businessByCategory = useMemo(() => {
    const items = businessComp?.items ?? []
    const groups = new Map<string, typeof items>()
    for (const it of items) {
      const key = it.category ?? "其他"
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(it)
    }
    return Array.from(groups.entries()).slice(0, 2).map(([category, list]) => ({
      category,
      items: list.slice(0, 3),
    }))
  }, [businessComp])

  // 派生: 资产负债表最新报告期 + 同比 (取最近 4 期, 求同比)
  const balanceSnapshot = useMemo(() => {
    const rows = financeReport?.rows ?? []
    if (rows.length === 0) return null
    const latest = rows[0]
    const previous = rows.length > 4 ? rows[4] : rows[rows.length - 1]
    const fieldsLatest = latest.fields
    const fieldsPrev = previous.fields

    const keyMetrics: Array<{ code: string; label: string }> = [
      { code: "T038", label: "总资产" },
      { code: "T071", label: "股东权益" },
      { code: "T077", label: "总负债" },
      { code: "T016", label: "流动资产" },
      { code: "T012", label: "存货" },
      { code: "T061", label: "股本" },
    ]

    return {
      reportDate: latest.rq,
      compareDate: previous.rq,
      items: keyMetrics
        .map((m) => {
          const cur = fieldsLatest[m.code]
          const prev = fieldsPrev[m.code]
          const curNum = typeof cur === "number" ? cur : null
          const prevNum = typeof prev === "number" ? prev : null
          let yoy: number | null = null
          if (curNum !== null && prevNum !== null && prevNum !== 0) {
            yoy = ((curNum - prevNum) / Math.abs(prevNum)) * 100
          }
          return { code: m.code, label: m.label, current: curNum, previous: prevNum, yoy }
        })
        .filter((row) => row.current !== null || row.previous !== null),
    }
  }, [financeReport])

  // 派生: 估值最新一行
  const latestValuation = valuation?.rows?.[0] ?? null

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
                      yAxisPosition="left"
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
            <Tabs defaultValue="info" className="flex h-full min-h-0 flex-col">
              <div className="flex items-center justify-between border-b border-slate-100 px-3 pt-2 text-xs font-medium text-slate-600">
                <TabsList variant="line" className="h-9 gap-0">
                  <TabsTrigger value="info" className="px-3 py-1.5 text-xs">
                    <Building2 className="mr-1 size-3.5" />
                    基本信息
                  </TabsTrigger>
                  <TabsTrigger value="finance" className="px-3 py-1.5 text-xs">
                    财务
                  </TabsTrigger>
                  <TabsTrigger value="news" className="px-3 py-1.5 text-xs">
                    <Newspaper className="mr-1 size-3.5" />
                    公告 / 新闻 / 研报
                    {news && news.count > 0 ? (
                      <span className="ml-1 rounded bg-slate-100 px-1 text-[9px] text-slate-500">
                        {news.count}
                      </span>
                    ) : null}
                  </TabsTrigger>
                </TabsList>
                {f10Loading ? (
                  <span className="pr-2 text-[10px] text-slate-400">F10 拉取中...</span>
                ) : null}
              </div>

              {/* Tab 1: 基本信息 + 技术指标快照 (小, 共用一列) */}
              <TabsContent
                value="info"
                className="m-0 flex-1 min-h-0 outline-none"
              >
                <ScrollArea className="h-full">
                  <div className="space-y-3 p-4">
                    <BasicInfoCard
                      latestBar={latestBar}
                      prevBar={prevBar}
                      meta={meta}
                      valuation={latestValuation}
                      loading={f10Loading && !latestBar && !latestValuation}
                    />
                    <section className="rounded-xl border border-slate-100 bg-white p-3">
                      <div className="mb-2 text-xs font-semibold text-slate-700">
                        技术指标快照
                      </div>
                      <p className="text-[11px] leading-relaxed text-slate-400">
                        MA / MACD / KDJ / BOLL 已在左侧 K 线图中绘制,
                        当前周期切换时实时刷新。
                      </p>
                    </section>
                  </div>
                </ScrollArea>
              </TabsContent>

              {/* Tab 2: 财务指标 */}
              <TabsContent
                value="finance"
                className="m-0 flex-1 min-h-0 outline-none"
              >
                <ScrollArea className="h-full">
                  <div className="space-y-3 p-4">
                    <FinanceSnapshotCard
                      loading={f10Loading && !balanceSnapshot && businessByCategory.length === 0}
                      balanceSnapshot={balanceSnapshot}
                      businessByCategory={businessByCategory}
                    />
                  </div>
                </ScrollArea>
              </TabsContent>

              {/* Tab 3: 公告 / 新闻 / 路演 / 研报 */}
              <TabsContent
                value="news"
                className="m-0 flex-1 min-h-0 outline-none"
              >
                <ScrollArea className="h-full">
                  <div className="space-y-3 p-4">
                    <NewsAndResearchCard
                      announcements={announcements}
                      news={news}
                      roadshows={roadshows}
                      companyNews={companyNews}
                      loading={
                        f10Loading &&
                        !announcements &&
                        !news &&
                        !roadshows &&
                        !companyNews
                      }
                    />
                  </div>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

interface BasicInfoCardProps {
  latestBar: StockKlineBar | null
  prevBar: StockKlineBar | null
  meta: StockMetaResponse | null
  valuation: StockValuationResponse["rows"][number] | null
  loading: boolean
}

function BasicInfoCard({ latestBar, prevBar, meta, valuation, loading }: BasicInfoCardProps) {
  return (
    <section className="rounded-xl border border-slate-100 bg-white p-3">
      <div className="mb-2 text-xs font-semibold text-slate-700">股票基本信息</div>
      <ul className="space-y-1.5">
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">现价 / 涨跌</span>
          <span className="tabular-nums text-slate-700">
            {latestBar ? (
              <>
                {formatPrice(latestBar.close)}
                {prevBar && prevBar.close
                  ? (() => {
                      const diff = latestBar.close - prevBar.close
                      const pct = (diff / prevBar.close) * 100
                      const sign = diff >= 0 ? "+" : ""
                      return (
                        <span
                          className={cn(
                            "ml-1.5 text-[10px]",
                            diff >= 0 ? "text-rose-600" : "text-emerald-600",
                          )}
                        >
                          {sign}
                          {diff.toFixed(2)} ({sign}
                          {pct.toFixed(2)}%)
                        </span>
                      )
                    })()
                  : null}
              </>
            ) : loading ? (
              <Skeleton className="h-3 w-16" />
            ) : (
              "—"
            )}
          </span>
        </li>
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">今开 / 昨收</span>
          <span className="tabular-nums text-slate-700">
            {latestBar ? `${formatPrice(latestBar.open)} / ${formatPrice(prevBar?.close ?? null)}` : loading ? <Skeleton className="h-3 w-20" /> : "—"}
          </span>
        </li>
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">最高 / 最低</span>
          <span className="tabular-nums text-slate-700">
            {latestBar ? `${formatPrice(latestBar.high)} / ${formatPrice(latestBar.low)}` : loading ? <Skeleton className="h-3 w-20" /> : "—"}
          </span>
        </li>
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">成交量</span>
          <span className="tabular-nums text-slate-700">
            {latestBar ? formatVolume(latestBar.volume) : loading ? <Skeleton className="h-3 w-14" /> : "—"}
          </span>
        </li>
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">总市值 / 流通市值</span>
          <span className="tabular-nums text-slate-700">
            {meta ? `${formatMarketCap(meta.totalMarketCap)} / ${formatMarketCap(meta.circMarketCap)}` : loading ? <Skeleton className="h-3 w-24" /> : "—"}
          </span>
        </li>
        <li className="flex items-center justify-between text-[11px]">
          <span className="text-slate-600">市盈率 / 市净率</span>
          <span className="tabular-nums text-slate-700">
            {valuation ? (
              <>
                PE {formatPrice(valuation.peTtm)} / PB {formatPrice(valuation.pbMrq)}
                <span className="ml-1 text-[10px] text-slate-400">@{valuation.date}</span>
              </>
            ) : loading ? (
              <Skeleton className="h-3 w-24" />
            ) : (
              "—"
            )}
          </span>
        </li>
        {meta?.industry ? (
          <li className="flex items-center justify-between text-[11px]">
            <span className="text-slate-600">所属行业</span>
            <span className="tabular-nums text-slate-700">{meta.industry}</span>
          </li>
        ) : null}
      </ul>
    </section>
  )
}

interface FinanceSnapshotCardProps {
  loading: boolean
  balanceSnapshot: {
    reportDate: string | null
    compareDate: string | null
    items: Array<{
      code: string
      label: string
      current: number | null
      previous: number | null
      yoy: number | null
    }>
  } | null
  businessByCategory: Array<{
    category: string
    items: Array<{
      category: string | null
      name: string | null
      revenue: number | null
      ratio: number | null
    }>
  }>
}

function FinanceSnapshotCard({ loading, balanceSnapshot, businessByCategory }: FinanceSnapshotCardProps) {
  const hasBalance = !!balanceSnapshot && balanceSnapshot.items.length > 0
  const hasBusiness = businessByCategory.length > 0

  return (
    <section className="rounded-xl border border-slate-100 bg-white p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="text-xs font-semibold text-slate-700">财务指标</div>
        {balanceSnapshot?.reportDate ? (
          <span className="text-[10px] text-slate-400">报告期 {balanceSnapshot.reportDate}</span>
        ) : null}
      </div>

      {hasBalance ? (
        <div className="mb-3">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
            资产负债表快照
          </div>
          <ul className="space-y-1">
            {balanceSnapshot!.items.map((row) => (
              <li
                key={row.code}
                className="flex items-center justify-between text-[11px]"
              >
                <span className="text-slate-600">{row.label}</span>
                <span className="tabular-nums text-slate-700">
                  {row.current !== null ? formatMarketCap(row.current) : "—"}
                  {row.yoy !== null ? (
                    <span
                      className={cn(
                        "ml-1.5 text-[10px]",
                        row.yoy >= 0 ? "text-rose-600" : "text-emerald-600",
                      )}
                    >
                      {row.yoy >= 0 ? "+" : ""}
                      {row.yoy.toFixed(2)}%
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasBusiness ? (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
            主营构成 (top3)
          </div>
          {businessByCategory.map((group) => (
            <div key={group.category} className="mb-2 last:mb-0">
              <div className="mb-0.5 text-[10px] text-slate-500">{group.category}</div>
              <ul className="space-y-1">
                {group.items.map((it, i) => (
                  <li
                    key={`${group.category}-${i}`}
                    className="flex items-center justify-between text-[11px]"
                  >
                    <span className="truncate text-slate-600">{it.name ?? "—"}</span>
                    <span className="tabular-nums text-slate-700">
                      {it.revenue !== null ? formatMarketCap(it.revenue) : "—"}
                      {it.ratio !== null ? (
                        <span className="ml-1 text-[10px] text-slate-400">
                          ({it.ratio.toFixed(2)}%)
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {!hasBalance && !hasBusiness ? (
        loading ? (
          <div className="space-y-1.5">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : (
          <p className="text-[11px] text-slate-400">暂无 F10 财务数据</p>
        )
      ) : null}
    </section>
  )
}

function EmptyPlaceholder() {
  return (
    <div className="flex h-full w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white text-xs text-slate-400">
      请选择股票
    </div>
  )
}

// ---------------------------------------------------------------------------
// 第 4 张卡: 公告 / 新闻 / 路演 / 研报
// ---------------------------------------------------------------------------

interface NewsAndResearchCardProps {
  announcements: StockAnnouncementsResponse | null
  news: StockNewsResponse | null
  roadshows: StockRoadshowsResponse | null
  companyNews: StockCompanyNewsResponse | null
  loading: boolean
}

/** 把 "2026-06-10 22:12:10" 截短成 "06-10 22:12"; 把 "20260609" 改成 "06-09" */
function formatShortDate(s: string | null): string {
  if (!s) return ""
  // yyyy-mm-dd hh:mm:ss -> mm-dd hh:mm
  const m1 = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2}))?/)
  if (m1) return `${m1[2]}-${m1[3]}${m1[4] ? ` ${m1[4]}` : ""}`
  // yyyyMMdd or yyyyMMddHHmmss
  const m2 = s.match(/^(\d{4})(\d{2})(\d{2})(?:\s?(\d{2}:\d{2}))?/)
  if (m2) return `${m2[2]}-${m2[3]}${m2[4] ? ` ${m2[4]}` : ""}`
  return s
}

function ratingBadgeClass(rating: string | null): string {
  if (!rating) return "bg-slate-100 text-slate-500"
  if (rating.includes("买入")) return "bg-rose-50 text-rose-700"
  if (rating.includes("增持")) return "bg-rose-50/70 text-rose-600"
  if (rating.includes("中性")) return "bg-slate-100 text-slate-600"
  if (rating.includes("减持") || rating.includes("卖出")) return "bg-emerald-50 text-emerald-700"
  return "bg-slate-100 text-slate-500"
}

function NewsAndResearchCard({
  announcements,
  news,
  roadshows,
  companyNews,
  loading,
}: NewsAndResearchCardProps) {
  const topAnnouncements = (announcements?.items ?? []).slice(0, 4).filter((it) => it.title)
  const topNews = (news?.items ?? []).slice(0, 3).filter((it) => it.title)
  const topRoadshows = (roadshows?.items ?? []).slice(0, 3).filter((it) => it.title)
  const topResearch = (companyNews?.items ?? []).slice(0, 3).filter((it) => it.title)

  const hasAny =
    topAnnouncements.length > 0 ||
    topNews.length > 0 ||
    topRoadshows.length > 0 ||
    topResearch.length > 0

  return (
    <section className="rounded-xl border border-slate-100 bg-white p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="text-xs font-semibold text-slate-700">
          近期公告 / 新闻 / 研报
        </div>
        {loading ? (
          <span className="text-[10px] text-slate-400">F10 拉取中...</span>
        ) : null}
      </div>

      {hasAny ? (
        <div className="space-y-3">
          {/* 公告 */}
          {topAnnouncements.length > 0 ? (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
                <FileText className="size-3" />
                公告
                <span className="ml-1 text-[10px] text-slate-300">
                  {announcements?.count ?? topAnnouncements.length} 条
                </span>
              </div>
              <ul className="space-y-1.5">
                {topAnnouncements.map((it, i) => (
                  <li key={`ann-${i}`} className="text-[11px]">
                    <div className="flex items-start gap-1.5">
                      <span className="shrink-0 tabular-nums text-slate-400">
                        {formatShortDate(it.issueDate)}
                      </span>
                      {it.url ? (
                        <a
                          href={it.url}
                          target="_blank"
                          rel="noreferrer"
                          className="line-clamp-1 flex-1 text-slate-700 hover:text-slate-900 hover:underline"
                          title={it.title ?? ""}
                        >
                          {it.title}
                        </a>
                      ) : (
                        <span
                          className="line-clamp-1 flex-1 text-slate-700"
                          title={it.title ?? ""}
                        >
                          {it.title}
                        </span>
                      )}
                    </div>
                    {it.typename ? (
                      <div className="ml-12 text-[9px] text-slate-400">
                        {it.typename}
                        {it.source ? ` · ${it.source}` : ""}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 新闻 */}
          {topNews.length > 0 ? (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
                <Newspaper className="size-3" />
                新闻
                <span className="ml-1 text-[10px] text-slate-300">
                  {news?.count ?? topNews.length} 条
                </span>
              </div>
              <ul className="space-y-1">
                {topNews.map((it, i) => (
                  <li
                    key={`news-${i}`}
                    className="flex items-start gap-1.5 text-[11px]"
                  >
                    <span className="shrink-0 tabular-nums text-slate-400">
                      {formatShortDate(it.issueDate)}
                    </span>
                    <span
                      className="line-clamp-1 flex-1 text-slate-700"
                      title={it.title ?? ""}
                    >
                      {it.title}
                    </span>
                    {it.source ? (
                      <span className="shrink-0 text-[9px] text-slate-300">
                        {it.source}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 路演 */}
          {topRoadshows.length > 0 ? (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
                <Presentation className="size-3" />
                路演 / 业绩说明会
                <span className="ml-1 text-[10px] text-slate-300">
                  {roadshows?.count ?? topRoadshows.length} 场
                </span>
              </div>
              <ul className="space-y-1">
                {topRoadshows.map((it, i) => (
                  <li
                    key={`rs-${i}`}
                    className="flex items-start gap-1.5 text-[11px]"
                  >
                    <span className="shrink-0 tabular-nums text-slate-400">
                      {formatShortDate(it.startDate)}
                      {it.startTime ? ` ${it.startTime}` : ""}
                    </span>
                    {it.url ? (
                      <a
                        href={it.url}
                        target="_blank"
                        rel="noreferrer"
                        className="line-clamp-1 flex-1 text-slate-700 hover:underline"
                        title={it.title ?? ""}
                      >
                        {it.title}
                      </a>
                    ) : (
                      <span
                        className="line-clamp-1 flex-1 text-slate-700"
                        title={it.title ?? ""}
                      >
                        {it.title}
                      </span>
                    )}
                    {it.roadshowType ? (
                      <span className="shrink-0 text-[9px] text-slate-300">
                        {it.roadshowType}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 研报 */}
          {topResearch.length > 0 ? (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
                <Megaphone className="size-3" />
                研报 / 评级
                <span className="ml-1 text-[10px] text-slate-300">
                  {companyNews?.count ?? topResearch.length} 篇
                </span>
              </div>
              <ul className="space-y-1.5">
                {topResearch.map((it, i) => (
                  <li key={`cn-${i}`} className="text-[11px]">
                    <div className="flex items-start gap-1.5">
                      <span className="shrink-0 tabular-nums text-slate-400">
                        {formatShortDate(it.issueDate)}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 rounded px-1 py-px text-[9px] font-medium",
                          ratingBadgeClass(it.rating),
                        )}
                      >
                        {it.rating ?? "—"}
                      </span>
                      <span
                        className="line-clamp-1 flex-1 text-slate-700"
                        title={it.title ?? ""}
                      >
                        {it.title}
                      </span>
                    </div>
                    {it.analysts ? (
                      <div className="ml-12 text-[9px] text-slate-400">
                        {it.analysts}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : loading ? (
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-2/3" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ) : (
        <p className="text-[11px] text-slate-400">暂无 F10 公告/新闻数据</p>
      )}
    </section>
  )
}
