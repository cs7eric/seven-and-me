export type StrongRow = {
  name: string
  changePct?: number
  changePercent?: number
  amount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  stockCount?: number
}

export type FlowRow = {
  name: string
  changePct?: number
  mainNet: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  leadingPrice?: number | null
}

export type RotationItem = {
  name: string
  changePct: number
  rank: number
  mainNet?: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
}

export type RotationRow = {
  date: string
  topN: number
  items: RotationItem[]
}

export type MarketPulse = {
  ok: boolean
  strong: {
    ok: boolean
    top: StrongRow[]
    bottom: StrongRow[]
    fetchedAt?: string
    count?: number
    tradeDate?: string | null
    requestedTradeDate?: string | null
    isFallbackTradeDate?: boolean
    source?: string
    sourceKind?: string | null
  }
  flow: {
    ok: boolean
    inflow: FlowRow[]
    outflow: FlowRow[]
    inflowCount?: number
    outflowCount?: number
    elapsedMs?: number
    kind?: string
    source?: string
    sourceKind?: string | null
    unit?: string
    tradeDate?: string | null
    requestedTradeDate?: string | null
    isFallbackTradeDate?: boolean
  }
  rotation: {
    ok: boolean
    dates: string[]
    rows: RotationRow[]
    topN?: number
    tradeDate?: string | null
    requestedTradeDate?: string | null
    isFallbackTradeDate?: boolean
    source?: string
    sourceKind?: string | null
  }
}

export type TrendIndustry = {
  name: string
  appearances: number
  avgRank: number | null
  bestRank: number | null
  worstRank: number | null
  latestRank: number | null
  latestChangePct: number | null
  ranks: (number | null)[]
  changePcts: (number | null)[]
}

export type RotationTrendData = {
  ok: boolean
  topN: number
  days: number
  dates: string[]
  industries: TrendIndustry[]
}

export type IndustryDetail = {
  ok: boolean
  name: string
  changePct?: number
  mainNet?: number
  inflow?: number
  outflow?: number
  stockCount?: number
  leadingStock?: string | null
  leadingChangePct?: number | null
  leadingQuote?: Record<string, unknown> | null
  leadingKLine?: Array<Record<string, unknown>>
  leadingFlow30d?: Array<{
    date?: string
    mainNet?: number
    largeNet?: number
    mediumNet?: number
    smallNet?: number
  }>
  leadingFlowSeed?: string
  constituents?: unknown[]
  error?: string
}

export type SchedulerStatus = {
  isRunning?: boolean
  schedulerStartedAt?: string
  lastRunAt?: string | null
  lastRunOk?: boolean | null
  lastInsideRefreshAt?: string | null
  lastCloseSnapshotAt?: string | null
  totalInside?: number
  totalClose?: number
  insideIntervalSeconds?: number
  closeSnapshotCron?: string
  isTradeTime?: boolean
  isTradingDay?: boolean
  now?: string
  lastTopN?: Array<{ name?: string; changePct?: number }>
}
