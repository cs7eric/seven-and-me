import { useEffect, useMemo, useRef, useState } from "react"
import { dispose, init, registerOverlay, type Chart, type KLineData } from "klinecharts"

import type { StockAnnotation, StockKlineBar, StockOverlayAnnotation, StockPeriod, StockSignalPoint } from "../lib/types"

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
const AI_OVERLAY_NAMES = ["price_zone", "trend_line", "pattern_polyline", "event_marker", "gap_zone", "ma_marker", "sentiment_marker"]
const AI_SOFT_FILL_NAME = "ai_soft_fill"
const AI_CANDLE_HIGHLIGHT_NAME = "ai_candle_highlight"
const STOCK_UP_COLOR = "#dc2626"
const STOCK_DOWN_COLOR = "#16a34a"
const STOCK_NEUTRAL_COLOR = "#94a3b8"

const RANGE_PRICE_FILL_COLOR = "#ef4444"
const RANGE_PRICE_FILL_ALPHA = 0.055
const RANGE_TIME_FILL_COLOR = "#2563eb"
const RANGE_TIME_FILL_ALPHA = 0.045
const RANGE_PRICE_LINE_ALPHA = 0.42
const RANGE_TIME_LINE_ALPHA = 0.38
const SELECTED_CANDLE_BORDER_COLOR = "#0f172a"
const SELECTED_CANDLE_FILL_ALPHA = 0.055

type AiOverlayKind = "point" | "range" | "line"

interface DerivedAiAnnotation {
  id: string
  overlay: StockOverlayAnnotation
  kind: AiOverlayKind
  shortText: string
  fullText: string
  typeLabel: string
  accentColor: string
  startTimestamp: number
  endTimestamp: number
  minValue: number
  maxValue: number
  anchorTimestamp: number
  anchorValue: number
  anchorHighValue: number
  anchorLowValue: number
  pixelTimestamps: number[]
}

interface HoveredAiAnnotation {
  annotation: DerivedAiAnnotation
  x: number
  y: number
  left: number
  top: number
  width: number
  height: number
  rangeStartIndex: number
  rangeEndIndex: number
}

interface AiAnnotationLabelPosition {
  id: string
  kind: "point" | "range" | "line"
  anchorX: number
  anchorY: number
  labelX: number
  labelY: number
  accentColor: string
  shortText: string
  fullText: string
  typeLabel: string
  startTimestamp: number
  endTimestamp: number
  minValue: number
  maxValue: number
  anchorTimestamp: number
  anchorValue: number
}

export interface ChartPanelSelectedBarItem {
  kind: "bar"
  key: string
  index: number
  bar: StockKlineBar
}

export interface ChartPanelSelectedAnnotationItem {
  kind: "annotation"
  key: string
  annotationId: string
  annotation: StockOverlayAnnotation
  overlayType: string
  typeLabel: string
  shortText: string
  fullText: string
  startTimestamp: number
  endTimestamp: number
  minValue: number
  maxValue: number
}

export type ChartPanelSelectionItem = ChartPanelSelectedBarItem | ChartPanelSelectedAnnotationItem

let bsOverlayRegistered = false
let aiOverlaysRegistered = false
let aiSoftFillRegistered = false
let aiCandleHighlightRegistered = false

function ensureAiSoftFillRegistered() {
  if (aiSoftFillRegistered) return
  registerOverlay({
    name: AI_SOFT_FILL_NAME,
    totalStep: 2,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }) => {
      const first = coordinates[0]
      const second = coordinates[1]
      if (!first || !second) return []
      const x = Math.min(first.x, second.x)
      const y = Math.min(first.y, second.y)
      const width = Math.max(Math.abs(second.x - first.x), 80)
      const height = Math.max(Math.abs(second.y - first.y), 8)
      const styles = (overlay.styles ?? {}) as Record<string, unknown>
      const color = safeText(styles.color, "#bfdbfe")
      const alpha = safeNumber(styles.alpha, safeNumber(styles.opacity, 0.12))
      const fillColor = toRgbaColor(color, alpha)
      return [
        {
          type: "rect",
          attrs: { x, y, width, height },
          styles: { style: "fill", color: fillColor, alpha: 1, opacity: 1 },
        },
      ]
    },
  })
  aiSoftFillRegistered = true
}

function ensureAiCandleHighlightRegistered() {
  if (aiCandleHighlightRegistered) return

  registerOverlay({
    name: AI_CANDLE_HIGHLIGHT_NAME,
    totalStep: 2,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }) => {
      const topPoint = coordinates[0]
      const bottomPoint = coordinates[1]
      if (!topPoint || !bottomPoint) return []

      const styles = (overlay.styles ?? {}) as Record<string, unknown>
      const xCenter = topPoint.x
      const top = Math.min(topPoint.y, bottomPoint.y)
      const bottom = Math.max(topPoint.y, bottomPoint.y)
      const width = Math.max(safeNumber(styles.width, 12), 6)
      const paddingY = safeNumber(styles.paddingY, 6)
      const x = xCenter - width / 2
      const y = top - paddingY
      const height = Math.max(bottom - top + paddingY * 2, 12)
      const rawBorderColor = safeText(styles.borderColor, safeText(styles.color, "#f59e0b"))
      const rawFillColor = safeText(styles.fillColor, rawBorderColor)
      const alpha = safeNumber(styles.alpha, 0.06)
      const borderAlpha = safeNumber(styles.borderAlpha, 0.9)
      const borderSize = safeNumber(styles.borderSize, 1.5)
      const dashedValue = Array.isArray(styles.dashedValue) ? styles.dashedValue as number[] : [4, 3]
      const borderColor = toRgbaColor(rawBorderColor, borderAlpha)
      const fillColor = toRgbaColor(rawFillColor, alpha)

      const borderStyle = {
        color: borderColor,
        size: borderSize,
        style: "dashed",
        dashedValue,
        alpha: 1,
        opacity: 1,
      }

      return [
        {
          type: "rect",
          attrs: { x, y, width, height },
          styles: { style: "fill", color: fillColor, alpha: 1, opacity: 1 },
        },
        { type: "line", attrs: { coordinates: [{ x, y }, { x: x + width, y }] }, styles: borderStyle },
        { type: "line", attrs: { coordinates: [{ x: x + width, y }, { x: x + width, y: y + height }] }, styles: borderStyle },
        { type: "line", attrs: { coordinates: [{ x: x + width, y: y + height }, { x, y: y + height }] }, styles: borderStyle },
        { type: "line", attrs: { coordinates: [{ x, y: y + height }, { x, y }] }, styles: borderStyle },
      ]
    },
  })

  aiCandleHighlightRegistered = true
}

function safeNumber(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function safeText(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback
}

function clampAlpha(alpha: number) {
  return Math.max(0, Math.min(alpha, 1))
}

function toRgbaColor(color: string, alpha: number) {
  const nextAlpha = clampAlpha(alpha)
  const trimmed = color.trim()

  const rgbMatch = trimmed.match(/^rgba?\(([^)]+)\)$/i)
  if (rgbMatch) {
    const parts = rgbMatch[1]
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)

    if (parts.length >= 3) {
      return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${nextAlpha})`
    }
  }

  const hexMatch = trimmed.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hexMatch) {
    const raw = hexMatch[1]
    const hex = raw.length === 3
      ? raw.split("").map((char) => `${char}${char}`).join("")
      : raw
    const red = parseInt(hex.slice(0, 2), 16)
    const green = parseInt(hex.slice(2, 4), 16)
    const blue = parseInt(hex.slice(4, 6), 16)
    return `rgba(${red}, ${green}, ${blue}, ${nextAlpha})`
  }

  return trimmed
}

function getAiOverlayLabel(overlayType: string) {
  switch (overlayType) {
    case "price_zone":
      return "区间"
    case "gap_zone":
      return "缺口"
    case "trend_line":
      return "趋势"
    case "pattern_polyline":
      return "形态"
    case "event_marker":
      return "事件"
    case "ma_marker":
      return "均线"
    case "sentiment_marker":
      return "情绪"
    default:
      return "标记"
  }
}

function getAiOverlayColor(overlayType: string, styles: Record<string, unknown>) {
  const color = safeText(styles.color)
  if (color) return color
  switch (overlayType) {
    case "price_zone":
      return "#6366f1"
    case "gap_zone":
      return "#0ea5e9"
    case "trend_line":
      return "#2563eb"
    case "pattern_polyline":
      return "#7c3aed"
    case "event_marker":
      return "#f97316"
    case "ma_marker":
      return "#475569"
    case "sentiment_marker":
      return "#10b981"
    default:
      return "#64748b"
  }
}

function shortenAiText(text: string, overlayType: string) {
  const compact = text.replace(/\s+/g, "").trim()
  if (!compact) return getAiOverlayLabel(overlayType)
  return compact.slice(0, Math.min(compact.length, 6))
}

function getAiOverlayKind(overlayType: string, pointCount: number): AiOverlayKind {
  if (overlayType === "event_marker" || overlayType === "ma_marker" || overlayType === "sentiment_marker") return "point"
  if (overlayType === "trend_line" || overlayType === "pattern_polyline") return "line"
  if (pointCount >= 2) return "range"
  return "point"
}

function clampIndex(index: number, max: number) {
  if (max <= 0) return 0
  return Math.max(0, Math.min(index, max - 1))
}

function findFirstBarIndexAtOrAfter(bars: StockKlineBar[], timestamp: number) {
  if (bars.length === 0) return -1
  const index = bars.findIndex((bar) => bar.timestamp >= timestamp)
  return index >= 0 ? index : bars.length - 1
}

function findNearestBarIndexByTimestamp(bars: StockKlineBar[], timestamp: number) {
  if (bars.length === 0) return -1
  let nearestIndex = 0
  let nearestDistance = Number.POSITIVE_INFINITY
  bars.forEach((bar, index) => {
    const distance = Math.abs(bar.timestamp - timestamp)
    if (distance < nearestDistance) {
      nearestDistance = distance
      nearestIndex = index
    }
  })
  return nearestIndex
}

function getAnnotationBarRange(annotation: DerivedAiAnnotation, bars: StockKlineBar[]) {
  if (bars.length === 0) return { startIndex: -1, endIndex: -1 }

  if (annotation.kind === "point") {
    const pointIndex = findNearestBarIndexByTimestamp(bars, annotation.anchorTimestamp)
    return { startIndex: pointIndex, endIndex: pointIndex }
  }

  const matchedIndices = annotation.pixelTimestamps
    .map((timestamp) => findNearestBarIndexByTimestamp(bars, timestamp))
    .filter((index) => index >= 0)

  if (matchedIndices.length > 0) {
    return {
      startIndex: Math.min(...matchedIndices),
      endIndex: Math.max(...matchedIndices),
    }
  }

  const startIndex = findFirstBarIndexAtOrAfter(bars, annotation.startTimestamp)
  const endIndex = findFirstBarIndexAtOrAfter(bars, annotation.endTimestamp)
  if (startIndex < 0 || endIndex < 0) return { startIndex: -1, endIndex: -1 }

  return {
    startIndex: Math.min(startIndex, endIndex),
    endIndex: Math.max(startIndex, endIndex),
  }
}

function formatRangeTime(timestamp: number) {
  return new Date(timestamp).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit" })
}

function ensureAiOverlaysRegistered() {
  if (aiOverlaysRegistered) return

  AI_OVERLAY_NAMES.forEach((name) => {
    registerOverlay({
      name,
      totalStep: name === "price_zone" || name === "trend_line" || name === "gap_zone" ? 2 : 1,
      needDefaultPointFigure: false,
      needDefaultXAxisFigure: false,
      needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay }) => {
        const styles = (overlay.styles ?? {}) as Record<string, unknown>
        const rawText = safeText((overlay.extendData as { text?: unknown } | undefined)?.text)
        const shortText = safeText((overlay.extendData as { shortText?: unknown } | undefined)?.shortText, shortenAiText(rawText, name))
        const color = safeText(styles.color, name === "price_zone" ? "#64748b" : "#2563eb")
        const opacity = safeNumber(styles.opacity, 0.12)
        const borderAlpha = name === "price_zone" || name === "gap_zone" ? 0.55 : 0.9

        if (name === "price_zone" || name === "gap_zone") {
          const first = coordinates[0]
          const second = coordinates[1]
          if (!first || !second) return []
          const x = Math.min(first.x, second.x)
          const y = Math.min(first.y, second.y)
          const width = Math.max(Math.abs(second.x - first.x), 80)
          const height = Math.max(Math.abs(second.y - first.y), 8)
          return [
            {
              type: "rect",
              attrs: { x, y, width, height },
              styles: { style: "fill", color, alpha: 0.04 },
            },
            {
              type: "line",
              attrs: { coordinates: [{ x, y }, { x: x + width, y }] },
              styles: { color, size: 1, style: "dashed", dashedValue: [4, 4], alpha: borderAlpha },
            },
            {
              type: "line",
              attrs: { coordinates: [{ x, y: y + height }, { x: x + width, y: y + height }] },
              styles: { color, size: 1, style: "dashed", dashedValue: [4, 4], alpha: borderAlpha },
            },
            {
              type: "text",
              attrs: { x: x + 8, y: y + 14, text: shortText, align: "left", baseline: "middle" },
              styles: { color: "#0f172a", size: 10, weight: "bold" },
            },
          ]
        }

        if (name === "trend_line" || name === "pattern_polyline") {
          if (coordinates.length < 2) return []
          const lineStyle = safeText(styles.style, name === "pattern_polyline" ? "dashed" : "solid")
          const dashedValue = Array.isArray(styles.dashedValue) ? styles.dashedValue as number[] : [4, 4]
          return [
            {
              type: "line",
              attrs: { coordinates },
              styles: {
                color,
                size: safeNumber(styles.size, 2),
                style: lineStyle,
                dashedValue,
                alpha: opacity,
              },
            },
          ]
        }

        const point = coordinates[0]
        if (!point) return []
        const markerColor = name === "sentiment_marker" ? "#10b981" : name === "event_marker" ? "#f97316" : color
        return [
          {
            type: "circle",
            attrs: { x: point.x, y: point.y, r: 4 },
            styles: { style: "stroke", borderColor: markerColor, borderSize: 1.5, color: "#ffffff", alpha: 0.95 },
          },
          {
            type: "text",
            attrs: { x: point.x + 8, y: point.y - 4, text: shortText, align: "left", baseline: "middle" },
            styles: { color: markerColor, size: 10, weight: "bold" },
          },
        ]
      },
    })
  })

  aiOverlaysRegistered = true
}

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
  overlayAnnotations = [],
  bsSignals,
  manualSignalMode,
  onManualSignalCreate,
  symbol,
  period,
  indicators,
  maLines,
  selectionMode = "single",
  selectionColors,
  onSelectionChange,
  onAnalyzeSelection,
}: {
  bars: StockKlineBar[]
  annotations: StockAnnotation[]
  overlayAnnotations?: StockOverlayAnnotation[]
  bsSignals: StockSignalPoint[]
  manualSignalMode: "B" | "S" | null
  onManualSignalCreate: (signal: StockSignalPoint) => void
  symbol: string
  period: StockPeriod
  indicators: string[]
  maLines: number[]
  selectionMode?: "single" | "multiple"
  selectionColors?: Record<string, string>
  onSelectionChange?: (items: ChartPanelSelectionItem[]) => void
  onAnalyzeSelection?: (item: ChartPanelSelectionItem) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<Chart | null>(null)
  const [hoveredSignal, setHoveredSignal] = useState<(StockSignalPoint & { x: number; y: number }) | null>(null)
  const [hoveredAiAnnotation, setHoveredAiAnnotation] = useState<HoveredAiAnnotation | null>(null)
  const [selectedAiAnnotation, setSelectedAiAnnotation] = useState<HoveredAiAnnotation | null>(null)
  const [annotationLabels, setAnnotationLabels] = useState<AiAnnotationLabelPosition[]>([])
  const [selectedBarIndexes, setSelectedBarIndexes] = useState<number[]>([])
  const [chartSizeTick, setChartSizeTick] = useState(0)
  const hasTurnover = useMemo(() => bars.some((bar) => typeof bar.turnover === "number" && bar.turnover > 0), [bars])

  const derivedAiAnnotations = useMemo<DerivedAiAnnotation[]>(() =>
    overlayAnnotations.map((overlay, index) => {
      const points = overlay.points || []
      const sortedPoints = [...points].sort((a, b) => a.timestamp - b.timestamp)
      const startPoint = sortedPoints[0] || points[0]
      const endPoint = sortedPoints[sortedPoints.length - 1] || points[points.length - 1] || startPoint
      const values = points.map((point) => point.value)
      const overlayType = overlay.overlay_type || "event_marker"
      const fullText = safeText(overlay.text, "")
      const shortText = shortenAiText(fullText, overlayType)
      const pixelTimestamps = Array.from(new Set(sortedPoints.map((point) => point.timestamp).filter((ts) => Number.isFinite(ts) && ts > 0)))
      return {
        id: `ai-${overlayType}-${index}`,
        overlay,
        kind: getAiOverlayKind(overlayType, points.length),
        shortText,
        fullText,
        typeLabel: getAiOverlayLabel(overlayType),
        accentColor: getAiOverlayColor(overlayType, overlay.styles || {}),
        startTimestamp: startPoint?.timestamp ?? 0,
        endTimestamp: endPoint?.timestamp ?? startPoint?.timestamp ?? 0,
        minValue: values.length ? Math.min(...values) : startPoint?.value ?? 0,
        maxValue: values.length ? Math.max(...values) : startPoint?.value ?? 0,
        anchorTimestamp: endPoint?.timestamp ?? startPoint?.timestamp ?? 0,
        anchorValue: endPoint?.value ?? startPoint?.value ?? 0,
        anchorHighValue: endPoint?.value ?? startPoint?.value ?? 0,
        anchorLowValue: endPoint?.value ?? startPoint?.value ?? 0,
        pixelTimestamps,
      }
    }),
  [overlayAnnotations])

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

  const getAiPixelPoint = (timestamp: number, value: number) => {
    const chart = chartRef.current
    if (!chart) return null

    return (chart as unknown as {
      convertToPixel: (point: { timestamp: number; value: number }, options?: { paneId?: string }) => { x?: number; y?: number }
    }).convertToPixel(
      {
        timestamp,
        value,
      },
      {
        paneId: MAIN_PANE_ID,
      }
    )
  }

  const getCurrentBarSpace = () => {
    const chart = chartRef.current as unknown as { getBarSpace?: () => number } | null
    const barSpace = chart?.getBarSpace?.()
    return safeNumber(barSpace, 10)
  }

  const getNearestBarIndexFromPixelX = (x: number) => {
    if (bars.length === 0) return -1

    let nearestIndex = -1
    let nearestDistance = Number.POSITIVE_INFINITY
    bars.forEach((bar, index) => {
      const point = getAiPixelPoint(bar.timestamp, bar.close)
      if (!point || typeof point.x !== "number") return
      const distance = Math.abs(point.x - x)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestIndex = index
      }
    })

    return nearestIndex
  }

  const getCandleHitBox = (bar: StockKlineBar) => {
    const centerPoint = getAiPixelPoint(bar.timestamp, bar.close)
    const highPoint = getAiPixelPoint(bar.timestamp, bar.high)
    const lowPoint = getAiPixelPoint(bar.timestamp, bar.low)
    if (!centerPoint || !highPoint || !lowPoint) return null
    if (typeof centerPoint.x !== "number" || typeof centerPoint.y !== "number") return null
    if (typeof highPoint.y !== "number" || typeof lowPoint.y !== "number") return null

    const top = Math.min(highPoint.y, lowPoint.y) - 8
    const bottom = Math.max(highPoint.y, lowPoint.y) + 8
    const halfWidth = Math.max(getCurrentBarSpace() * 0.58, 6)

    return {
      centerX: centerPoint.x,
      centerY: centerPoint.y,
      top,
      bottom,
      halfWidth,
    }
  }

  const buildAiAnnotationHover = (annotation: DerivedAiAnnotation, focusBarIndex?: number): HoveredAiAnnotation | null => {
    const range = getAnnotationBarRange(annotation, bars)
    if (range.startIndex < 0 || range.endIndex < 0) return null

    const startIndex = Math.min(range.startIndex, range.endIndex)
    const endIndex = Math.max(range.startIndex, range.endIndex)
    const clampedFocusIndex = focusBarIndex === undefined
      ? Math.floor((startIndex + endIndex) / 2)
      : clampIndex(focusBarIndex, bars.length)
    const focusBar = bars[clampedFocusIndex] ?? bars[startIndex]
    if (!focusBar) return null

    const tooltipTimestamp = annotation.kind === "point" ? annotation.anchorTimestamp : focusBar.timestamp
    const tooltipValue = annotation.kind === "point" ? annotation.anchorValue : focusBar.close
    const tooltipPixel = getAiPixelPoint(tooltipTimestamp, tooltipValue)
    const fallbackPixel = getAiPixelPoint(focusBar.timestamp, focusBar.close)
    const pixel = tooltipPixel ?? fallbackPixel
    if (!pixel || typeof pixel.x !== "number" || typeof pixel.y !== "number") return null

    return {
      annotation,
      x: pixel.x,
      y: pixel.y,
      left: pixel.x - 8,
      top: pixel.y - 8,
      width: 16,
      height: 16,
      rangeStartIndex: startIndex,
      rangeEndIndex: endIndex,
    }
  }

  const toggleSelectedAiAnnotation = (nextAnnotation: HoveredAiAnnotation) => {
    setSelectedAiAnnotation((current) => {
      if (current?.annotation.id === nextAnnotation.annotation.id) return null
      return nextAnnotation
    })
    setHoveredAiAnnotation(null)
    setHoveredSignal(null)
  }

  const highlightedAiAnnotation = hoveredAiAnnotation ?? selectedAiAnnotation
  const tooltipAiAnnotation = hoveredAiAnnotation
  const isAiAnnotationPinned = Boolean(selectedAiAnnotation)

  const buildSelectedAnnotationItem = (item: HoveredAiAnnotation): ChartPanelSelectedAnnotationItem => ({
    kind: "annotation",
    key: item.annotation.id,
    annotationId: item.annotation.id,
    annotation: item.annotation.overlay,
    overlayType: item.annotation.overlay.overlay_type,
    typeLabel: item.annotation.typeLabel,
    shortText: item.annotation.shortText,
    fullText: item.annotation.fullText,
    startTimestamp: item.annotation.startTimestamp,
    endTimestamp: item.annotation.endTimestamp,
    minValue: item.annotation.minValue,
    maxValue: item.annotation.maxValue,
  })

  useEffect(() => {
    setSelectedBarIndexes([])
    setHoveredSignal(null)
    setHoveredAiAnnotation(null)
    setSelectedAiAnnotation(null)
  }, [symbol, period, bars, overlayAnnotations])

  useEffect(() => {
    const selectedItems: ChartPanelSelectionItem[] = selectedBarIndexes
      .map((index) => {
        const bar = bars[index]
        if (!bar) return null
        return {
          kind: "bar" as const,
          key: `bar-${bar.timestamp}`,
          index,
          bar,
        }
      })
      .filter((item): item is ChartPanelSelectedBarItem => Boolean(item))

    if (selectedAiAnnotation) {
      selectedItems.push(buildSelectedAnnotationItem(selectedAiAnnotation))
    }

    onSelectionChange?.(selectedItems)
  }, [bars, onSelectionChange, selectedAiAnnotation, selectedBarIndexes])

  const handleChartClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const chart = chartRef.current
    const container = containerRef.current
    if (!chart || !container) return

    const bounds = container.getBoundingClientRect()
    const pointerX = event.clientX - bounds.left
    const pointerY = event.clientY - bounds.top
    const coordinate = (chart as unknown as {
      convertFromPixel: (coordinate: { x: number; y: number }, options?: { paneId?: string }) => {
        dataIndex?: number
        timestamp?: number
        value?: number
      }
    }).convertFromPixel(
      {
        x: pointerX,
        y: pointerY,
      },
      {
        paneId: MAIN_PANE_ID,
      }
    )

    const nearestIndex = getNearestBarIndexFromPixelX(pointerX)
    const dataIndex = nearestIndex >= 0 ? nearestIndex : coordinate.dataIndex ?? -1
    if (dataIndex < 0 || dataIndex >= bars.length) return

    const bar = bars[dataIndex]
    if (!bar) return

    if (manualSignalMode) {
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
      setSelectedBarIndexes([])
      setSelectedAiAnnotation(null)
      return
    }

    setSelectedAiAnnotation(null)
    setSelectedBarIndexes((current) => {
      const exists = current.includes(dataIndex)
      if (selectionMode === "multiple") {
        return exists ? current.filter((index) => index !== dataIndex) : [...current, dataIndex].sort((left, right) => left - right)
      }

      return exists ? [] : [dataIndex]
    })
  }

  const handleChartMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current
    const chart = chartRef.current
    if (!container || !chart) {
      setHoveredSignal(null)
      setHoveredAiAnnotation(null)
      return
    }

    const bounds = container.getBoundingClientRect()
    const pointerX = event.clientX - bounds.left
    const pointerY = event.clientY - bounds.top
    const nearestBarIndex = getNearestBarIndexFromPixelX(pointerX)
    const nearestBar = nearestBarIndex >= 0 ? bars[nearestBarIndex] : null
    const hitBox = nearestBar ? getCandleHitBox(nearestBar) : null
    const isHoveringCandle = Boolean(
      hitBox &&
      Math.abs(pointerX - hitBox.centerX) <= hitBox.halfWidth &&
      pointerY >= hitBox.top &&
      pointerY <= hitBox.bottom
    )

    if (isHoveringCandle && nearestBarIndex >= 0 && nearestBar) {
      const matchedAi = derivedAiAnnotations
        .map((annotation) => {
          const range = getAnnotationBarRange(annotation, bars)
          if (range.startIndex < 0 || range.endIndex < 0) return null

          const startIndex = Math.min(range.startIndex, range.endIndex)
          const endIndex = Math.max(range.startIndex, range.endIndex)
          const isMatched = annotation.kind === "point"
            ? nearestBarIndex === startIndex
            : nearestBarIndex >= startIndex && nearestBarIndex <= endIndex

          if (!isMatched) return null

          const span = Math.max(1, endIndex - startIndex + 1)
          const kindPriority = annotation.kind === "point" ? 0 : annotation.kind === "line" ? 1 : 2
          return { annotation, startIndex, endIndex, span, kindPriority }
        })
        .filter((item): item is { annotation: DerivedAiAnnotation; startIndex: number; endIndex: number; span: number; kindPriority: number } => Boolean(item))
        .sort((a, b) => a.kindPriority - b.kindPriority || a.span - b.span)[0]

      if (matchedAi) {
        const nextHoveredAnnotation = buildAiAnnotationHover(matchedAi.annotation, nearestBarIndex)
        if (nextHoveredAnnotation) {
          setHoveredAiAnnotation(nextHoveredAnnotation)
          setHoveredSignal(null)
          return
        }
      }
    }

    setHoveredAiAnnotation(null)

    if (bsSignals.length === 0) {
      setHoveredSignal(null)
      return
    }

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
    setHoveredAiAnnotation(null)
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
    ensureAiOverlaysRegistered()
    ensureAiSoftFillRegistered()
    ensureAiCandleHighlightRegistered()

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
      setChartSizeTick((tick) => tick + 1)
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
    chart.removeOverlay({ groupId: "ai-annotations" })
    chart.removeOverlay({ groupId: "ai-callout" })
    chart.removeOverlay({ groupId: "ai-hover-highlight" })
    chart.removeOverlay({ groupId: "bs-signals" })
    chart.removeOverlay({ groupId: "selected-bar" })

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

    const newLabels: AiAnnotationLabelPosition[] = []
    const containerWidth = containerRef.current?.clientWidth ?? 960
    const containerHeight = containerRef.current?.clientHeight ?? 720
    const labelWidth = 184

    derivedAiAnnotations.forEach((annotation) => {
      const anchorPixel = getAiPixelPoint(annotation.anchorTimestamp, annotation.anchorValue)
      if (!anchorPixel || typeof anchorPixel.x !== "number" || typeof anchorPixel.y !== "number") return

      const startPixel = annotation.kind === "point" ? anchorPixel : getAiPixelPoint(annotation.startTimestamp, annotation.maxValue)
      const endPixel = annotation.kind === "point" ? anchorPixel : getAiPixelPoint(annotation.endTimestamp, annotation.minValue)
      if (!startPixel || !endPixel) return
      if (typeof startPixel.x !== "number" || typeof startPixel.y !== "number") return
      if (typeof endPixel.x !== "number" || typeof endPixel.y !== "number") return

      const startX = Math.min(startPixel.x, endPixel.x)
      const endX = Math.max(startPixel.x, endPixel.x)
      const startY = Math.min(startPixel.y, endPixel.y)
      const endY = Math.max(startPixel.y, endPixel.y)
      const targetX = annotation.kind === "point" ? anchorPixel.x : (startX + endX) / 2
      const targetY = annotation.kind === "point" ? anchorPixel.y : (startY + endY) / 2
      const placeRight = targetX + 24 + labelWidth <= containerWidth
      const labelX = placeRight ? targetX + 24 : Math.max(8, targetX - labelWidth - 24)
      const labelY = Math.max(8, Math.min(targetY - 18, containerHeight - 54))

      newLabels.push({
        id: annotation.id,
        kind: annotation.kind,
        anchorX: targetX,
        anchorY: targetY,
        labelX,
        labelY,
        accentColor: annotation.accentColor,
        shortText: annotation.shortText,
        fullText: annotation.fullText,
        typeLabel: annotation.typeLabel,
        startTimestamp: annotation.startTimestamp,
        endTimestamp: annotation.endTimestamp,
        minValue: annotation.minValue,
        maxValue: annotation.maxValue,
        anchorTimestamp: annotation.anchorTimestamp,
        anchorValue: annotation.anchorValue,
      })
    })

    setAnnotationLabels(newLabels)

    const visibleStartTs = bars[0]?.timestamp
    const visibleEndTs = bars[bars.length - 1]?.timestamp
    const candleWidth = Math.max(getCurrentBarSpace() * 1.2, 8)

    const createCandleFrame = (id: string, bar: StockKlineBar, options?: { borderColor?: string; fillColor?: string; alpha?: number; borderAlpha?: number; borderSize?: number; width?: number; zLevel?: number; groupId?: string }) => {
      chart.createOverlay({
        id,
        groupId: options?.groupId ?? "ai-hover-highlight",
        name: AI_CANDLE_HIGHLIGHT_NAME,
        points: [
          { timestamp: bar.timestamp, value: bar.high },
          { timestamp: bar.timestamp, value: bar.low },
        ],
        lock: true,
        visible: true,
        zLevel: options?.zLevel ?? 31,
        styles: {
          width: options?.width ?? candleWidth,
          paddingY: 5,
          borderColor: options?.borderColor ?? "#f59e0b",
          fillColor: options?.fillColor ?? options?.borderColor ?? "#f59e0b",
          alpha: options?.alpha ?? 0.06,
          borderAlpha: options?.borderAlpha ?? 0.9,
          borderSize: options?.borderSize ?? 1.8,
          dashedValue: [4, 3],
        },
        extendData: { text: "", shortText: "" },
      })
    }

    if (highlightedAiAnnotation && visibleStartTs !== undefined && visibleEndTs !== undefined) {
      const annotation = highlightedAiAnnotation.annotation
      const range = getAnnotationBarRange(annotation, bars)
      const rangeStartIndex = range.startIndex >= 0 ? range.startIndex : highlightedAiAnnotation.rangeStartIndex
      const rangeEndIndex = range.endIndex >= 0 ? range.endIndex : highlightedAiAnnotation.rangeEndIndex
      const startBar = bars[rangeStartIndex]
      const accent = annotation.accentColor

      if (annotation.kind === "point" && startBar) {
        const focusValue = annotation.anchorValue

        createCandleFrame(`ai-highlight-point-bar-${annotation.id}`, startBar, {
          borderColor: accent,
          fillColor: "#fef3c7",
          alpha: 0.14,
          borderAlpha: 0.95,
          borderSize: 2,
          width: candleWidth * 1.2,
        })

        chart.createOverlay({
          id: `ai-highlight-point-price-${annotation.id}`,
          groupId: "ai-hover-highlight",
          name: "trend_line",
          points: [
            { timestamp: visibleStartTs, value: focusValue },
            { timestamp: visibleEndTs, value: focusValue },
          ],
          lock: true,
          visible: true,
          zLevel: 29,
          styles: { color: accent, opacity: 0.62, size: 1, style: "dashed", dashedValue: [5, 4] },
          extendData: { text: "", shortText: "" },
        })

        chart.createOverlay({
          id: `ai-highlight-point-dot-${annotation.id}`,
          groupId: "ai-hover-highlight",
          name: "event_marker",
          points: [{ timestamp: annotation.anchorTimestamp, value: focusValue }],
          lock: true,
          visible: true,
          zLevel: 34,
          styles: { color: accent, opacity: 1 },
          extendData: { text: "", shortText: "" },
        })
      } else if (annotation.kind === "line") {
        const barsInTrend = bars.slice(Math.max(0, rangeStartIndex), Math.min(bars.length, rangeEndIndex + 1))
        barsInTrend.forEach((bar, index) => {
          createCandleFrame(`ai-highlight-trend-bar-${annotation.id}-${bar.timestamp}-${index}`, bar, {
            borderColor: accent,
            fillColor: accent,
            alpha: 0.045,
            borderAlpha: 0.55,
            borderSize: 2.25,
            width: candleWidth * 1.08,
            zLevel: 26,
          })
        })

        chart.createOverlay({
          id: `ai-highlight-trend-line-${annotation.id}`,
          groupId: "ai-hover-highlight",
          name: "trend_line",
          points: annotation.overlay.points.map((point) => ({ timestamp: point.timestamp, value: point.value })),
          lock: true,
          visible: true,
          zLevel: 33,
          styles: { color: accent, opacity: 0.96, size: 4, style: "solid" },
          extendData: { text: "", shortText: "" },
        })
      } else {
        // 区间的红/蓝背景和虚线边界改用 DOM/SVG 渲染，避免 klinecharts overlay 吞掉透明度。
      }
    }

    selectedBarIndexes.forEach((selectedIndex) => {
      const bar = bars[selectedIndex]
      if (bar) {
        const barKey = `bar-${bar.timestamp}`
        const highlightColor = selectionColors?.[barKey] ?? SELECTED_CANDLE_BORDER_COLOR
        createCandleFrame(`selected-bar-highlight-${bar.timestamp}`, bar, {
          groupId: "selected-bar",
          borderColor: highlightColor,
          fillColor: highlightColor,
          alpha: SELECTED_CANDLE_FILL_ALPHA,
          borderAlpha: 0.86,
          borderSize: 1.6,
          width: candleWidth * 1.2,
          zLevel: 35,
        })
      }
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
  }, [annotations, bars, bsSignals, chartSizeTick, derivedAiAnnotations, highlightedAiAnnotation, selectedBarIndexes, selectionColors])

  const visibleAnnotationLabels = highlightedAiAnnotation
    ? annotationLabels.filter((label) => label.id === highlightedAiAnnotation.annotation.id)
    : annotationLabels

  const panelWidth = containerRef.current?.clientWidth ?? 960
  const panelHeight = containerRef.current?.clientHeight ?? 720

  const activeRangeVisual = (() => {
    const active = highlightedAiAnnotation
    if (!active || active.annotation.kind !== "range" || bars.length === 0) return null

    const annotation = active.annotation
    const startBar = bars[active.rangeStartIndex]
    const endBar = bars[Math.max(active.rangeStartIndex, active.rangeEndIndex)]
    const visibleStartTs = bars[0]?.timestamp
    if (!startBar || !endBar || visibleStartTs === undefined) return null

    const chartYMin = Math.min(...bars.map((bar) => bar.low), annotation.minValue)
    const chartYMax = Math.max(...bars.map((bar) => bar.high), annotation.maxValue)

    const priceTopPoint = getAiPixelPoint(visibleStartTs, annotation.maxValue)
    const priceBottomPoint = getAiPixelPoint(visibleStartTs, annotation.minValue)
    const paneTopPoint = getAiPixelPoint(visibleStartTs, chartYMax)
    const paneBottomPoint = getAiPixelPoint(visibleStartTs, chartYMin)
    const timeStartPoint = getAiPixelPoint(startBar.timestamp, chartYMax)
    const timeEndPoint = getAiPixelPoint(endBar.timestamp, chartYMax)

    if (
      !priceTopPoint || !priceBottomPoint || !paneTopPoint || !paneBottomPoint || !timeStartPoint || !timeEndPoint ||
      typeof priceTopPoint.y !== "number" || typeof priceBottomPoint.y !== "number" ||
      typeof paneTopPoint.y !== "number" || typeof paneBottomPoint.y !== "number" ||
      typeof timeStartPoint.x !== "number" || typeof timeEndPoint.x !== "number"
    ) {
      return null
    }

    const priceTop = Math.min(priceTopPoint.y, priceBottomPoint.y)
    const priceBottom = Math.max(priceTopPoint.y, priceBottomPoint.y)
    const paneTop = Math.max(0, Math.min(paneTopPoint.y, paneBottomPoint.y))
    const paneBottom = Math.min(panelHeight, Math.max(paneTopPoint.y, paneBottomPoint.y))
    const timeLeft = Math.max(0, Math.min(timeStartPoint.x, timeEndPoint.x))
    const timeRight = Math.min(panelWidth, Math.max(timeStartPoint.x, timeEndPoint.x))

    return {
      priceTop,
      priceBottom,
      priceHeight: Math.max(priceBottom - priceTop, 1),
      paneTop,
      paneBottom,
      paneHeight: Math.max(paneBottom - paneTop, 1),
      timeLeft,
      timeRight,
      timeWidth: Math.max(timeRight - timeLeft, 1),
    }
  })()

  return (
    <div className="relative" onMouseLeave={handleChartMouseLeave}>
      <div
        ref={containerRef}
        onClick={handleChartClick}
        onMouseMove={handleChartMouseMove}
        className="h-[720px] w-full rounded-2xl bg-background"
      />
      {activeRangeVisual ? (
        <svg className="pointer-events-none absolute inset-0 z-[8] h-full w-full">
          <rect
            x={0}
            y={activeRangeVisual.priceTop}
            width={panelWidth}
            height={activeRangeVisual.priceHeight}
            fill={toRgbaColor(RANGE_PRICE_FILL_COLOR, RANGE_PRICE_FILL_ALPHA)}
          />
          <rect
            x={activeRangeVisual.timeLeft}
            y={activeRangeVisual.paneTop}
            width={activeRangeVisual.timeWidth}
            height={activeRangeVisual.paneHeight}
            fill={toRgbaColor(RANGE_TIME_FILL_COLOR, RANGE_TIME_FILL_ALPHA)}
          />
          <line
            x1={0}
            y1={activeRangeVisual.priceTop}
            x2={panelWidth}
            y2={activeRangeVisual.priceTop}
            stroke={RANGE_PRICE_FILL_COLOR}
            strokeOpacity={RANGE_PRICE_LINE_ALPHA}
            strokeWidth={1.1}
            strokeDasharray="7 5"
          />
          <line
            x1={0}
            y1={activeRangeVisual.priceBottom}
            x2={panelWidth}
            y2={activeRangeVisual.priceBottom}
            stroke={RANGE_PRICE_FILL_COLOR}
            strokeOpacity={RANGE_PRICE_LINE_ALPHA}
            strokeWidth={1.1}
            strokeDasharray="7 5"
          />
          <line
            x1={activeRangeVisual.timeLeft}
            y1={activeRangeVisual.paneTop}
            x2={activeRangeVisual.timeLeft}
            y2={activeRangeVisual.paneBottom}
            stroke={RANGE_TIME_FILL_COLOR}
            strokeOpacity={RANGE_TIME_LINE_ALPHA}
            strokeWidth={1.1}
            strokeDasharray="5 5"
          />
          <line
            x1={activeRangeVisual.timeRight}
            y1={activeRangeVisual.paneTop}
            x2={activeRangeVisual.timeRight}
            y2={activeRangeVisual.paneBottom}
            stroke={RANGE_TIME_FILL_COLOR}
            strokeOpacity={RANGE_TIME_LINE_ALPHA}
            strokeWidth={1.1}
            strokeDasharray="5 5"
          />
        </svg>
      ) : null}
      <svg className="pointer-events-none absolute inset-0 z-[9] h-full w-full">
        {visibleAnnotationLabels.map((label) => {
          const labelAnchorX = label.labelX > label.anchorX ? label.labelX : label.labelX + 184
          const labelAnchorY = label.labelY + 18
          return (
            <line
              key={`${label.id}-leader`}
              x1={label.anchorX}
              y1={label.anchorY}
              x2={labelAnchorX}
              y2={labelAnchorY}
              stroke={label.accentColor}
              strokeDasharray="4 4"
              strokeWidth={1.2}
              strokeOpacity={highlightedAiAnnotation?.annotation.id === label.id ? 0.78 : 0.34}
            />
          )
        })}
      </svg>
      {visibleAnnotationLabels.map((label) => (
        <button
          key={label.id}
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            const matched = derivedAiAnnotations.find((annotation) => annotation.id === label.id)
            if (!matched) return
            const nextSelected = buildAiAnnotationHover(matched)
            if (!nextSelected) return
            toggleSelectedAiAnnotation(nextSelected)
          }}
          className="pointer-events-auto absolute z-10 max-w-[184px] cursor-pointer rounded-lg border border-slate-200 bg-white/88 px-2.5 py-1.5 text-left text-[11px] leading-tight text-slate-700 shadow-sm backdrop-blur-sm transition hover:border-slate-300 hover:bg-white hover:shadow"
          style={{
            left: label.labelX,
            top: label.labelY,
            borderLeft: `3px solid ${label.accentColor}`,
          }}
          title="点击选中并固定该 annotation 的高亮效果"
        >
          <div className="font-semibold text-slate-900" style={{ color: label.accentColor }}>{label.shortText}</div>
          <div className="truncate text-[10px] text-slate-500">{highlightedAiAnnotation?.annotation.id === label.id ? (isAiAnnotationPinned ? "已选中" : "悬停中") : label.typeLabel}</div>
        </button>
      ))}
      {tooltipAiAnnotation ? (
        <div
          role="button"
          tabIndex={0}
          onClick={(event) => {
            event.stopPropagation()
            toggleSelectedAiAnnotation(tooltipAiAnnotation)
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return
            event.preventDefault()
            event.stopPropagation()
            toggleSelectedAiAnnotation(tooltipAiAnnotation)
          }}
          className="pointer-events-auto absolute z-20 w-[260px] cursor-pointer rounded-2xl border border-slate-200 bg-white/95 p-3 text-left text-xs text-slate-700 shadow-[0_16px_40px_rgba(15,23,42,0.14)] backdrop-blur-sm transition hover:border-slate-300 hover:bg-white"
          style={{
            left: Math.min(tooltipAiAnnotation.x + 18, Math.max(16, panelWidth - 280)),
            top: Math.max(16, tooltipAiAnnotation.y - (tooltipAiAnnotation.annotation.kind === "point" ? 88 : 110)),
          }}
        >
          <div className="mb-2 flex items-center gap-2">
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
              style={{ backgroundColor: tooltipAiAnnotation.annotation.accentColor }}
            >
              {tooltipAiAnnotation.annotation.typeLabel}
            </span>
            <span className="text-[11px] font-semibold text-slate-900">{tooltipAiAnnotation.annotation.shortText}</span>
          </div>
          <div className="mb-2 leading-5 text-slate-700">{tooltipAiAnnotation.annotation.fullText || tooltipAiAnnotation.annotation.shortText}</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-500">
            {tooltipAiAnnotation.annotation.kind === "point" ? (
              <>
                <div>时间：{formatRangeTime(tooltipAiAnnotation.annotation.anchorTimestamp)}</div>
                <div>价位：{tooltipAiAnnotation.annotation.anchorValue.toFixed(2)}</div>
                <div>标签：{tooltipAiAnnotation.annotation.shortText}</div>
                <div>类型：{tooltipAiAnnotation.annotation.typeLabel}</div>
              </>
            ) : (
              <>
                <div>开始：{formatRangeTime(tooltipAiAnnotation.annotation.startTimestamp)}</div>
                <div>结束：{formatRangeTime(tooltipAiAnnotation.annotation.endTimestamp)}</div>
                <div>低位：{tooltipAiAnnotation.annotation.minValue.toFixed(2)}</div>
                <div>高位：{tooltipAiAnnotation.annotation.maxValue.toFixed(2)}</div>
              </>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <div className="text-[10px] text-slate-400">
              点击固定该 annotation 高亮
            </div>
            {onAnalyzeSelection ? (
              <button
                type="button"
                className="pointer-events-auto px-0 text-[11px] font-semibold text-slate-700 transition hover:text-slate-950"
                onClick={(event) => {
                  event.stopPropagation()
                  setSelectedAiAnnotation(tooltipAiAnnotation)
                  setHoveredAiAnnotation(null)
                  onAnalyzeSelection(buildSelectedAnnotationItem(tooltipAiAnnotation))
                }}
              >
                Analysis
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {hoveredSignal ? (
        <div
          className="pointer-events-none absolute z-20 min-w-[140px] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-700 shadow-lg"
          style={{
            left: Math.min(hoveredSignal.x + 14, Math.max(16, panelWidth - 180)),
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
