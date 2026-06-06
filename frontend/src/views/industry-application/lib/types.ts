export interface ApplicationAnalysisDailySnapshot {
  short_term_trend?: Record<string, unknown> | null
  current_situation?: Record<string, unknown> | null
  summary?: Record<string, unknown> | null
  updated_at?: string
}

export interface IndustryApplicationTarget {
  id: string
  target_type: "industry" | "concept"
  symbol: string
  name: string
  enabled?: boolean
  interval_minutes?: number
  tags?: string[]
}

export interface IndustryApplicationHorizon {
  days: number
  segments: number
}

export interface IndustryApplicationConfig {
  version: number
  updated_at?: string | null
  horizon: IndustryApplicationHorizon
  items: IndustryApplicationTarget[]
}

export interface IndustryApplicationIndexBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  prev_close: number | null
  pct: number | null
  volume_lots: number
  amount: number
}

export interface IndustryApplicationIndicators {
  latest_close?: number
  latest_pct?: number | null
  latest_time?: string
  ma20?: number | null
  ma60?: number | null
  ma120?: number | null
  ma250?: number | null
  above_ma20?: boolean
  above_ma60?: boolean
  above_ma20_pct?: number | null
  above_ma60_pct?: number | null
  above_ma20_streak?: number
  high_20?: number | null
  low_20?: number | null
  range_pos_20?: number | null
  return_5d?: number | null
  return_20d?: number | null
  return_60d?: number | null
  bar_count?: number
}

export interface IndustryApplicationKlinePayload {
  target_type: "industry" | "concept"
  code: string
  name: string
  period: string
  kline: IndustryApplicationIndexBar[]
  indicators: IndustryApplicationIndicators
  fetched_at: string
  source: string
}

export interface IndustryApplicationTargetCode {
  code: string
  name: string
  kind: "industry" | "concept"
}
