import { useEffect, useMemo, useRef } from "react"
import { dispose, init, type Chart, type KLineData } from "klinecharts"

import type { StockAnnotation, StockKlineBar, StockPeriod } from "../lib/types"

const CHART_PERIOD_MAP: Record<StockPeriod, { type: "minute" | "day" | "week"; span: number }> = {
  "1m": { type: "minute", span: 1 },
  "5m": { type: "minute", span: 5 },
  "15m": { type: "minute", span: 15 },
  "30m": { type: "minute", span: 30 },
  "60m": { type: "minute", span: 60 },
  "120m": { type: "minute", span: 120 },
  "1d": { type: "day", span: 1 },
  "1w": { type: "week", span: 1 },
}

const MAIN_PANE_ID = "candle_pane"
const AMOUNT_PANE_ID = "amount_pane"
const MACD_PANE_ID = "macd_pane"
const STOCK_UP_COLOR = "#dc2626"
const STOCK_DOWN_COLOR = "#16a34a"
const STOCK_NEUTRAL_COLOR = "#94a3b8"

function buildMainPaneContent(indicators: string[], maLines: number[]) {
  const content: Array<string | { name: string; shortName: string; calcParams?: number[] }> = []

  if (maLines.length > 0) {
    content.push({
      name: "MA",
      shortName: "MA",
      calcParams: maLines,
    })
  }

  if (indicators.includes("EXPMA")) {
    content.push({
      name: "EMA",
      shortName: "EXPMA",
      calcParams: [12, 50],
    })
  }

  if (indicators.includes("BOLL")) {
    content.push({
      name: "BOLL",
      shortName: "BOLL",
    })
  }

  return content
}

function syncIndicators(chart: Chart, indicators: string[], maLines: number[], hasTurnover: boolean) {
  chart.removeIndicator({})

  buildMainPaneContent(indicators, maLines).forEach((indicator) => {
    chart.createIndicator(indicator, {
      isStack: true,
      pane: { id: MAIN_PANE_ID },
    })
  })

  if (hasTurnover && indicators.includes("AMOUNT")) {
    chart.createIndicator("AMOUNT", {
      isStack: false,
      pane: { id: AMOUNT_PANE_ID, height: 128, minHeight: 84, dragEnabled: true, order: 1 },
    })
  }

  if (indicators.includes("MACD")) {
    chart.createIndicator("MACD", {
      isStack: false,
      pane: { id: MACD_PANE_ID, height: 148, minHeight: 104, dragEnabled: true, order: 2 },
    })
  }
}

export function ChartPanel({
  bars,
  annotations,
  symbol,
  period,
  indicators,
  maLines,
}: {
  bars: StockKlineBar[]
  annotations: StockAnnotation[]
  symbol: string
  period: StockPeriod
  indicators: string[]
  maLines: number[]
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<Chart | null>(null)
  const hasTurnover = useMemo(() => bars.some((bar) => typeof bar.turnover === "number" && bar.turnover > 0), [bars])

  const chartData = useMemo<KLineData[]>(
    () =>
      bars.map((bar) => ({
        timestamp: bar.timestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume,
        turnover: bar.turnover,
      })),
    [bars]
  )

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return

    const chart = init(containerRef.current, {
      styles: {
        grid: {
          show: true,
          horizontal: { show: true },
          vertical: { show: true },
        },
        candle: {
          bar: {
            upColor: STOCK_UP_COLOR,
            downColor: STOCK_DOWN_COLOR,
            noChangeColor: STOCK_NEUTRAL_COLOR,
            upBorderColor: STOCK_UP_COLOR,
            downBorderColor: STOCK_DOWN_COLOR,
            noChangeBorderColor: STOCK_NEUTRAL_COLOR,
            upWickColor: STOCK_UP_COLOR,
            downWickColor: STOCK_DOWN_COLOR,
            noChangeWickColor: STOCK_NEUTRAL_COLOR,
          },
          priceMark: {
            last: {
              upColor: STOCK_UP_COLOR,
              downColor: STOCK_DOWN_COLOR,
              noChangeColor: STOCK_NEUTRAL_COLOR,
            },
          },
        },
        crosshair: {
          horizontal: { line: { size: 1 } },
          vertical: { line: { size: 1 } },
        },
      },
      layout: {
        panes: [
          { type: "candle", options: { id: MAIN_PANE_ID } },
          { type: "xAxis" },
        ],
      },
    })

    if (!chart) return
    chartRef.current = chart
    chart.setBarSpace(10)
    chart.setLeftMinVisibleBarCount(24)
    chart.setRightMinVisibleBarCount(8)
    chart.setOffsetRightDistance(12)
    chart.setMaxOffsetLeftDistance(80)
    chart.setMaxOffsetRightDistance(80)

    const resizeObserver = new ResizeObserver(() => {
      chart.resize()
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      dispose(chart)
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    chart.setDataLoader({
      getBars: ({ callback }) => {
        callback(chartData, false)
      },
    })
    chart.resetData()
    chart.setSymbol({ ticker: symbol, pricePrecision: 2, volumePrecision: 0 })
    chart.setPeriod(CHART_PERIOD_MAP[period])
    chart.scrollToRealTime()
  }, [chartData, period, symbol])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    syncIndicators(chart, indicators, maLines, hasTurnover)
  }, [hasTurnover, indicators, maLines])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    chart.removeOverlay({})

    annotations.forEach((annotation) => {
      chart.createOverlay({
        id: annotation.id,
        name: annotation.overlay_type,
        points: annotation.points.map((point) => ({
          timestamp: point.timestamp,
          value: point.value,
        })),
        styles: annotation.styles,
        mode: "strong_magnet",
        modeSensitivity: 16,
        lock: false,
        zLevel: 20,
        extendData: { text: annotation.text },
      })
    })
  }, [annotations])

  return <div ref={containerRef} className="h-[720px] w-full rounded-2xl bg-background" />
}
