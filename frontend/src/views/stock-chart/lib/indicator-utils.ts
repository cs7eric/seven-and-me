import type { StockKlineBar } from "./types"

export interface MAValues {
  ma5: (number | null)[]
  ma10: (number | null)[]
  ma20: (number | null)[]
  ma60: (number | null)[]
  ma120: (number | null)[]
  ma250: (number | null)[]
}

export interface LastBiasRates {
  ma20Bias: number | null
  ma60Bias: number | null
  ma250Bias: number | null
}

export interface LastMASlope {
  ma5Slope: number | null
  ma10Slope: number | null
  ma20Slope: number | null
  ma60Slope: number | null
  ma120Slope: number | null
  ma250Slope: number | null
}

export interface MACDResult {
  dif: (number | null)[]
  dea: (number | null)[]
  histogram: (number | null)[]
}

export interface RSIData {
  rsi6: (number | null)[]
  rsi14: (number | null)[]
}

export interface ATRData {
  atr14: (number | null)[]
  atrPct: (number | null)[]
}

export type TrendStateLabel = "强多头" | "多头修复" | "多头回踩" | "多头调整" | "震荡偏强" | "震荡" | "短线走弱" | "弱反弹" | "中期转弱" | "空头反抽" | "空头趋势"

export interface SignalCard {
  id: string
  label: string
  description: string
  category: "event" | "state" | "risk"
  level: "bullish" | "neutral" | "warning" | "danger"
  conditions: string[]
}

export interface PriceLevel {
  price: number
  label: string
  type: "support" | "resistance"
  source: "swing" | "ma" | "atr"
}

export interface KeyPriceZone {
  supports: PriceLevel[]
  resistances: PriceLevel[]
  stopLoss: { price: number; label: string; method: string } | null
  atrStop: { price: number; label: string } | null
}

export type SignalDirection = "bullish" | "bearish" | "neutral"

export interface SignalBacktest {
  signalId: string
  signalLabel: string
  signalDirection: SignalDirection
  totalOccurrences: number
  winCount: number
  winRate: number | null
  avgReturn5: number | null
  avgReturn10: number | null
  avgReturn20: number | null
  maxReturn20: number | null
  worstReturn20: number | null
  recentOccurrence: { index: number; date: string; forward5Return: number | null; forward10Return: number | null; forward20Return: number | null } | null
  summary: string
}

export interface HistoricalBacktest {
  signals: SignalBacktest[]
  dataPeriod: { start: string; end: string; bars: number }
  note: string
}

export interface ScoreLevel {
  label: string
  desc: string
  tone: "strong" | "good" | "neutral" | "weak" | "danger"
}

export interface ScoreBreakdown {
  score: number
  max: number
  label: string
  desc: string
}

export interface TechnicalScoreDetail {
  total: number
  level: string
  desc: string
  items: {
    maStructure: ScoreBreakdown
    maSlope: ScoreBreakdown
    volumeQuality: ScoreBreakdown
    macdMomentum: ScoreBreakdown
    priceAction: ScoreBreakdown
  }
}

export interface RiskScoreDetail {
  total: number
  level: string
  desc: string
  items: {
    biasRisk: ScoreBreakdown
    sentimentRisk: ScoreBreakdown
    volatilityRisk: ScoreBreakdown
    volumeRisk: ScoreBreakdown
    breakRisk: ScoreBreakdown
  }
}

export interface CompositeScore {
  total: number
  level: string
  desc: string
  decision: string
  riskDiscount: number
}

export function getRatioLevel(score: number, max: number): ScoreLevel {
  const ratio = max > 0 ? score / max : 0
  if (ratio >= 0.8) return { label: "强", desc: "该项贡献明显", tone: "strong" }
  if (ratio >= 0.65) return { label: "良好", desc: "该项表现较好", tone: "good" }
  if (ratio >= 0.5) return { label: "一般", desc: "该项有一定支持，但不够强", tone: "neutral" }
  if (ratio >= 0.35) return { label: "偏弱", desc: "该项支持有限", tone: "weak" }
  return { label: "弱", desc: "该项基本不支持趋势", tone: "danger" }
}

export function getTechnicalLevel(score: number): { level: string; desc: string } {
  if (score >= 80) return { level: "强形态", desc: "多头结构清晰，趋势质量高" }
  if (score >= 65) return { level: "良好形态", desc: "趋势有优势，可重点观察" }
  if (score >= 50) return { level: "修复形态", desc: "有改善，但还不稳定" }
  if (score >= 35) return { level: "弱形态", desc: "支撑不足，容易反复" }
  return { level: "差形态", desc: "空头或明显弱势" }
}

export function getRiskLevel(score: number): { level: string; desc: string } {
  if (score >= 80) return { level: "极高风险", desc: "技术风险全面，优先回避追涨" }
  if (score >= 60) return { level: "高风险", desc: "当前位置风险偏高，不适合追高" }
  if (score >= 40) return { level: "中风险", desc: "存在一定风险，需注意节奏" }
  if (score >= 20) return { level: "中低风险", desc: "风险可控，可正常观察" }
  return { level: "低风险", desc: "位置较健康" }
}

export function getCompositeLevel(score: number): { level: string; desc: string } {
  if (score >= 80) return { level: "高质量机会", desc: "技术形态强，风险可控" }
  if (score >= 65) return { level: "关注机会", desc: "形态较好，可等确认" }
  if (score >= 50) return { level: "观察区", desc: "有亮点，但还不适合直接追" }
  if (score >= 35) return { level: "谨慎区", desc: "风险或结构问题明显" }
  return { level: "回避区", desc: "暂不具备良好参与条件" }
}

export function getScoreDecision(technicalScore: number, riskScore: number, compositeScore: number): string {
  if (technicalScore >= 75 && riskScore <= 35) {
    return "技术形态较强，风险可控，可重点关注回踩或延续信号。"
  }
  if (technicalScore >= 75 && riskScore > 60) {
    return "技术形态较好，但当前风险偏高，不适合追高，建议等待回踩或风险释放。"
  }
  if (technicalScore >= 60 && riskScore <= 45) {
    return "形态有一定优势，风险尚可，可加入观察池等待确认。"
  }
  if (technicalScore < 50 && riskScore <= 40) {
    return "风险不高，但趋势形态不足，暂时缺少参与价值。"
  }
  if (technicalScore < 50 && riskScore > 60) {
    return "技术形态偏弱且风险较高，建议回避。"
  }
  if (compositeScore >= 50) {
    return "当前处于观察区，需结合回踩、量能和市场环境进一步确认。"
  }
  return "当前综合质量不足，暂不适合作为重点机会。"
}

export interface TrendAnalysis {
  trendState: TrendStateLabel
  maShortAlignment: boolean
  maMidAlignment: boolean
  maLongAlignment: boolean
  technicalScore: TechnicalScoreDetail
  riskScore: RiskScoreDetail
  compositeScore: CompositeScore
  lastBias: LastBiasRates
  lastSlope: LastMASlope
  lastRsi6: number | null
  lastRsi14: number | null
  lastAtr14: number | null
  lastAtrPct: number | null
  lastClose: number | null
  lastMa20: number | null
  lastMa60: number | null
  lastMa250: number | null
  lastVolume: number | null
  avgVolume5: number | null
  volumeRatio: number | null
  lastMacd: { dif: number | null; dea: number | null; histogram: number | null }
  signals: SignalCard[]
  keyPriceZone: KeyPriceZone
  backtest: HistoricalBacktest
  dataWarnings: string[]
  priceAboveMa20: boolean
  priceAboveMa60: boolean
  priceAboveMa250: boolean
  ma20AboveMa60: boolean
  ma60AboveMa120: boolean
}

interface IndicatorAt {
  close: number
  volume: number
  ma5: number | null
  ma10: number | null
  ma20: number
  ma60: number
  ma120: number | null
  ma250: number | null
  dif: number | null
  dea: number | null
  histogram: number | null
  ma20Slope5: number | null
  ma60Slope10: number | null
  volRatio: number | null
  rsi6: number | null
  rsi14: number | null
}

function sma(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) {
        sum += values[j]
      }
      result.push(sum / period)
    }
  }
  return result
}

function ema(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  const multiplier = 2 / (period + 1)
  let prev: number | null = null
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else if (i === period - 1) {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += values[j]
      }
      prev = sum / period
      result.push(prev)
    } else {
      prev = (values[i] - prev!) * multiplier + prev!
      result.push(prev)
    }
  }
  return result
}

export function calcMA(bars: StockKlineBar[]): MAValues {
  const closes = bars.map((b) => b.close)
  return {
    ma5: sma(closes, 5),
    ma10: sma(closes, 10),
    ma20: sma(closes, 20),
    ma60: sma(closes, 60),
    ma120: sma(closes, 120),
    ma250: sma(closes, 250),
  }
}

export function calcMACD(bars: StockKlineBar[]): MACDResult {
  const closes = bars.map((b) => b.close)
  const ema12 = ema(closes, 12)
  const ema26 = ema(closes, 26)
  const dif: (number | null)[] = []
  const dea: (number | null)[] = []
  const histogram: (number | null)[] = []

  for (let i = 0; i < closes.length; i++) {
    if (ema12[i] == null || ema26[i] == null) {
      dif.push(null)
    } else {
      dif.push(ema12[i]! - ema26[i]!)
    }
  }

  const validDifs = dif.filter((d): d is number => d != null)
  const deaRaw = ema(validDifs, 9)

  let deaI = 0
  for (let i = 0; i < closes.length; i++) {
    if (dif[i] == null) {
      dea.push(null)
      histogram.push(null)
    } else {
      const deaVal = deaRaw[deaI]
      if (deaVal == null) {
        dea.push(null)
        histogram.push(null)
      } else {
        dea.push(deaVal)
        histogram.push((dif[i]! - deaVal) * 2)
      }
      deaI++
    }
  }

  return { dif, dea, histogram }
}

export function calcRSI(bars: StockKlineBar[]): RSIData {
  const closes = bars.map((b) => b.close)

  const calcSingleRSI = (period: number): (number | null)[] => {
    const result: (number | null)[] = []
    const gains: number[] = []
    const losses: number[] = []

    for (let i = 1; i < closes.length; i++) {
      const change = closes[i] - closes[i - 1]
      gains.push(Math.max(change, 0))
      losses.push(Math.max(-change, 0))
    }

    let prevAvgGain: number | null = null
    let prevAvgLoss: number | null = null

    for (let i = 0; i < closes.length; i++) {
      if (i < period) {
        result.push(null)
        continue
      }

      if (i === period) {
        let sumGain = 0
        let sumLoss = 0
        for (let j = 0; j < period; j++) {
          sumGain += gains[j]
          sumLoss += losses[j]
        }
        prevAvgGain = sumGain / period
        prevAvgLoss = sumLoss / period
      } else {
        if (prevAvgGain == null || prevAvgLoss == null) {
          result.push(null)
          continue
        }
        prevAvgGain = (prevAvgGain * (period - 1) + gains[i - 1]) / period
        prevAvgLoss = (prevAvgLoss * (period - 1) + losses[i - 1]) / period
      }

      const avgGain = prevAvgGain!
      const avgLoss = prevAvgLoss!

      if (avgLoss === 0 && avgGain === 0) {
        result.push(50)
      } else if (avgLoss === 0) {
        result.push(100)
      } else {
        const rs = avgGain / avgLoss
        result.push(100 - 100 / (1 + rs))
      }
    }

    return result
  }

  return {
    rsi6: calcSingleRSI(6),
    rsi14: calcSingleRSI(14),
  }
}

export function calcATR(bars: StockKlineBar[]): ATRData {
  const atr14: (number | null)[] = []
  const atrPct: (number | null)[] = []

  const trValues: number[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i === 0) {
      trValues.push(bars[i].high - bars[i].low)
    } else {
      const highLow = bars[i].high - bars[i].low
      const highPrev = Math.abs(bars[i].high - bars[i - 1].close)
      const lowPrev = Math.abs(bars[i].low - bars[i - 1].close)
      trValues.push(Math.max(highLow, highPrev, lowPrev))
    }
  }

  const period = 14
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) {
      atr14.push(null)
      atrPct.push(null)
      continue
    }

    if (i === period - 1) {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += trValues[j]
      }
      atr14.push(sum / period)
    } else {
      const prevAtr = atr14[i - 1]
      if (prevAtr == null) {
        atr14.push(null)
        atrPct.push(null)
        continue
      }
      atr14.push((prevAtr * (period - 1) + trValues[i]) / period)
    }

    const atr = atr14[i]
    if (atr != null && bars[i].close > 0) {
      atrPct.push(atr / bars[i].close)
    } else {
      atrPct.push(null)
    }
  }

  return { atr14, atrPct }
}

function avgPrevious(values: number[], currentIndex: number, count: number): number | null {
  const start = currentIndex - count
  if (start < 0) return null
  const slice = values.slice(start, currentIndex)
  if (slice.length < count) return null
  return slice.reduce((a, b) => a + b, 0) / count
}

function crossedAbove(values: number[], maSeries: (number | null)[], index: number): boolean {
  if (index <= 0) return false
  const prevMa = maSeries[index - 1]
  const currMa = maSeries[index]
  if (prevMa == null || currMa == null) return false
  return values[index - 1] <= prevMa && values[index] > currMa
}

function crossedBelow(values: number[], maSeries: (number | null)[], index: number): boolean {
  if (index <= 0) return false
  const prevMa = maSeries[index - 1]
  const currMa = maSeries[index]
  if (prevMa == null || currMa == null) return false
  return values[index - 1] >= prevMa && values[index] < currMa
}

function calcSlopeAt(maSeries: (number | null)[], index: number, lookback: number): number | null {
  if (maSeries[index] == null) return null
  const prevIdx = index - lookback
  if (prevIdx >= 0 && maSeries[prevIdx] != null) {
    return (maSeries[index]! - maSeries[prevIdx]!) / maSeries[prevIdx]!
  }
  return null
}

function buildIndicatorAt(
  bars: StockKlineBar[],
  ma: MAValues,
  macd: MACDResult,
  rsi: RSIData,
  index: number
): IndicatorAt | null {
  const bar = bars[index]
  if (!bar) return null

  const close = bar.close
  const volume = bar.volume
  const ma20 = ma.ma20[index]
  const ma60 = ma.ma60[index]
  if (ma20 == null || ma60 == null) return null

  const avgVol5Prev = avgPrevious(
    bars.map((b) => b.volume),
    index,
    5
  )

  return {
    close,
    volume,
    ma5: ma.ma5[index] ?? null,
    ma10: ma.ma10[index] ?? null,
    ma20,
    ma60,
    ma120: ma.ma120[index] ?? null,
    ma250: ma.ma250[index] ?? null,
    dif: macd.dif[index] ?? null,
    dea: macd.dea[index] ?? null,
    histogram: macd.histogram[index] ?? null,
    ma20Slope5: calcSlopeAt(ma.ma20, index, 5),
    ma60Slope10: calcSlopeAt(ma.ma60, index, 10),
    volRatio: avgVol5Prev != null && avgVol5Prev > 0 ? volume / avgVol5Prev : null,
    rsi6: rsi.rsi6[index] ?? null,
    rsi14: rsi.rsi14[index] ?? null,
  }
}

function evaluateSignalsAtIndex(
  bars: StockKlineBar[],
  ma: MAValues,
  macd: MACDResult,
  rsi: RSIData,
  index: number
): SignalCard[] {
  const ind = buildIndicatorAt(bars, ma, macd, rsi, index)
  if (!ind) return []

  const closes = bars.map((b) => b.close)
  const signals: SignalCard[] = []

  const prevClose = bars[index - 1]?.close ?? ind.close
  const dayReturn = (ind.close - prevClose) / prevClose
  const bar = bars[index]
  const upperShadow = (bar.high - Math.max(bar.open, bar.close)) / ind.close
  const closePosition = (bar.close - bar.low) / (bar.high - bar.low || 1)
  const difPct = ind.dif != null ? ind.dif / ind.close : null
  const nearZeroMacd = difPct != null && Math.abs(difPct) < 0.003
  const heavyVolume = ind.volRatio != null && ind.volRatio >= 1.3
  const crossAboveMa60 = crossedAbove(closes, ma.ma60, index)
  const crossBelowMa20 = crossedBelow(closes, ma.ma20, index)
  const crossBelowMa60 = crossedBelow(closes, ma.ma60, index)
  const priceAboveMa20 = ind.close > ind.ma20
  const priceAboveMa60 = ind.close > ind.ma60
  const ma20AboveMa60 = ind.ma20 > ind.ma60
  const hasMidTrend = ma20AboveMa60 && priceAboveMa60 && ind.ma60Slope10 != null && ind.ma60Slope10 >= 0

  const conditions: string[] = []

  if (crossAboveMa60 && ind.ma20Slope5 != null && ind.ma20Slope5 > 0 && heavyVolume) {
    conditions.push("上穿MA60")
    conditions.push("MA20向上")
    conditions.push("放量（量能比≥1.3）")
    if (nearZeroMacd) conditions.push("MACD位于零轴附近")

    signals.push({
      id: "trend-start",
      label: "趋势启动",
      description: conditions.length >= 4 ? "放量突破MA60，各条件共振较好" : "上穿MA60，建议观察确认",
      category: "event",
      level: "bullish",
      conditions: [...conditions],
    })
  }
  conditions.length = 0

  if (ind.close > ind.ma60 && ind.ma20 > ind.ma60 && ind.ma20Slope5 != null && ind.ma20Slope5 > 0) {
    signals.push({
      id: "trend-maintain",
      label: "中期趋势维持",
      description: "价格在MA60上方运行，中期结构完好",
      category: "state",
      level: "bullish",
      conditions: ["收盘价位于MA60上方", "MA20>MA60", "MA20向上"],
    })
  }

  const nearMa20 = Math.abs(ind.close - ind.ma20) / ind.ma20 < 0.03
  const volShrinking = ind.volRatio != null && ind.volRatio < 0.8

  if (hasMidTrend && nearMa20 && volShrinking && ind.close >= ind.ma20) {
    signals.push({
      id: "pullback",
      label: "回踩确认",
      description: "中期趋势完好的背景下，缩量回踩MA20，调整健康",
      category: "event",
      level: "bullish",
      conditions: ["中期趋势完好（MA20>MA60，MA60斜率≥0）", "价格贴近MA20", "成交量缩小"],
    })
  } else if (nearMa20 && volShrinking && !hasMidTrend) {
    signals.push({
      id: "weak-attach",
      label: "弱势贴线",
      description: "价格在MA20附近缩量，但中期趋势未确认，可能只是弱势横盘",
      category: "state",
      level: "neutral",
      conditions: ["价格贴近MA20", "成交量缩小", "中期趋势未确认"],
    })
  }

  const ma20Bias = (ind.close - ind.ma20) / ind.ma20
  if (ma20Bias > 0.12) {
    conditions.push(`价格高于MA20 ${(ma20Bias * 100).toFixed(1)}%`)
  }
  if (ind.rsi6 != null && ind.rsi6 > 80) {
    conditions.push("RSI6高于80")
  }

  const stagnation =
    heavyVolume &&
    dayReturn < 0.02 &&
    upperShadow > 0.03 &&
    closePosition < 0.5

  if (stagnation) {
    conditions.push("放量滞涨（上影线较长、收盘偏低）")
  } else if (heavyVolume && dayReturn < 0.02) {
    conditions.push("放量但涨幅收窄")
  }

  if (conditions.length >= 2) {
    signals.push({
      id: "overheat",
      label: "短线过热",
      description: stagnation
        ? "高位放量滞涨，上影线较长，注意派发风险"
        : "短线情绪偏高，注意回撤风险，不宜追高",
      category: "risk",
      level: conditions.length >= 3 ? "danger" : "warning",
      conditions: [...conditions],
    })
  }
  conditions.length = 0

  const crossMa20Heavy = crossBelowMa20 && heavyVolume
  if (crossMa20Heavy) {
    conditions.push("放量跌破MA20")
  } else if (crossBelowMa20) {
    conditions.push("跌破MA20")
  } else if (!priceAboveMa20) {
    conditions.push("收盘价位于MA20下方")
  }
  if (ind.ma20Slope5 != null && ind.ma20Slope5 < 0) {
    conditions.push("MA20斜率转负")
  }

  const midBreak = crossBelowMa60 || (!priceAboveMa60 && ind.ma60Slope10 != null && ind.ma60Slope10 < 0)

  if (conditions.length >= 2 && midBreak) {
    signals.push({
      id: "trend-break",
      label: "趋势破坏",
      description: "跌破MA60均线系统，趋势明显走弱",
      category: "event",
      level: "danger",
      conditions: [...conditions, "跌破MA60或MA60斜率转负"],
    })
  } else if (conditions.length >= 2 && priceAboveMa60) {
    signals.push({
      id: "short-weak",
      label: "短线走弱",
      description: "短线跌破MA20，但MA60尚在下方，中期趋势未坏",
      category: "event",
      level: "warning",
      conditions: [...conditions],
    })
  } else if (conditions.length >= 2) {
    signals.push({
      id: "mid-weak",
      label: "中期转弱",
      description: "跌破MA20，关注MA60支撑",
      category: "event",
      level: "warning",
      conditions: [...conditions],
    })
  }
  conditions.length = 0

  let reboundCond = 0
  if (!priceAboveMa60) { conditions.push("价格仍在MA60下方"); reboundCond++ }
  if (ind.ma60Slope10 != null && ind.ma60Slope10 < 0) { conditions.push("MA60向下"); reboundCond++ }
  if (ind.dif != null && ind.dea != null && ind.dif > ind.dea && ind.dif < 0) {
    conditions.push("DIF零轴下方位于DEA上方")
  }
  if (ind.volRatio != null && ind.volRatio < 1.0) { conditions.push("成交量不足"); reboundCond++ }

  if (reboundCond >= 2) {
    signals.push({
      id: "weak-rebound",
      label: "弱反弹",
      description: "当前反弹力度偏弱，不宜当作主升浪看待",
      category: "state",
      level: "neutral",
      conditions: [...conditions],
    })
  }

  return signals
}

function findSwingHighs(highs: number[], lookback: number): Array<{ index: number; value: number }> {
  const results: Array<{ index: number; value: number }> = []
  for (let i = lookback; i < highs.length - lookback; i++) {
    const h = highs[i]
    let isSwing = true
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue
      if (highs[j] >= h) { isSwing = false; break }
    }
    if (isSwing) results.push({ index: i, value: h })
  }
  return results
}

function findSwingLows(lows: number[], lookback: number): Array<{ index: number; value: number }> {
  const results: Array<{ index: number; value: number }> = []
  for (let i = lookback; i < lows.length - lookback; i++) {
    const l = lows[i]
    let isSwing = true
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue
      if (lows[j] <= l) { isSwing = false; break }
    }
    if (isSwing) results.push({ index: i, value: l })
  }
  return results
}

function calcKeyPriceZone(
  bars: StockKlineBar[],
  ma: MAValues,
  lastClose: number | null,
  lastAtr14: number | null
): KeyPriceZone {
  const supports: PriceLevel[] = []
  const resistances: PriceLevel[] = []

  const highs = bars.map((b) => b.high)
  const lows = bars.map((b) => b.low)

  const swingHighs20 = findSwingHighs(highs, 3).filter((s) => s.index >= bars.length - 20)
  const swingLows20 = findSwingLows(lows, 3).filter((s) => s.index >= bars.length - 20)
  const swingHighs60 = findSwingHighs(highs, 5).filter((s) => s.index >= bars.length - 60)
  const swingLows60 = findSwingLows(lows, 5).filter((s) => s.index >= bars.length - 60)

  const addedResistancePrices = new Set<number>()
  const addedSupportPrices = new Set<number>()

  const addSupport = (price: number, label: string, source: PriceLevel["source"]) => {
    if (lastClose != null && price >= lastClose) return
    const rounded = Math.round(price * 100) / 100
    if (addedSupportPrices.has(rounded)) return
    addedSupportPrices.add(rounded)
    supports.push({ price: rounded, label, type: "support", source })
  }

  const addResistance = (price: number, label: string, source: PriceLevel["source"]) => {
    if (lastClose != null && price <= lastClose) return
    const rounded = Math.round(price * 100) / 100
    if (addedResistancePrices.has(rounded)) return
    addedResistancePrices.add(rounded)
    resistances.push({ price: rounded, label, type: "resistance", source })
  }

  if (lastClose != null) {
    const ma20 = ma.ma20[bars.length - 1] ?? null
    const ma60 = ma.ma60[bars.length - 1] ?? null
    const ma120 = ma.ma120[bars.length - 1] ?? null
    const ma250 = ma.ma250[bars.length - 1] ?? null

    if (ma20 != null && lastClose > ma20) addSupport(ma20, "MA20", "ma")
    if (ma60 != null && lastClose > ma60) addSupport(ma60, "MA60", "ma")
    if (ma120 != null && lastClose > ma120) addSupport(ma120, "MA120", "ma")
    if (ma250 != null && lastClose > ma250) addSupport(ma250, "MA250", "ma")

    if (ma20 != null && lastClose < ma20) addResistance(ma20, "MA20", "ma")
    if (ma60 != null && lastClose < ma60) addResistance(ma60, "MA60", "ma")
    if (ma120 != null && lastClose < ma120) addResistance(ma120, "MA120", "ma")
    if (ma250 != null && lastClose < ma250) addResistance(ma250, "MA250", "ma")
  }

  if (swingLows20.length > 0) {
    const sorted = [...swingLows20].sort((a, b) => b.value - a.value)
    for (const s of sorted.slice(0, 2)) {
      addSupport(s.value, `近期低点(${bars.length - s.index}天前)`, "swing")
    }
  }

  if (swingLows60.length > 0) {
    const valid = swingLows60.filter((s) => !swingLows20.some((s2) => s2.index === s.index))
    const sorted = [...valid].sort((a, b) => b.value - a.value)
    for (const s of sorted.slice(0, 1)) {
      addSupport(s.value, `中期低点(${bars.length - s.index}天前)`, "swing")
    }
  }

  if (swingHighs20.length > 0) {
    const sorted = [...swingHighs20].sort((a, b) => a.value - b.value)
    for (const s of sorted.slice(0, 2)) {
      addResistance(s.value, `近期高点(${bars.length - s.index}天前)`, "swing")
    }
  }

  if (swingHighs60.length > 0) {
    const valid = swingHighs60.filter((s) => !swingHighs20.some((s2) => s2.index === s.index))
    const sorted = [...valid].sort((a, b) => a.value - b.value)
    for (const s of sorted.slice(0, 1)) {
      addResistance(s.value, `中期高点(${bars.length - s.index}天前)`, "swing")
    }
  }

  supports.sort((a, b) => b.price - a.price)
  resistances.sort((a, b) => a.price - b.price)

  let stopLoss: { price: number; label: string; method: string } | null = null
  let atrStop: { price: number; label: string } | null = null

  if (lastClose != null && lastAtr14 != null) {
    const atr2Price = Math.round((lastClose - lastAtr14 * 2) * 100) / 100
    atrStop = { price: atr2Price, label: "2×ATR止损" }

    const nearestSupport = supports[0]
    if (nearestSupport && nearestSupport.price < lastClose) {
      stopLoss = {
        price: Math.round(Math.max(nearestSupport.price * 0.98, atr2Price) * 100) / 100,
        label: nearestSupport.label,
        method: `基于${nearestSupport.label} + 2%缓冲`
      }
    } else {
      stopLoss = { price: atr2Price, label: "2×ATR止损", method: "无明确支撑，以2×ATR为止损" }
    }
  }

  return { supports, resistances, stopLoss, atrStop }
}

const SIGNAL_DIRECTION_MAP: Record<string, SignalDirection> = {
  "trend-start": "bullish",
  "trend-maintain": "bullish",
  "pullback": "bullish",
  "weak-attach": "neutral",
  "overheat": "bearish",
  "trend-break": "bearish",
  "short-weak": "bearish",
  "mid-weak": "bearish",
  "weak-rebound": "bearish",
}

const SIGNAL_LABELS: Record<string, string> = {
  "trend-start": "趋势启动",
  "trend-maintain": "中期趋势维持",
  "pullback": "回踩确认",
  "weak-attach": "弱势贴线",
  "overheat": "短线过热",
  "trend-break": "趋势破坏",
  "short-weak": "短线走弱",
  "mid-weak": "中期转弱",
  "weak-rebound": "弱反弹",
}

function isWinForDirection(ret: number, direction: SignalDirection): boolean {
  if (direction === "bullish") return ret > 0
  if (direction === "bearish") return ret < 0
  return Math.abs(ret) < 0.03
}

function winLabelForDirection(direction: SignalDirection): string {
  if (direction === "bullish") return "上涨概率"
  if (direction === "bearish") return "下跌概率"
  return "震荡概率"
}

function runHistoricalBacktest(bars: StockKlineBar[]): HistoricalBacktest {
  const signalIds = ["trend-start", "pullback", "overheat", "trend-break", "short-weak", "mid-weak", "weak-rebound"] as const

  if (bars.length < 80) {
    return {
      signals: [],
      dataPeriod: { start: "", end: "", bars: bars.length },
      note: "数据量不足（至少需要80根K线），无法进行有意义的回测"
    }
  }

  const ma = calcMA(bars)
  const macd = calcMACD(bars)
  const rsi = calcRSI(bars)

  const forwardReturn = (fromIdx: number, forwardBars: number): number | null => {
    const entryIdx = fromIdx + 1
    const exitIdx = fromIdx + forwardBars
    if (entryIdx >= bars.length || exitIdx >= bars.length) return null
    return (bars[exitIdx].close - bars[entryIdx].open) / bars[entryIdx].open
  }

  const results: SignalBacktest[] = []

  for (const signalId of signalIds) {
    const direction = SIGNAL_DIRECTION_MAP[signalId] ?? "neutral"
    const occurrences: Array<{ index: number; forward5: number | null; forward10: number | null; forward20: number | null }> = []
    let lastTriggerIndex = -Infinity
    const cooldown = 10

    for (let i = 60; i < bars.length - 20; i++) {
      if (i - lastTriggerIndex < cooldown) continue

      const signalsAtI = evaluateSignalsAtIndex(bars, ma, macd, rsi, i)
      const triggered = signalsAtI.some((s) => s.id === signalId)

      if (triggered) {
        occurrences.push({
          index: i,
          forward5: forwardReturn(i, 5),
          forward10: forwardReturn(i, 10),
          forward20: forwardReturn(i, 20),
        })
        lastTriggerIndex = i
      }
    }

    const total = occurrences.length
    if (total === 0) {
      results.push({
        signalId,
        signalLabel: SIGNAL_LABELS[signalId] ?? signalId,
        signalDirection: direction,
        totalOccurrences: 0,
        winCount: 0,
        winRate: null,
        avgReturn5: null,
        avgReturn10: null,
        avgReturn20: null,
        maxReturn20: null,
        worstReturn20: null,
        recentOccurrence: null,
        summary: "历史数据中未匹配到该信号"
      })
      continue
    }

    const valid20 = occurrences.filter((o) => o.forward20 != null)
    const winCount = valid20.filter((o) => isWinForDirection(o.forward20!, direction)).length

    const avg = (arr: number[]): number | null => (arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null)
    const arr5 = occurrences.filter((o) => o.forward5 != null).map((o) => o.forward5!)
    const arr10 = occurrences.filter((o) => o.forward10 != null).map((o) => o.forward10!)
    const arr20 = valid20.map((o) => o.forward20!)

    const max20 = arr20.length > 0 ? Math.max(...arr20) : null
    const min20 = arr20.length > 0 ? Math.min(...arr20) : null
    const winRate = valid20.length > 0 ? winCount / valid20.length : null
    const winLabel = winLabelForDirection(direction)

    const last = occurrences[occurrences.length - 1]

    let summary = ""
    if (winRate != null) {
      if (winRate >= 0.6) summary = `历史${winLabel}较高(${(winRate * 100).toFixed(0)}%)，信号可信度好`
      else if (winRate >= 0.45) summary = `历史${winLabel}一般(${(winRate * 100).toFixed(0)}%)，需结合其他指标判断`
      else summary = `历史${winLabel}偏低(${(winRate * 100).toFixed(0)}%)，该信号单独参考价值有限`
    }

    results.push({
      signalId,
      signalLabel: SIGNAL_LABELS[signalId] ?? signalId,
      signalDirection: direction,
      totalOccurrences: total,
      winCount,
      winRate,
      avgReturn5: avg(arr5),
      avgReturn10: avg(arr10),
      avgReturn20: avg(arr20),
      maxReturn20: max20,
      worstReturn20: min20,
      recentOccurrence: last ? {
        index: last.index,
        date: new Date(bars[last.index].timestamp).toLocaleDateString("zh-CN"),
        forward5Return: last.forward5,
        forward10Return: last.forward10,
        forward20Return: last.forward20,
      } : null,
      summary,
    })
  }

  return {
    signals: results,
    dataPeriod: {
      start: new Date(bars[0].timestamp).toLocaleDateString("zh-CN"),
      end: new Date(bars[bars.length - 1].timestamp).toLocaleDateString("zh-CN"),
      bars: bars.length,
    },
    note: "回测基于次日开盘入场，历史数据仅供参考，不代表未来表现"
  }
}

export function analyzeTrend(bars: StockKlineBar[]): TrendAnalysis {
  const closes = bars.map((b) => b.close)
  const volumes = bars.map((b) => b.volume)
  const lastIndex = bars.length - 1

  const ma = calcMA(bars)
  const macd = calcMACD(bars)
  const rsi = calcRSI(bars)
  const atr = calcATR(bars)

  const lastClose = closes[lastIndex] ?? null
  const lastMa5 = ma.ma5[lastIndex] ?? null
  const lastMa10 = ma.ma10[lastIndex] ?? null
  const lastMa20 = ma.ma20[lastIndex] ?? null
  const lastMa60 = ma.ma60[lastIndex] ?? null
  const lastMa120 = ma.ma120[lastIndex] ?? null
  const lastMa250 = ma.ma250[lastIndex] ?? null
  const lastDif = macd.dif[lastIndex] ?? null
  const lastDea = macd.dea[lastIndex] ?? null
  const lastHist = macd.histogram[lastIndex] ?? null

  const dataWarnings: string[] = []
  if (bars.length < 60) dataWarnings.push("K线样本不足，MA60以下指标不可靠")
  if (bars.length < 120) dataWarnings.push("MA120数据不足，中期趋势判断受限")
  if (bars.length < 250) dataWarnings.push("MA250数据不足，长期趋势无法判断")

  const priceAboveMa20 = lastClose != null && lastMa20 != null && lastClose > lastMa20
  const priceAboveMa60 = lastClose != null && lastMa60 != null && lastClose > lastMa60
  const priceAboveMa250 = lastClose != null && lastMa250 != null && lastClose > lastMa250
  const ma20AboveMa60 = lastMa20 != null && lastMa60 != null && lastMa20 > lastMa60
  const ma60AboveMa120 = lastMa60 != null && lastMa120 != null && lastMa60 > lastMa120

  const maShortAlignment = lastMa5 != null && lastMa10 != null && lastMa20 != null
    && lastMa5 > lastMa10 && lastMa10 > lastMa20
  const maMidAlignment = ma20AboveMa60
  const maLongAlignment = ma60AboveMa120

  let trendState: TrendStateLabel = "震荡"
  if (priceAboveMa20 && priceAboveMa60 && priceAboveMa250 && ma20AboveMa60) {
    trendState = "强多头"
  } else if (priceAboveMa20 && ma20AboveMa60) {
    trendState = "多头修复"
  } else if (priceAboveMa60 && !priceAboveMa20 && lastMa20 != null) {
    if (lastMa20 > lastMa60) trendState = "多头调整"
    else if (lastMa20 < lastMa60) trendState = "空头反抽"
    else trendState = "震荡"
  } else if (!priceAboveMa60 && lastMa20 != null && lastMa60 != null) {
    if (lastMa20 < lastMa60) {
      trendState = priceAboveMa20 ? "弱反弹" : "空头趋势"
    } else {
      trendState = priceAboveMa20 ? "震荡偏强" : "震荡"
    }
  }

  const hasMidTrendContext = ma20AboveMa60 && priceAboveMa60

  if (hasMidTrendContext && !priceAboveMa20 && priceAboveMa60) {
    const prevClosePrev = lastIndex > 1 ? closes[lastIndex - 1] : null
    const crossMa20Recent = prevClosePrev != null && lastMa20 != null
      && prevClosePrev >= lastMa20 && lastClose! < lastMa20
    if (crossMa20Recent) {
      trendState = "多头回踩"
    }
  }

  if (!priceAboveMa60 && lastMa20 != null && lastMa60 != null && lastMa20 < lastMa60) {
    const lastSlope60 = calcSlopeAt(ma.ma60, lastIndex, 10)
    if (lastSlope60 != null && lastSlope60 < 0 && !priceAboveMa20) {
      trendState = "短线走弱"
    }
  }

  const lastBias: LastBiasRates = {
    ma20Bias: lastClose != null && lastMa20 != null ? (lastClose - lastMa20) / lastMa20 : null,
    ma60Bias: lastClose != null && lastMa60 != null ? (lastClose - lastMa60) / lastMa60 : null,
    ma250Bias: lastClose != null && lastMa250 != null ? (lastClose - lastMa250) / lastMa250 : null,
  }

  const lastSlope: LastMASlope = {
    ma5Slope: calcSlopeAt(ma.ma5, lastIndex, 5),
    ma10Slope: calcSlopeAt(ma.ma10, lastIndex, 5),
    ma20Slope: calcSlopeAt(ma.ma20, lastIndex, 5),
    ma60Slope: calcSlopeAt(ma.ma60, lastIndex, 10),
    ma120Slope: calcSlopeAt(ma.ma120, lastIndex, 15),
    ma250Slope: calcSlopeAt(ma.ma250, lastIndex, 20),
  }

  const prevClose = lastIndex > 0 ? closes[lastIndex - 1] : lastClose
  const dayReturn = prevClose != null && prevClose > 0 ? ((lastClose ?? 0) - prevClose) / prevClose : null
  const avgVol5Prev = avgPrevious(volumes, lastIndex, 5)
  const avgVol20Prev = lastIndex >= 20 ? avgPrevious(volumes, lastIndex, 20) : null
  const lastVol = volumes[lastIndex] ?? null
  const volRatio = lastVol != null && avgVol5Prev != null && avgVol5Prev > 0 ? lastVol / avgVol5Prev : null

  let maStructureScore = 0
  if (priceAboveMa20) maStructureScore += 8
  if (priceAboveMa60) maStructureScore += 8
  if (priceAboveMa250) maStructureScore += 6
  if (ma20AboveMa60) maStructureScore += 4
  if (ma60AboveMa120) maStructureScore += 4

  let maSlopeScore = 0
  const m20s = lastSlope.ma20Slope
  const m60s = lastSlope.ma60Slope
  if (m20s != null && m60s != null) {
    if (m20s > 0) maSlopeScore += 8
    if (m20s > 0.02) maSlopeScore += 4
    if (m60s > 0) maSlopeScore += 4
    if (m60s > 0.01) maSlopeScore += 4
  } else if (m20s != null && m20s > 0) {
    maSlopeScore += 8
  }

  let volumeQualityScore = 0
  if (volRatio != null && dayReturn != null) {
    if (volRatio >= 1.5 && dayReturn > 0 && priceAboveMa20) {
      volumeQualityScore += 10
    } else if (volRatio >= 1.2 && dayReturn > 0) {
      volumeQualityScore += 7
    } else if (volRatio >= 0.8) {
      volumeQualityScore += 4
    } else {
      volumeQualityScore += 1
    }
  }
  if (avgVol20Prev != null && avgVol5Prev != null && avgVol5Prev > avgVol20Prev) {
    volumeQualityScore += 5
  }
  if (lastClose != null && lastMa60 != null && lastClose > lastMa60 && volRatio != null && volRatio > 1.2 && dayReturn != null && dayReturn > 0) {
    volumeQualityScore += 5
  }

  let macdMomentumScore = 0
  if (lastDif != null && lastDea != null) {
    if (lastDif > lastDea) macdMomentumScore += 4
    if (lastDif > 0) macdMomentumScore += 3
    if (lastHist != null && lastHist > 0) macdMomentumScore += 3
  } else if (lastDif != null && lastDif > 0) {
    macdMomentumScore += 3
  }

  let priceActionScore = 0
  if (lastClose != null && lastMa20 != null && lastClose > lastMa20) priceActionScore += 3
  if (maShortAlignment) priceActionScore += 3
  const hasRecentCross = crossedAbove(closes, ma.ma20, lastIndex) || crossedAbove(closes, ma.ma60, lastIndex)
  if (hasRecentCross) priceActionScore += 4

  const technicalScoreRaw = maStructureScore + maSlopeScore + volumeQualityScore + macdMomentumScore + priceActionScore
  const technicalScoreTotal = Math.min(100, Math.round(technicalScoreRaw))
  const techLevel = getTechnicalLevel(technicalScoreTotal)

  let biasRisk = 0
  if (lastBias.ma20Bias != null) {
    if (lastBias.ma20Bias > 0.15) biasRisk += 12
    else if (lastBias.ma20Bias > 0.12) biasRisk += 9
    else if (lastBias.ma20Bias > 0.08) biasRisk += 6
    else if (lastBias.ma20Bias > 0.05) biasRisk += 3
  }
  if (lastBias.ma60Bias != null && lastBias.ma60Bias > 0.2) biasRisk += 6

  let sentimentRisk = 0
  const lastRsi6 = rsi.rsi6[lastIndex] ?? null
  const lastRsi14 = rsi.rsi14[lastIndex] ?? null
  if (lastRsi6 != null && lastRsi6 > 85) sentimentRisk += 10
  else if (lastRsi6 != null && lastRsi6 > 80) sentimentRisk += 7
  else if (lastRsi6 != null && lastRsi6 > 70) sentimentRisk += 3
  if (lastRsi6 != null && lastRsi6 > 80 && lastRsi14 != null && lastRsi14 > 70) sentimentRisk += 3

  let volatilityRisk = 0
  const lastAtr14 = atr.atr14[lastIndex] ?? null
  const lastAtrPct = atr.atrPct[lastIndex] ?? null
  if (lastAtrPct != null && lastAtrPct > 0.08) volatilityRisk += 10
  else if (lastAtrPct != null && lastAtrPct > 0.06) volatilityRisk += 7
  else if (lastAtrPct != null && lastAtrPct > 0.04) volatilityRisk += 4
  else if (lastAtrPct != null && lastAtrPct > 0.02) volatilityRisk += 2

  let volumeRisk = 0
  if (volRatio != null && volRatio >= 1.5 && dayReturn != null && dayReturn < -0.02) {
    volumeRisk += 8
  } else if (volRatio != null && volRatio >= 1.5 && dayReturn != null && dayReturn < 0) {
    volumeRisk += 4
  }
  if (volRatio != null && volRatio >= 1.5 && dayReturn != null && dayReturn < 0.02 && lastBias.ma20Bias != null && lastBias.ma20Bias > 0.08) {
    volumeRisk += 4
  }

  let breakRisk = 0
  if (!priceAboveMa20) breakRisk += 4
  if (!priceAboveMa60 && lastMa60 != null) breakRisk += 5
  if (lastSlope.ma20Slope != null && lastSlope.ma20Slope < 0) breakRisk += 3
  if (lastDif != null && lastDea != null && lastDif < lastDea) breakRisk += 3

  const riskScoreRaw = biasRisk + sentimentRisk + volatilityRisk + volumeRisk + breakRisk
  const riskScoreTotal = Math.min(100, Math.round(riskScoreRaw))
  const riskLvl = getRiskLevel(riskScoreTotal)

  const riskDiscount = Math.max(0.35, 1 - riskScoreTotal * 0.004)
  const compositeScoreTotal = Math.round(technicalScoreTotal * riskDiscount)
  const compLevel = getCompositeLevel(compositeScoreTotal)
  const compDecision = getScoreDecision(technicalScoreTotal, riskScoreTotal, compositeScoreTotal)

  const technicalScore: TechnicalScoreDetail = {
    total: technicalScoreTotal,
    level: techLevel.level,
    desc: techLevel.desc,
    items: {
      maStructure: { score: maStructureScore, max: 35, label: "均线结构", desc: "价格与MA20/60/250的位置及结构" },
      maSlope: { score: maSlopeScore, max: 25, label: "均线斜率", desc: "MA20/MA60的方向与强度" },
      volumeQuality: { score: volumeQualityScore, max: 20, label: "量价配合", desc: "放量方向、均量对比" },
      macdMomentum: { score: macdMomentumScore, max: 10, label: "MACD动能", desc: "DIF位置、方向与MACD柱" },
      priceAction: { score: priceActionScore, max: 10, label: "K线行为", desc: "突破、回踩、修复、站稳关键位" },
    },
  }

  const riskScore: RiskScoreDetail = {
    total: riskScoreTotal,
    level: riskLvl.level,
    desc: riskLvl.desc,
    items: {
      biasRisk: { score: biasRisk, max: 30, label: "乖离风险", desc: "价格是否远离MA20/MA60" },
      sentimentRisk: { score: sentimentRisk, max: 20, label: "情绪过热", desc: "RSI是否过热、连续大涨" },
      volatilityRisk: { score: volatilityRisk, max: 20, label: "波动风险", desc: "ATR占比是否过高" },
      volumeRisk: { score: volumeRisk, max: 15, label: "放量风险", desc: "高位放量滞涨、放量下跌" },
      breakRisk: { score: breakRisk, max: 15, label: "破位风险", desc: "是否跌破MA20/MA60，MACD转弱" },
    },
  }

  const compositeScore: CompositeScore = {
    total: compositeScoreTotal,
    level: compLevel.level,
    desc: compLevel.desc,
    decision: compDecision,
    riskDiscount: Math.round(riskDiscount * 100) / 100,
  }

  const signals = evaluateSignalsAtIndex(bars, ma, macd, rsi, lastIndex)
  const keyPriceZone = calcKeyPriceZone(bars, ma, lastClose, lastAtr14)
  const backtest = runHistoricalBacktest(bars)

  return {
    trendState,
    maShortAlignment,
    maMidAlignment,
    maLongAlignment,
    technicalScore,
    riskScore,
    compositeScore,
    lastBias,
    lastSlope,
    lastRsi6,
    lastRsi14,
    lastAtr14,
    lastAtrPct,
    lastClose,
    lastMa20,
    lastMa60,
    lastMa250,
    lastVolume: lastVol,
    avgVolume5: avgVol5Prev,
    volumeRatio: volRatio,
    lastMacd: { dif: lastDif, dea: lastDea, histogram: lastHist },
    signals,
    keyPriceZone,
    backtest,
    dataWarnings,
    priceAboveMa20,
    priceAboveMa60,
    priceAboveMa250,
    ma20AboveMa60,
    ma60AboveMa120,
  }
}
