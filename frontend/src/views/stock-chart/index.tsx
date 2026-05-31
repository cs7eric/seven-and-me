import { useEffect, useMemo, useState } from "react"

import { Eye, EyeOff, Plus, X, Trash2 } from "lucide-react"

import {
  createStockAnnotation,
  deleteStockAnnotation,
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
import { TechnicalIndicatorPanel } from "./components/technical-indicator-panel"
import { useStockChartStore } from "./lib/store"
import type { StockAnnotation, StockAuctionSnapshot, StockKlineBar, StockPeriod, StockSignalPoint } from "./lib/types"

const BS_PERSIST_PERIOD = "all"

function annotationToSignal(annotation: StockAnnotation): StockSignalPoint | null {
  if (annotation.overlay_type !== "bs_point") return null
  const point = annotation.points?.[0]
  if (!point) return null
  const text = annotation.text || ""
  const side = text.startsWith("S") ? "S" : text.startsWith("B") ? "B" : null
  if (!side) return null

  return {
    id: annotation.id,
    timestamp: point.timestamp,
    price: point.value,
    side,
    label: side,
    reason: text.slice(2) || "manual",
    source: "manual",
    period: BS_PERSIST_PERIOD,
  }
}

function isSameTradeDate(left: number, right: number) {
  const leftDate = new Date(left)
  const rightDate = new Date(right)
  return leftDate.getFullYear() === rightDate.getFullYear() && leftDate.getMonth() === rightDate.getMonth() && leftDate.getDate() === rightDate.getDate()
}

function mapSignalToVisibleBar(signal: StockSignalPoint, bars: StockKlineBar[], period: StockPeriod): StockSignalPoint | null {
  if (!bars.length) return null
  const exactBar = bars.find((bar) => bar.timestamp === signal.timestamp)
  if (exactBar) return signal

  if (period === "1d" || period === "1w") {
    const sameDateBar = bars.find((bar) => isSameTradeDate(bar.timestamp, signal.timestamp))
    return sameDateBar ? { ...signal, timestamp: sameDateBar.timestamp } : null
  }

  const sortedBars = [...bars].sort((a, b) => a.timestamp - b.timestamp)
  const matchedBar = sortedBars.find((bar, index) => {
    const next = sortedBars[index + 1]
    return signal.timestamp >= bar.timestamp && (!next || signal.timestamp < next.timestamp)
  })

  return matchedBar ? { ...signal, timestamp: matchedBar.timestamp } : null
}

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
  const [showBsPoints, setShowBsPoints] = useState(true)
  const [manualSignalMode, setManualSignalMode] = useState<"B" | "S" | null>(null)
  const [manualSignals, setManualSignals] = useState<StockSignalPoint[]>([])
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
        const [workspace, klineResult, annotationResult, sharedSignalAnnotations, auctionResult] = await Promise.all([
          fetchStockWorkspace(targetType, symbol, name),
          fetchStockKlines({ targetType, symbol, name, period, adjust }),
          listStockAnnotations(targetType, symbol, period),
          listStockAnnotations(targetType, symbol, BS_PERSIST_PERIOD),
          fetchStockAuction(symbol),
        ])
        if (!active) return
        setBars(klineResult.items)
        setAnnotations(annotationResult)
        setManualSignals(sharedSignalAnnotations.map(annotationToSignal).filter((item): item is StockSignalPoint => Boolean(item)))
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
  const bsSignals = useMemo(() => {
    if (!showBsPoints) return []
    return manualSignals
      .map((signal) => mapSignalToVisibleBar(signal, bars, period))
      .filter((signal): signal is StockSignalPoint => Boolean(signal))
  }, [bars, manualSignals, period, showBsPoints])


  const handleCreateManualSignal = async (signal: StockSignalPoint) => {
    const annotation = await createStockAnnotation({
      target_type: targetType,
      symbol,
      period: BS_PERSIST_PERIOD,
      overlay_type: "bs_point",
      points: [{ timestamp: signal.timestamp, value: signal.price }],
      text: `${signal.side}:${signal.reason ?? "manual"}`,
      styles: {
        side: signal.side,
        source: "manual",
      },
    })

    const persistedSignal = annotationToSignal(annotation)
    if (persistedSignal) {
      setManualSignals((current) => {
        const next = current.filter((item) => item.id !== persistedSignal.id)
        next.push(persistedSignal)
        return next
      })
    }
    setManualSignalMode(null)
  }

  const handleClearManualMode = () => {
    setManualSignalMode(null)
  }

  const handleClearManualSignals = async () => {
    const targets = [...manualSignals]
    await Promise.all(
      targets.map((signal) => deleteStockAnnotation(targetType, symbol, BS_PERSIST_PERIOD, signal.id))
    )
    setManualSignals([])
  }

  const handleDeleteManualSignal = async (signalId: string) => {
    await deleteStockAnnotation(targetType, symbol, BS_PERSIST_PERIOD, signalId)
    setManualSignals((current) => current.filter((signal) => signal.id !== signalId))
  }

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
            <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200/80 bg-slate-50/80 p-1">
              <Button
                size="xs"
                variant="ghost"
                className={manualSignalMode === "B" ? "bg-red-600 text-white hover:bg-red-600/90 hover:text-white" : "text-red-600 hover:bg-red-50 hover:text-red-700"}
                onClick={() => setManualSignalMode((current) => (current === "B" ? null : "B"))}
              >
                <Plus className="size-3" />添加 B 点
              </Button>
              <Button
                size="xs"
                variant="ghost"
                className={manualSignalMode === "S" ? "bg-green-600 text-white hover:bg-green-600/90 hover:text-white" : "text-green-600 hover:bg-green-50 hover:text-green-700"}
                onClick={() => setManualSignalMode((current) => (current === "S" ? null : "S"))}
              >
                <Plus className="size-3" />添加 S 点
              </Button>
              <Button size="xs" variant="ghost" className="text-slate-500 hover:bg-slate-100 hover:text-slate-700" onClick={handleClearManualMode} disabled={!manualSignalMode}>
                <X className="size-3" />退出落点
              </Button>
              <Button size="xs" variant="ghost" className="text-slate-500 hover:bg-slate-100 hover:text-slate-700" onClick={() => void handleClearManualSignals()} disabled={manualSignals.length === 0}>
                清空手动点
              </Button>
              <Button size="xs" variant="ghost" className="text-slate-500 hover:bg-slate-100 hover:text-slate-700" onClick={() => setShowBsPoints((current) => !current)}>
                {showBsPoints ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                {showBsPoints ? "隐藏 BS 点" : "显示 BS 点"}
              </Button>
              <Button size="xs" variant="ghost" className="text-slate-400 hover:bg-slate-100 hover:text-slate-600" onClick={() => void handleCreateSampleAnnotation()}>
                添加示例标记
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {manualSignalMode ? (
              <div className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500">
                当前处于 {manualSignalMode} 点添加模式，点击 K 线区域任意一根蜡烛即可落点。
              </div>
            ) : null}
            <ChartPanel bars={bars} annotations={annotations} bsSignals={bsSignals} manualSignalMode={manualSignalMode} onManualSignalCreate={handleCreateManualSignal} symbol={symbol} period={period} indicators={indicators} maLines={maLines} />
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-800">手动 BS 点</div>
                  <div className="text-xs text-slate-500">支持逐条删除，方便整理自己的买卖计划。</div>
                </div>
                <div className="text-xs text-slate-500">共 {manualSignals.length} 个</div>
              </div>
              {manualSignals.length ? (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {manualSignals
                    .slice()
                    .sort((a, b) => b.timestamp - a.timestamp)
                    .map((signal) => (
                      <div key={signal.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                            <span className={signal.side === "B" ? "rounded bg-red-600 px-1.5 py-0.5 text-[10px] text-white" : "rounded bg-green-600 px-1.5 py-0.5 text-[10px] text-white"}>{signal.side}</span>
                            <span>{new Date(signal.timestamp).toLocaleString("zh-CN", { hour12: false })}</span>
                          </div>
                          <div className="truncate text-xs text-slate-500">价格 {signal.price.toFixed(2)} · {signal.reason === "manual" ? "手动标记" : signal.reason}</div>
                        </div>
                        <Button size="icon-xs" variant="ghost" className="text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => void handleDeleteManualSignal(signal.id)}>
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                    ))}
                </div>
              ) : (
                <div className="text-xs text-slate-500">还没有手动 BS 点，点击上方“添加 B 点 / 添加 S 点”后在 K 线上落点即可。</div>
              )}
            </div>
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
                <SelectItem value="ma-support">技术指标</SelectItem>
                <SelectItem value="fund-flow">资金</SelectItem>
              </SelectContent>
            </Select>
            <TabsList className="hidden md:inline-flex">
              <TabsTrigger value="auction">集合竞价</TabsTrigger>
              <TabsTrigger value="ma-support">技术指标</TabsTrigger>
              <TabsTrigger value="fund-flow">资金</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="auction" className="mt-0">
            {showAuctionPanel ? <AuctionPanel auction={auction} /> : null}
          </TabsContent>

          <TabsContent value="ma-support" className="mt-0">
            <TechnicalIndicatorPanel bars={bars} />
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
