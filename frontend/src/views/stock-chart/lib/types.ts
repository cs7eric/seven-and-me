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
  trade_date?: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover?: number
  turnover_rate?: number
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

export interface StockOverlayAnnotation {
  target_type?: StockTargetType
  symbol?: string
  period: string
  overlay_type: "price_zone" | "trend_line" | "pattern_polyline" | "event_marker" | "gap_zone" | "ma_marker" | "sentiment_marker" | string
  points: Array<{ timestamp: number; value: number }>
  styles: Record<string, unknown>
  text: string
}

export interface ApplicationAnalysisResponse {
  analysis_input: Record<string, unknown>
  analysis_result: Record<string, unknown> & {
    target?: {
      target_type: StockTargetType
      symbol: string
      name: string
    }
    data_quality?: Record<string, unknown> & { warnings?: string[] }
    trend_state?: Record<string, unknown>
    rolling_metrics?: Record<string, unknown>
    support_resistance_zones?: Array<Record<string, unknown>>
    pattern_candidates?: Array<Record<string, unknown>>
    market_sentiment?: Record<string, unknown>
    multi_index_resonance?: Record<string, unknown>
    summary?: Record<string, unknown> & {
      current_status?: string
      main_support?: string[]
      main_resistance?: string[]
      main_risks?: string[]
      main_observations?: string[]
    }
    overlay_annotations?: StockOverlayAnnotation[]
  }
  raw_result: Record<string, unknown>
}

export interface StockSignalPoint {
  id: string
  timestamp: number
  trade_date?: string
  price: number
  side: "B" | "S"
  label?: string
  reason?: string
  score?: number
  period?: string
  source?: "manual"
}

export interface StockAuctionPriceRange {
  low: number
  high: number
  spread: number
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
  anchorExact?: boolean
  anchorSource?: string
  anchorTargetTime?: string
  priceRange?: StockAuctionPriceRange | null
  recentPriceTrend?: string
  recentPriceChange?: number | null
  recentVolumeDelta?: number | null
  directionStability?: string
  directionFlipCount?: number
  dominantDirection?: string
  imbalancePressure?: number | null
  dataConfidence?: string
}

export interface StockAuctionPoint {
  time_label: string
  price?: number
  matched_volume?: number
  unmatched_volume?: number
  unmatched_direction_raw?: number
  matched_amount_estimated?: number
}

export interface StockAuctionDetails {
  quote?: Record<string, unknown>
  auction0925?: Record<string, unknown>
  openingPoints?: StockAuctionPoint[]
  closingPoints?: StockAuctionPoint[]
  allPoints?: StockAuctionPoint[]
}

export interface StockAuctionSnapshot {
  symbol: string
  trade_date: string
  opening?: StockAuctionPhaseSnapshot
  closing?: StockAuctionPhaseSnapshot
  details?: StockAuctionDetails
}

export interface StockIntradayMinuteBars {
  "1m": StockKlineBar[]
  "5m": StockKlineBar[]
  "15m": StockKlineBar[]
  "30m"?: StockKlineBar[]
}

export interface StockIntradayPoint {
  timestamp: number
  trade_date?: string | null
  time_label: string
  price: number
  avg_price?: number | null
  volume: number
  turnover?: number | null
  turnover_rate?: number | null
}

export interface StockIntradayResponse {
  ok: boolean
  symbol: string
  target_type: StockTargetType
  name: string
  adjust: StockAdjust
  effective_adjust?: StockAdjust | string
  requested_adjust?: StockAdjust | string
  source?: string
  trade_date?: string | null
  requested_trade_date?: string | null
  timeshare: StockIntradayPoint[]
  minute_bars: Partial<StockIntradayMinuteBars>
  error?: string
}
