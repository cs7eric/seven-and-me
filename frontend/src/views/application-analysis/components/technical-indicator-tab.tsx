import { useEffect, useState } from "react"

import {
  fetchMarketBreadth,
  fetchMarketBreadthSeries,
  fetchStockKlines,
  fetchStockMeta,
} from "@/lib/api"
import { TechnicalIndicatorPanel } from "../../stock-chart/components/technical-indicator-panel"
import type {
  MarketBreadth,
  MarketBreadthSeries,
  StockMeta,
} from "../../stock-chart/lib/indicator-utils"
import type {
  StockAdjust,
  StockKlineBar,
  StockPeriod,
  StockTargetType,
} from "../../stock-chart/lib/types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { notification } from "@/components/ui/notification"

export interface TechnicalIndicatorTabProps {
  targetType: StockTargetType
  symbol: string
  name: string
  period?: StockPeriod
  adjust?: StockAdjust
}

const DEFAULT_PERIOD: StockPeriod = "1d"
const DEFAULT_ADJUST: StockAdjust = "qfq"

const INDEX_KLINE_SYMBOLS: Record<string, string> = {
  "上证指数": "000001",
  "上证50": "000016",
  "沪深300": "000300",
  "中证500": "000905",
  "中证1000": "000852",
  "中证2000": "932000",
  "创业板指": "399006",
  "科创50": "000688",
}

function loadContextIndexBars(params: {
  period: StockPeriod
  adjust: StockAdjust
  sector?: { symbol: string; label: string } | null
}): Promise<PromiseSettledResult<{ label: string; items: StockKlineBar[] }>[]> {
  const entries: Array<{ label: string; symbol: string; targetType: StockTargetType }> = Object.entries(INDEX_KLINE_SYMBOLS)
    .map(([label, symbol]) => ({ label, symbol, targetType: "index" }))

  if (params.sector?.symbol) {
    entries.push({
      label: params.sector.label,
      symbol: params.sector.symbol,
      targetType: /^\d+$/.test(params.sector.symbol) ? "index" : "sector",
    })
  }

  return Promise.allSettled(
    entries.map(async ({ label, symbol, targetType }) => {
      const res = await fetchStockKlines({
        targetType,
        symbol,
        name: label,
        period: params.period,
        adjust: params.adjust,
      })
      return { label, items: res.items }
    }),
  )
}

function settledBarsToMap(results: PromiseSettledResult<{ label: string; items: StockKlineBar[] }>[]) {
  const map: Record<string, StockKlineBar[]> = {}
  for (const r of results) {
    if (r.status === "fulfilled") {
      map[r.value.label] = r.value.items
    }
  }
  return map
}

export function TechnicalIndicatorTab({
  targetType,
  symbol,
  name,
  period = DEFAULT_PERIOD,
  adjust = DEFAULT_ADJUST,
}: TechnicalIndicatorTabProps) {
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [indexBarsMap, setIndexBarsMap] = useState<Record<string, StockKlineBar[]>>({})
  const [stockMeta, setStockMeta] = useState<StockMeta | null>(null)
  const [breadth, setBreadth] = useState<MarketBreadth | null>(null)
  const [breadthSeries, setBreadthSeries] = useState<MarketBreadthSeries>([])
  const [error, setError] = useState<string>("")

  useEffect(() => {
    let active = true

    void (async () => {
      try {
        if (!active) return
        setError("")
        const klineResult = await fetchStockKlines({ targetType, symbol, name, period, adjust })
        if (!active) return
        setBars(klineResult.items)

        fetchStockMeta({ targetType, symbol }).then((meta) => {
          if (!active) return

          const sectorSymbol = meta.sectorIndexSymbol || meta.industry || null
          const sectorLabel = meta.sectorIndexName || sectorSymbol
          setStockMeta({
            marketCap: meta.circMarketCap || null,
            capStyle: meta.capStyle,
            sectorIndexSymbol: sectorLabel,
          })

          void loadContextIndexBars({
            period,
            adjust,
            sector: sectorSymbol ? { symbol: sectorSymbol, label: sectorLabel || sectorSymbol } : null,
          }).then((results) => {
            if (!active) return
            setIndexBarsMap(settledBarsToMap(results))
          })
        }).catch(() => {
          if (!active) return
          setStockMeta(null)

          void loadContextIndexBars({ period, adjust }).then((results) => {
            if (!active) return
            setIndexBarsMap(settledBarsToMap(results))
          })
        })

        fetchMarketBreadth().then((b) => {
          if (!active) return
          setBreadth(b)
        }).catch(() => {
          if (active) setBreadth(null)
        })

        fetchMarketBreadthSeries().then((series) => {
          if (!active) return
          setBreadthSeries(series)
        }).catch(() => {
          if (active) setBreadthSeries([])
        })
      } catch (err) {
        if (!active) return
        const msg = err instanceof Error ? err.message : "加载技术指标失败"
        setBars([])
        setIndexBarsMap({})
        setStockMeta(null)
        setBreadth(null)
        setBreadthSeries([])
        setError(msg)
        notification.danger({ title: "加载技术指标失败", description: msg })
      }
    })()

    return () => {
      active = false
    }
  }, [targetType, symbol, name, period, adjust])

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>加载技术指标失败</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  return (
    <TechnicalIndicatorPanel
      bars={bars}
      indexBarsMap={indexBarsMap}
      stockMeta={stockMeta}
      breadth={breadth}
      breadthSeries={breadthSeries}
    />
  )
}
