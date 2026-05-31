import { useEffect, useMemo, useState } from "react"

import {
  createStockAnnotation,
  fetchStockAuction,
  fetchStockKlines,
  fetchStockWorkspace,
  listStockAnnotations,
  saveStockWorkspace,
} from "@/lib/api"
import { WorkspaceShell } from "@/components/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ChartPanel } from "./components/chart-panel"
import { SymbolSearch } from "./components/symbol-search"
import { IndicatorToolbar } from "./components/indicator-toolbar"
import { AuctionPanel } from "./components/auction-panel"
import { useStockChartStore } from "./lib/store"
import type { StockAnnotation, StockAuctionSnapshot, StockKlineBar, StockPeriod } from "./lib/types"

export default function StockChartPage() {
  const {
    targetType,
    symbol,
    name,
    period,
    adjust,
    indicators,
    maLines,
    showAuctionPanel,
    setTarget,
    setPeriod,
    setAdjust,
    toggleIndicator,
    toggleMALine,
  } = useStockChartStore()
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [annotations, setAnnotations] = useState<StockAnnotation[]>([])
  const [auction, setAuction] = useState<StockAuctionSnapshot | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    const minutePeriods = new Set<StockPeriod>(["5m", "15m", "30m", "60m"])
    if (minutePeriods.has(period) && adjust !== "none") {
      setAdjust("none")
    }
  }, [adjust, period, setAdjust])

  useEffect(() => {
    let active = true

    void (async () => {
      try {
        if (!active) return
        setError("")
        const [workspace, klineResult, annotationResult, auctionResult] = await Promise.all([
          fetchStockWorkspace(targetType, symbol, name),
          fetchStockKlines({ targetType, symbol, name, period, adjust }),
          listStockAnnotations(targetType, symbol, period),
          fetchStockAuction(symbol),
        ])
        if (!active) return
        setBars(klineResult.items)
        setAnnotations(annotationResult)
        setAuction(auctionResult)
        await saveStockWorkspace({
          symbol,
          name,
          target_type: targetType,
          period,
          adjust,
          indicators,
          drawing_tool: workspace.drawing_tool,
          show_auction_panel: workspace.show_auction_panel,
        })
      } catch (err) {
        if (!active) return
        setBars([])
        setAnnotations([])
        setAuction(null)
        setError(err instanceof Error ? err.message : "加载 stock chart 失败")
      }
    })()

    return () => {
      active = false
    }
  }, [adjust, indicators, name, period, symbol, targetType])

  const targetLabel = useMemo(() => `${name} · ${symbol}`, [name, symbol])

  const handleCreateSampleAnnotation = async () => {
    if (!bars.length) return
    const first = bars[Math.max(0, bars.length - 20)]
    const second = bars[bars.length - 1]
    const annotation = await createStockAnnotation({
      target_type: targetType,
      symbol,
      period,
      overlay_type: "segment",
      points: [
        { timestamp: first.timestamp, value: first.close },
        { timestamp: second.timestamp, value: second.close },
      ],
      text: "趋势标记",
    })
    setAnnotations((prev) => [annotation, ...prev])
  }

  return (
    <WorkspaceShell sectionLabel="Stock Chart" pageTitle="Chart Workspace">
      <div className="container space-y-5 pb-24">
        <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
          <CardHeader>
            <CardTitle className="text-2xl">Stock Chart Workspace</CardTitle>
            <CardDescription>查看股票 / 指数 / 板块 K 线，叠加指标并持久化标记到 reference/stock。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SymbolSearch onSelect={(item) => setTarget({ targetType: item.target_type, symbol: item.symbol, name: item.name })} />
            <IndicatorToolbar
              period={period}
              adjust={adjust}
              activeIndicators={indicators}
              maLines={maLines}
              onPeriodChange={setPeriod}
              onAdjustChange={setAdjust}
              onToggleIndicator={toggleIndicator}
              onToggleMALine={toggleMALine}
            />
          </CardContent>
        </Card>

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>加载失败</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
          <CardHeader className="flex flex-row items-center justify-between gap-4">
            <div>
              <CardTitle>{targetLabel}</CardTitle>
              <CardDescription>{targetType} · {period} · {adjust}</CardDescription>
            </div>
            <Button onClick={() => void handleCreateSampleAnnotation()}>添加示例标记</Button>
          </CardHeader>
          <CardContent>
            <ChartPanel bars={bars} annotations={annotations} symbol={symbol} period={period} indicators={indicators} maLines={maLines} />
          </CardContent>
        </Card>

        <Tabs defaultValue="auction" className="w-full flex-col justify-start gap-4">
          <div className="flex items-center justify-between gap-3">
            <Select defaultValue="auction">
              <SelectTrigger className="flex w-fit md:hidden" size="sm">
                <SelectValue placeholder="选择模块" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auction">集合竞价</SelectItem>
                <SelectItem value="ma-support">均线支持</SelectItem>
                <SelectItem value="fund-flow">资金</SelectItem>
              </SelectContent>
            </Select>
            <TabsList className="hidden md:inline-flex">
              <TabsTrigger value="auction">集合竞价</TabsTrigger>
              <TabsTrigger value="ma-support">均线支持</TabsTrigger>
              <TabsTrigger value="fund-flow">资金</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="auction" className="mt-0">
            {showAuctionPanel ? <AuctionPanel auction={auction} /> : null}
          </TabsContent>

          <TabsContent value="ma-support" className="mt-0">
            <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
              <CardHeader>
                <CardTitle className="text-base">均线支持</CardTitle>
                <CardDescription>先保留 mock 结构，后续接入真实均线支撑/压力分析。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-6 text-sm text-slate-500">
                  均线支持模块待接入真实数据，当前为占位内容。
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="fund-flow" className="mt-0">
            <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
              <CardHeader>
                <CardTitle className="text-base">资金</CardTitle>
                <CardDescription>先保留 mock 结构，后续接入主力资金 / 分时资金等指标。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-6 text-sm text-slate-500">
                  资金模块待接入真实数据，当前为占位内容。
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </WorkspaceShell>
  )
}
