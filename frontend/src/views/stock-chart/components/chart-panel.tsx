import { useEffect, useMemo, useRef, useState } from "react"
import { dispose, init, registerOverlay, type Chart, type KLineData } from "klinecharts"

import type { StockAnnotation, StockKlineBar, StockPeriod, StockSignalPoint } from "../lib/types"

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
const BS_OVERLAY_NAME = "stock-bs-marker"
const STOCK_UP_COLOR = "#dc2626"
const STOCK_DOWN_COLOR = "#16a34a"
const STOCK_NEUTRAL_COLOR = "#94a3b8"

let bsOverlayRegistered = false

function ensureBsOverlayRegistered() {
  if (bsOverlayRegistered) return

  registerOverlay({
    name: BS_OVERLAY_NAME,
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }) => {
      const coordinate = coordinates[0]
      if (!coordinate) return []

      const extendData = (overlay.extendData ?? {}) as { side?: "B" | "S" }
      const side = extendData.side === "S" ? "S" : "B"
      const offsetY = side === "B" ? 26 : -26
      const fillColor = side === "B" ? STOCK_UP_COLOR : STOCK_DOWN_COLOR
      const badgeWidth = 24
      const badgeHeight = 16
      const radius = badgeHeight / 2
      const badgeY = coordinate.y + offsetY - badgeHeight / 2
      const pointerTop = side === "B" ? badgeY - 2 : badgeY + badgeHeight + 2
      const pointerBottom = side === "B" ? coordinate.y + 10 : coordinate.y - 10

      return [
        {
          type: "circle",
          attrs: {
            x: coordinate.x - badgeWidth / 2 + radius,
            y: coordinate.y + offsetY,
            r: radius,
          },
          styles: {
            style: "fill",
            color: fillColor,
          },
        },
        {
          type: "rect",
          attrs: {
            x: coordinate.x - badgeWidth / 2 + radius,
            y: badgeY,
            width: badgeWidth - badgeHeight,
            height: badgeHeight,
          },
          styles: {
            style: "fill",
            color: fillColor,
          },
        },
        {
          type: "circle",
          attrs: {
            x: coordinate.x + badgeWidth / 2 - radius,
            y: coordinate.y + offsetY,
            r: radius,
          },
          styles: {
            style: "fill",
            color: fillColor,
          },
        },
        {
          type: "line",
          attrs: {
            coordinates: [
              { x: coordinate.x, y: pointerTop },
              { x: coordinate.x, y: pointerBottom },
            ],
          },
          styles: {
            color: fillColor,
            size: 1,
          },
        },
        {
          type: "text",
          attrs: {
            x: coordinate.x,
            y: coordinate.y + offsetY,
            text: side,
            align: "center",
            baseline: "middle",
          },
          styles: {
            color: "#ffffff",
            size: 11,
            weight: "bold",
          },
        },
      ]
    },
  })

  bsOverlayRegistered = true
}

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
  bsSignals,
  manualSignalMode,
  onManualSignalCreate,
  symbol,
  period,
  indicators,
  maLines,
}: {
  bars: StockKlineBar[]
  annotations: StockAnnotation[]
  bsSignals: StockSignalPoint[]
  manualSignalMode: "B" | "S" | null
  onManualSignalCreate: (signal: StockSignalPoint) => void
  symbol: string
  period: StockPeriod
  indicators: string[]
  maLines: number[]
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<Chart | null>(null)
  const [hoveredSignal, setHoveredSignal] = useState<(StockSignalPoint & { x: number; y: number }) | null>(null)
  const hasTurnover = useMemo(() => bars.some((bar) => typeof bar.turnover === "number" && bar.turnover > 0), [bars])

  const getSignalPixelPoint = (signal: StockSignalPoint) => {
    const chart = chartRef.current
    if (!chart) return null

    return (chart as unknown as {
      convertToPixel: (point: { timestamp: number; value: number }, options?: { paneId?: string }) => { x?: number; y?: number }
    }).convertToPixel(
      {
        timestamp: signal.timestamp,
        value: signal.price,
      },
      {
        paneId: MAIN_PANE_ID,
      }
    )
  }

  const handleChartClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!manualSignalMode) return

    const chart = chartRef.current
    const container = containerRef.current
    if (!chart || !container) return

    const bounds = container.getBoundingClientRect()
    const coordinate = (chart as unknown as {
      convertFromPixel: (coordinate: { x: number; y: number }, options?: { paneId?: string }) => {
        dataIndex?: number
        timestamp?: number
        value?: number
      }
    }).convertFromPixel(
      {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      },
      {
        paneId: MAIN_PANE_ID,
      }
    )

    const dataIndex = coordinate.dataIndex ?? -1
    if (dataIndex < 0 || dataIndex >= bars.length) return

    const bar = bars[dataIndex]
    if (!bar) return

    const side = manualSignalMode
    const price = side === "B" ? bar.low : bar.high

    onManualSignalCreate({
      id: `bs-manual-${side}-${bar.timestamp}`,
      timestamp: bar.timestamp,
      price,
      side,
      label: side,
      reason: "manual",
      score: 1,
    })
  }

  const handleChartMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current
    if (!container || bsSignals.length === 0) {
      setHoveredSignal(null)
      return
    }

    const bounds = container.getBoundingClientRect()
    const pointerX = event.clientX - bounds.left
    const pointerY = event.clientY - bounds.top
    const nearestSignal = bsSignals
      .map((signal) => {
        const point = getSignalPixelPoint(signal)
        if (!point || typeof point.x !== "number" || typeof point.y !== "number") return null
        const dx = point.x - pointerX
        const dy = point.y - pointerY
        return {
          ...signal,
          x: point.x,
          y: point.y,
          distance: Math.sqrt(dx * dx + dy * dy),
        }
      })
      .filter((signal): signal is StockSignalPoint & { x: number; y: number; distance: number } => Boolean(signal))
      .sort((a, b) => a.distance - b.distance)[0]

    if (!nearestSignal || nearestSignal.distance > 24) {
      setHoveredSignal(null)
      return
    }

    setHoveredSignal(nearestSignal)
  }

  const handleChartMouseLeave = () => {
    setHoveredSignal(null)
  }


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

    ensureBsOverlayRegistered()

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

    chart.removeOverlay({ groupId: "annotations" })
    chart.removeOverlay({ groupId: "bs-signals" })

    annotations.forEach((annotation) => {
      chart.createOverlay({
        id: annotation.id,
        groupId: "annotations",
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

    if (bsSignals.length > 0) {
      chart.createOverlay(
        bsSignals.map((signal) => ({
          id: signal.id,
          groupId: "bs-signals",
          name: BS_OVERLAY_NAME,
          paneId: MAIN_PANE_ID,
          lock: true,
          visible: true,
          zLevel: 30,
          points: [
            {
              timestamp: signal.timestamp,
              value: signal.price,
            },
          ],
          extendData: {
            side: signal.side,
            label: signal.label,
            reason: signal.reason,
            score: signal.score,
          },
        }))
      )
    }
  }, [annotations, bsSignals])

  return (
    <div className="relative">
      <div
        ref={containerRef}
        onClick={handleChartClick}
        onMouseMove={handleChartMouseMove}
        onMouseLeave={handleChartMouseLeave}
        className="h-[720px] w-full rounded-2xl bg-background"
      />
      {hoveredSignal ? (
        <div
          className="pointer-events-none absolute z-20 min-w-[140px] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-700 shadow-lg"
          style={{
            left: Math.min(hoveredSignal.x + 14, 820),
            top: hoveredSignal.side === "B" ? hoveredSignal.y - 66 : hoveredSignal.y + 8,
          }}
        >
          <div className="mb-1 flex items-center gap-2 font-medium text-slate-900">
            <span className={hoveredSignal.side === "B" ? "rounded bg-red-600 px-1.5 py-0.5 text-[10px] text-white" : "rounded bg-green-600 px-1.5 py-0.5 text-[10px] text-white"}>{hoveredSignal.side}</span>
            <span>{hoveredSignal.reason === "manual" ? "手动 BS 点" : hoveredSignal.reason}</span>
          </div>
          <div>价格：{hoveredSignal.price.toFixed(2)}</div>
          <div>时间：{new Date(hoveredSignal.timestamp).toLocaleString("zh-CN", { hour12: false })}</div>
        </div>
      ) : null}
    </div>
  )
}
