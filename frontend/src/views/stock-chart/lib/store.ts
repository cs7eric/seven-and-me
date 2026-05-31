import { create } from "zustand"

import type { StockAdjust, StockPeriod, StockTargetType } from "./types"

type StockChartState = {
  targetType: StockTargetType
  symbol: string
  name: string
  period: StockPeriod
  adjust: StockAdjust
  indicators: string[]
  maLines: number[]
  drawingTool: string | null
  showAuctionPanel: boolean
  setTarget: (payload: { targetType: StockTargetType; symbol: string; name: string }) => void
  setPeriod: (period: StockPeriod) => void
  setAdjust: (adjust: StockAdjust) => void
  toggleIndicator: (name: string) => void
  toggleMALine: (period: number) => void
  setDrawingTool: (tool: string | null) => void
  setShowAuctionPanel: (visible: boolean) => void
}

const defaultIndicators = ["MA", "BOLL", "MACD", "AMOUNT"]
const defaultMALines = [5, 10, 30]
const defaultPeriod: StockPeriod = "1d"
const defaultAdjust: StockAdjust = "qfq"

export const useStockChartStore = create<StockChartState>((set) => ({
  targetType: "stock",
  symbol: "000001",
  name: "平安银行",
  period: defaultPeriod,
  adjust: defaultAdjust,
  indicators: defaultIndicators,
  maLines: defaultMALines,
  drawingTool: null,
  showAuctionPanel: true,
  setTarget: ({ targetType, symbol, name }) => set({ targetType, symbol, name, period: defaultPeriod, adjust: defaultAdjust }),
  setPeriod: (period) => set({ period }),
  setAdjust: (adjust) => set({ adjust }),
  toggleIndicator: (name) => set((state) => ({ indicators: state.indicators.includes(name) ? state.indicators.filter((item) => item !== name) : [...state.indicators, name] })),
  toggleMALine: (period) => set((state) => ({ maLines: state.maLines.includes(period) ? state.maLines.filter((item) => item !== period) : [...state.maLines, period].sort((a, b) => a - b) })),
  setDrawingTool: (drawingTool) => set({ drawingTool }),
  setShowAuctionPanel: (showAuctionPanel) => set({ showAuctionPanel }),
}))
