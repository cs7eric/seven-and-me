export type StockTargetType = "stock" | "index" | "sector"
export type StockPeriod = "1m" | "5m" | "15m" | "30m" | "60m" | "120m" | "1d" | "1w"
export type StockAdjust = "none" | "qfq" | "hfq"

export interface StockSearchItem {
  target_type: StockTargetType
  symbol: string
  name: string
}

export interface StockKlineBar {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover?: number
  volume_ratio?: number
}

export interface StockWorkspace {
  id: string
  symbol: string
  target_type: StockTargetType
  period: StockPeriod
  adjust: StockAdjust
  indicators: string[]
  drawing_tool: string | null
  show_auction_panel: boolean
  updated_at: string | null
}

export interface StockAnnotation {
  id: string
  overlay_type: string
  points: Array<{ timestamp: number; value: number }>
  styles: Record<string, unknown>
  text: string
  created_at: string
  updated_at: string
}

export interface StockAuctionPhaseSnapshot {
  price?: number
  volume?: number
  amount?: number
  matchPrice?: number
  unmatchedBuyVolume?: number
  unmatchedSellVolume?: number
  time?: string
  gapRate?: number
  auctionVolumeRatio?: number
  unmatchedDelta?: number
  strengthLabel?: string
}

export interface StockAuctionSnapshot {
  symbol: string
  trade_date: string
  opening?: StockAuctionPhaseSnapshot
  closing?: StockAuctionPhaseSnapshot
}
