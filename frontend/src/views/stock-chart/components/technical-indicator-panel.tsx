import { useMemo } from "react"
import { IconMinus, IconAlertTriangle, IconFlame, IconActivity, IconGauge, IconArrowUp, IconShield, IconTarget, IconHistory } from "@tabler/icons-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import type { StockKlineBar } from "../lib/types"
import { analyzeTrend, getRatioLevel, type SignalCard, type TrendAnalysis, type ScoreLevel, type SignalDirection } from "../lib/indicator-utils"

function formatPct(value: number | null): string {
  if (value == null) return "—"
  return `${(value * 100).toFixed(2)}%`
}

function formatNum(value: number | null, decimals = 2): string {
  if (value == null) return "—"
  return value.toFixed(decimals)
}

function formatVol(value: number | null): string {
  if (value == null) return "—"
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return value.toFixed(0)
}

function maStateColor(state: string): string {
  switch (state) {
    case "强多头":
      return "bg-emerald-600"
    case "多头修复":
      return "bg-emerald-500"
    case "多头回踩":
      return "bg-emerald-400"
    case "多头调整":
      return "bg-teal-500"
    case "震荡偏强":
      return "bg-lime-600"
    case "震荡":
      return "bg-amber-500"
    case "短线走弱":
      return "bg-orange-400"
    case "弱反弹":
      return "bg-orange-400"
    case "中期转弱":
      return "bg-orange-500"
    case "空头反抽":
      return "bg-orange-600"
    case "空头趋势":
      return "bg-red-500"
    default:
      return "bg-slate-400"
  }
}

function trendScoreColor(score: number): string {
  if (score >= 80) return "text-emerald-600"
  if (score >= 65) return "text-emerald-500"
  if (score >= 50) return "text-amber-500"
  if (score >= 35) return "text-orange-500"
  return "text-red-500"
}

function signalLevelColor(level: SignalCard["level"]): string {
  switch (level) {
    case "bullish":
      return "border-emerald-400 bg-emerald-50/70"
    case "neutral":
      return "border-slate-300 bg-slate-50/70"
    case "warning":
      return "border-amber-400 bg-amber-50/70"
    case "danger":
      return "border-red-400 bg-red-50/70"
  }
}

function signalLevelBadge(level: SignalCard["level"]): { variant: "default" | "secondary" | "destructive" | "outline"; label: string } {
  switch (level) {
    case "bullish":
      return { variant: "default", label: "看多" }
    case "neutral":
      return { variant: "secondary", label: "中性" }
    case "warning":
      return { variant: "outline", label: "警示" }
    case "danger":
      return { variant: "destructive", label: "风险" }
  }
}

function returnColorByDirection(value: number, direction: SignalDirection): string {
  if (direction === "bullish") return value >= 0 ? "text-emerald-500" : "text-red-500"
  if (direction === "bearish") return value <= 0 ? "text-emerald-500" : "text-red-500"
  return "text-slate-600"
}

function scoreLevelBadge(tone: ScoreLevel["tone"]): { variant: "default" | "secondary" | "destructive" | "outline"; className: string } {
  switch (tone) {
    case "strong": return { variant: "default", className: "bg-emerald-600 text-white" }
    case "good": return { variant: "default", className: "bg-emerald-500 text-white" }
    case "neutral": return { variant: "secondary", className: "" }
    case "weak": return { variant: "outline", className: "border-amber-400 text-amber-600" }
    case "danger": return { variant: "destructive", className: "" }
  }
}

function ScoreBar({ score, max, label }: { score: number; max: number; label: string }) {
  const pct = Math.min(100, Math.max(0, (score / max) * 100))
  const level = getRatioLevel(score, max)
  const badge = scoreLevelBadge(level.tone)
  return (
    <div className="flex items-center gap-3 text-xs">
      <div className="flex items-center gap-1.5 w-28 shrink-0">
        <span className="text-slate-600">{label}</span>
        <Badge variant={badge.variant} className={`text-[10px] px-1 ${badge.className}`}>{level.label}</Badge>
      </div>
      <span className="w-10 text-right tabular-nums text-slate-500">{score}</span>
      <Progress value={pct} className="h-1.5 flex-1" />
      <span className="w-8 text-right tabular-nums text-[10px] text-slate-400">{max}</span>
    </div>
  )
}

function TechnicalScoreCard({ analysis }: { analysis: TrendAnalysis }) {
  const ts = analysis.technicalScore
  const color = ts.total >= 80 ? "text-emerald-600" : ts.total >= 65 ? "text-emerald-500" : ts.total >= 50 ? "text-amber-500" : "text-slate-500"
  const bg = ts.total >= 80 ? "border-emerald-200 bg-emerald-50/70" : ts.total >= 65 ? "border-emerald-100 bg-emerald-50/50" : ts.total >= 50 ? "border-amber-100 bg-amber-50/50" : "border-slate-200 bg-slate-50/50"

  return (
    <div className={`rounded-xl border p-4 ${bg}`}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-slate-700">技术形态分</div>
          <div className="text-xs text-slate-400">判断形态结构是否健康</div>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-bold tabular-nums ${color}`}>{ts.total}</div>
          <div className="text-xs text-slate-400">/ 100 · {ts.level}</div>
        </div>
      </div>
      <div className="mb-2 text-xs text-slate-500">{ts.desc}</div>
      <div className="space-y-1 rounded-lg bg-white/70 p-2.5">
        <ScoreBar score={ts.items.maStructure.score} max={ts.items.maStructure.max} label={ts.items.maStructure.label} />
        <ScoreBar score={ts.items.maSlope.score} max={ts.items.maSlope.max} label={ts.items.maSlope.label} />
        <ScoreBar score={ts.items.volumeQuality.score} max={ts.items.volumeQuality.max} label={ts.items.volumeQuality.label} />
        <ScoreBar score={ts.items.macdMomentum.score} max={ts.items.macdMomentum.max} label={ts.items.macdMomentum.label} />
        <ScoreBar score={ts.items.priceAction.score} max={ts.items.priceAction.max} label={ts.items.priceAction.label} />
      </div>
    </div>
  )
}

function RiskScoreCard({ analysis }: { analysis: TrendAnalysis }) {
  const rs = analysis.riskScore
  const color = rs.total >= 80 ? "text-red-600" : rs.total >= 60 ? "text-red-500" : rs.total >= 40 ? "text-amber-500" : "text-emerald-500"
  const bg = rs.total >= 80 ? "border-red-200 bg-red-50/70" : rs.total >= 60 ? "border-red-100 bg-red-50/50" : rs.total >= 40 ? "border-amber-100 bg-amber-50/50" : "border-emerald-100 bg-emerald-50/50"

  return (
    <div className={`rounded-xl border p-4 ${bg}`}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-slate-700">风险系数</div>
          <div className="text-xs text-slate-400">判断当前位置是否危险</div>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-bold tabular-nums ${color}`}>{rs.total}</div>
          <div className="text-xs text-slate-400">/ 100 · {rs.level}</div>
        </div>
      </div>
      <div className="mb-2 text-xs text-slate-500">{rs.desc}</div>
      <div className="space-y-1 rounded-lg bg-white/70 p-2.5">
        <ScoreBar score={rs.items.biasRisk.score} max={rs.items.biasRisk.max} label={rs.items.biasRisk.label} />
        <ScoreBar score={rs.items.sentimentRisk.score} max={rs.items.sentimentRisk.max} label={rs.items.sentimentRisk.label} />
        <ScoreBar score={rs.items.volatilityRisk.score} max={rs.items.volatilityRisk.max} label={rs.items.volatilityRisk.label} />
        <ScoreBar score={rs.items.volumeRisk.score} max={rs.items.volumeRisk.max} label={rs.items.volumeRisk.label} />
        <ScoreBar score={rs.items.breakRisk.score} max={rs.items.breakRisk.max} label={rs.items.breakRisk.label} />
      </div>
    </div>
  )
}

function CompositeScoreCard({ analysis }: { analysis: TrendAnalysis }) {
  const cs = analysis.compositeScore
  const ts = analysis.technicalScore
  const rs = analysis.riskScore
  const color = cs.total >= 80 ? "text-emerald-600" : cs.total >= 65 ? "text-emerald-500" : cs.total >= 50 ? "text-amber-500" : cs.total >= 35 ? "text-orange-500" : "text-red-500"
  const bg = cs.total >= 80 ? "border-emerald-200 bg-emerald-50/70" : cs.total >= 65 ? "border-emerald-100 bg-emerald-50/50" : cs.total >= 50 ? "border-amber-100 bg-amber-50/50" : cs.total >= 35 ? "border-orange-100 bg-orange-50/50" : "border-red-200 bg-red-50/70"

  const techHigh = ts.total >= 65
  const riskLow = rs.total <= 40
  const riskHigh = rs.total >= 60

  let matrixLabel: string
  if (techHigh && riskLow) matrixLabel = "最理想，重点关注"
  else if (techHigh && riskHigh) matrixLabel = "形态好但位置危险，等回踩"
  else if (!techHigh && riskLow) matrixLabel = "没什么风险，但也没趋势"
  else if (!techHigh && riskHigh) matrixLabel = "最差，回避"
  else matrixLabel = "形态一般，风险中等，观察"

  return (
    <div className={`rounded-xl border p-4 ${bg}`}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-slate-700">综合评分</div>
          <div className="text-xs text-slate-400">形态分 × 风险折扣</div>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-bold tabular-nums ${color}`}>{cs.total}</div>
          <div className="text-xs text-slate-400">/ 100 · {cs.level}</div>
        </div>
      </div>

      <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">
        <span>风险折扣</span>
        <span className="font-bold tabular-nums text-slate-700">×{cs.riskDiscount.toFixed(2)}</span>
        <span className="text-slate-400">({ts.total} × {cs.riskDiscount.toFixed(2)} ≈ {cs.total})</span>
      </div>

      <div className="mb-3 rounded-lg bg-white/70 px-3 py-2 text-sm text-slate-600">
        {cs.decision}
      </div>

      <div className="flex items-center justify-between rounded-lg bg-white/70 px-3 py-2 text-xs">
        <span className="text-slate-400">二维矩阵</span>
        <span className={`font-medium ${matrixLabel.includes("理想") ? "text-emerald-600" : matrixLabel.includes("最差") ? "text-red-500" : matrixLabel.includes("危险") ? "text-amber-500" : "text-slate-600"}`}>
          {matrixLabel}
        </span>
      </div>
    </div>
  )
}

function TrendStatusOverview({ analysis }: { analysis: TrendAnalysis }) {
  const rs = analysis.riskScore
  const riskColor = rs.total >= 60 ? "text-red-500" : rs.total >= 40 ? "text-amber-500" : "text-emerald-500"

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-4">
      <div className="flex items-center gap-3">
        <Badge className={`${maStateColor(analysis.trendState)} text-white px-3 py-1 text-sm`}>{analysis.trendState}</Badge>
      </div>

      <Separator orientation="vertical" className="h-8" />

      <div className="flex items-center gap-2">
        <IconGauge className="size-4 text-slate-400" />
        <span className="text-xs text-slate-500">技术</span>
        <span className={`text-lg font-bold tabular-nums ${trendScoreColor(analysis.technicalScore.total)}`}>{analysis.technicalScore.total}</span>
        <Badge variant="outline" className="text-xs">{analysis.technicalScore.level}</Badge>
      </div>

      <Separator orientation="vertical" className="h-8" />

      <div className="flex items-center gap-2">
        <IconAlertTriangle className="size-4 text-slate-400" />
        <span className="text-xs text-slate-500">风险</span>
        <span className={`text-lg font-bold tabular-nums ${riskColor}`}>{analysis.riskScore.total}</span>
        <Badge variant="outline" className="text-xs">{analysis.riskScore.level}</Badge>
      </div>

      <Separator orientation="vertical" className="h-8" />

      <div className="flex items-center gap-2">
        <IconActivity className="size-4 text-slate-400" />
        <span className="text-xs text-slate-500">综合</span>
        <span className={`text-lg font-bold tabular-nums ${trendScoreColor(analysis.compositeScore.total)}`}>{analysis.compositeScore.total}</span>
        <Badge variant="outline" className="text-xs">{analysis.compositeScore.level}</Badge>
      </div>

      <Separator orientation="vertical" className="h-8" />

      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">量能</span>
        {analysis.volumeRatio != null ? (
          <>
            <span className={`text-sm font-bold tabular-nums ${analysis.volumeRatio >= 1.5 ? "text-emerald-500" : analysis.volumeRatio >= 1.0 ? "text-slate-700" : "text-slate-400"}`}>
              {analysis.volumeRatio.toFixed(1)}x
            </span>
            <Badge variant="outline" className="text-xs">
              {analysis.volumeRatio >= 1.5 ? "放量" : analysis.volumeRatio >= 1.0 ? "正常" : "缩量"}
            </Badge>
          </>
        ) : (
          <span className="text-xs text-slate-400">数据不足</span>
        )}
      </div>

      {analysis.priceAboveMa60 && analysis.lastSlope.ma20Slope != null && analysis.lastSlope.ma20Slope > 0 ? (
        <>
          <Separator orientation="vertical" className="h-8" />
          <Badge variant="default" className="bg-emerald-600 text-white text-xs">中期多头结构</Badge>
        </>
      ) : null}
    </div>
  )
}

function MAPositionSection({ analysis }: { analysis: TrendAnalysis }) {
  const items = [
    { label: "收盘价 > MA20", value: analysis.priceAboveMa20, desc: "短中期趋势偏强" },
    { label: "收盘价 > MA60", value: analysis.priceAboveMa60, desc: "中期趋势偏强" },
    { label: "收盘价 > MA250", value: analysis.priceAboveMa250, desc: "长期趋势偏强" },
    { label: "MA20 > MA60", value: analysis.ma20AboveMa60, desc: "中期结构改善" },
    { label: "MA60 > MA120", value: analysis.ma60AboveMa120, desc: "长周期趋势改善" },
  ]

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">均线位置</div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className={`flex size-5 shrink-0 items-center justify-center rounded-full ${item.value ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              {item.value ? <IconArrowUp className="size-3" /> : <IconMinus className="size-3" />}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-medium text-slate-700 truncate">{item.label}</div>
              <div className="text-[10px] text-slate-400">{item.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function MASlopeSection({ analysis }: { analysis: TrendAnalysis }) {
  const items = [
    { label: "MA5斜率", value: analysis.lastSlope.ma5Slope },
    { label: "MA10斜率", value: analysis.lastSlope.ma10Slope },
    { label: "MA20斜率", value: analysis.lastSlope.ma20Slope },
    { label: "MA60斜率", value: analysis.lastSlope.ma60Slope },
    { label: "MA120斜率", value: analysis.lastSlope.ma120Slope },
    { label: "MA250斜率", value: analysis.lastSlope.ma250Slope },
  ]

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">均线斜率</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {items.map((item) => (
          <div key={item.label} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
            <div className="text-[10px] text-slate-400">{item.label}</div>
            <div className={`text-sm font-bold tabular-nums ${item.value != null ? (item.value > 0 ? "text-emerald-500" : "text-red-500") : "text-slate-300"}`}>
              {item.value != null ? `${(item.value * 100).toFixed(2)}%` : "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function BiasRateSection({ analysis }: { analysis: TrendAnalysis }) {
  const items = [
    { label: "MA20乖离率", value: analysis.lastBias.ma20Bias },
    { label: "MA60乖离率", value: analysis.lastBias.ma60Bias },
    { label: "MA250乖离率", value: analysis.lastBias.ma250Bias },
  ]

  const biasLabel = (bias: number | null): { text: string; color: string } => {
    if (bias == null) return { text: "—", color: "text-slate-300" }
    if (bias > 0.15) return { text: "高位风险", color: "text-red-500" }
    if (bias > 0.08) return { text: "短线偏热", color: "text-amber-500" }
    if (bias > -0.05) return { text: "正常", color: "text-emerald-500" }
    if (bias > -0.10) return { text: "偏弱", color: "text-orange-400" }
    return { text: "超跌", color: "text-red-500" }
  }

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">乖离率</div>
      <div className="grid grid-cols-3 gap-2">
        {items.map((item) => {
          const labelInfo = biasLabel(item.value)
          return (
            <div key={item.label} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
              <div className="text-[10px] text-slate-400">{item.label}</div>
              <div className={`text-sm font-bold tabular-nums ${labelInfo.color}`}>{formatPct(item.value)}</div>
              <div className={`text-[10px] ${labelInfo.color}`}>{labelInfo.text}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function VolumeMetricsSection({ analysis }: { analysis: TrendAnalysis }) {
  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">成交量</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">最新量</div>
          <div className="text-sm font-bold tabular-nums text-slate-700">{formatVol(analysis.lastVolume)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">5日均量</div>
          <div className="text-sm font-bold tabular-nums text-slate-700">{formatVol(analysis.avgVolume5)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">量能比</div>
          <div className={`text-sm font-bold tabular-nums ${analysis.volumeRatio != null ? (analysis.volumeRatio >= 1.5 ? "text-emerald-500" : analysis.volumeRatio >= 1.0 ? "text-slate-700" : "text-slate-400") : "text-slate-300"}`}>
            {analysis.volumeRatio != null ? `${analysis.volumeRatio.toFixed(2)}x` : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">量能状态</div>
          <div className={`text-sm font-bold ${analysis.volumeRatio != null ? (analysis.volumeRatio >= 1.5 ? "text-emerald-500" : analysis.volumeRatio >= 1.0 ? "text-slate-700" : "text-slate-400") : "text-slate-300"}`}>
            {analysis.volumeRatio != null ? (analysis.volumeRatio >= 1.5 ? "放量" : analysis.volumeRatio >= 1.0 ? "正常" : "缩量") : "—"}
          </div>
        </div>
      </div>
    </div>
  )
}

function RSIATRSection({ analysis }: { analysis: TrendAnalysis }) {
  const rsiColor = (value: number | null): string => {
    if (value == null) return "text-slate-300"
    if (value > 80) return "text-red-500"
    if (value > 60) return "text-amber-500"
    if (value < 30 && analysis.priceAboveMa60) return "text-emerald-500"
    if (value < 30 && !analysis.priceAboveMa60) return "text-orange-500"
    return "text-slate-600"
  }
  const atrPctLabel = (pct: number): string => {
    if (pct < 0.02) return "波动较低"
    if (pct < 0.05) return "正常"
    if (pct < 0.08) return "高波动"
    return "风险很大"
  }

  const atrPctColor = (pct: number): string => {
    if (pct < 0.02) return "text-emerald-500"
    if (pct < 0.05) return "text-slate-600"
    if (pct < 0.08) return "text-amber-500"
    return "text-red-500"
  }

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">RSI / ATR 波动率</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">RSI6</div>
          <div className={`text-sm font-bold tabular-nums ${rsiColor(analysis.lastRsi6)}`}>{formatNum(analysis.lastRsi6, 1)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">RSI14</div>
          <div className={`text-sm font-bold tabular-nums ${rsiColor(analysis.lastRsi14)}`}>{formatNum(analysis.lastRsi14, 1)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">ATR14</div>
          <div className="text-sm font-bold tabular-nums text-slate-700">{formatNum(analysis.lastAtr14)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">ATR占比</div>
          <div className={`text-sm font-bold tabular-nums ${analysis.lastAtrPct != null ? atrPctColor(analysis.lastAtrPct) : "text-slate-300"}`}>
            {formatPct(analysis.lastAtrPct)}
          </div>
          <div className={`text-[10px] ${analysis.lastAtrPct != null ? atrPctColor(analysis.lastAtrPct) : "text-slate-300"}`}>
            {analysis.lastAtrPct != null ? atrPctLabel(analysis.lastAtrPct) : "—"}
          </div>
        </div>
      </div>
    </div>
  )
}

function MACDSection({ analysis }: { analysis: TrendAnalysis }) {
  const lastMacd = analysis.lastMacd
  const hasMacd = lastMacd.dif != null && lastMacd.dea != null
  const difAboveDea = hasMacd && lastMacd.dif! > lastMacd.dea!
  const difAboveZero = lastMacd.dif != null && lastMacd.dif > 0

  let macdStatus = "数据不足"
  if (hasMacd) {
    if (difAboveZero && difAboveDea) macdStatus = "DIF零轴上方，位于DEA上方"
    else if (difAboveZero && !difAboveDea) macdStatus = "DIF零轴上方，位于DEA下方"
    else if (!difAboveZero && difAboveDea) macdStatus = "DIF零轴下方，位于DEA上方"
    else macdStatus = "DIF零轴下方，位于DEA下方"
  }

  const macdStatusColor = hasMacd ? (difAboveZero ? "text-emerald-500" : "text-red-500") : "text-slate-400"

  const difColor = lastMacd.dif != null
    ? (lastMacd.dif > 0 ? "text-emerald-500" : "text-red-500")
    : "text-slate-300"

  const histColor = lastMacd.histogram != null
    ? (lastMacd.histogram > 0 ? "text-emerald-500" : "text-red-500")
    : "text-slate-300"

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">MACD 动能</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">DIF</div>
          <div className={`text-sm font-bold tabular-nums ${difColor}`}>{formatNum(lastMacd.dif)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">DEA</div>
          <div className="text-sm font-bold tabular-nums text-slate-700">{formatNum(lastMacd.dea)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">MACD柱</div>
          <div className={`text-sm font-bold tabular-nums ${histColor}`}>{formatNum(lastMacd.histogram)}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
          <div className="text-[10px] text-slate-400">状态</div>
          <div className={`text-xs font-bold ${macdStatusColor}`}>{macdStatus}</div>
        </div>
      </div>
    </div>
  )
}

function MAAlignmentSection({ analysis }: { analysis: TrendAnalysis }) {
  const items = [
    { label: "短线排列(5>10>20)", value: analysis.maShortAlignment, desc: "短线多头" },
    { label: "中期结构(20>60)", value: analysis.maMidAlignment, desc: "中期改善" },
    { label: "长期结构(60>120)", value: analysis.maLongAlignment, desc: "长期趋势" },
  ]

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-slate-700">均线排列</div>
      <div className="grid grid-cols-3 gap-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className={`flex size-5 shrink-0 items-center justify-center rounded-full ${item.value ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              {item.value ? <IconArrowUp className="size-3" /> : <IconMinus className="size-3" />}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-medium text-slate-700 truncate">{item.label}</div>
              <div className="text-[10px] text-slate-400">{item.value ? item.desc : "未确认"}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SignalCards({ signals }: { signals: SignalCard[] }) {
  if (signals.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-4 py-6 text-center text-sm text-slate-400">
        当前无明显技术信号
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {signals.map((signal) => {
        const badge = signalLevelBadge(signal.level)
        return (
          <div key={signal.id} className={`rounded-lg border p-3 ${signalLevelColor(signal.level)}`}>
            <div className="mb-2 flex items-center gap-2">
              <Badge variant={badge.variant}>{badge.label}</Badge>
              <span className="text-sm font-medium text-slate-800">{signal.label}</span>
            </div>
            <p className="mb-2 text-xs text-slate-600">{signal.description}</p>
            <div className="flex flex-wrap gap-1">
              {signal.conditions.map((cond) => (
                <span key={cond} className="rounded bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-500">{cond}</span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function InterpretationText({ analysis }: { analysis: TrendAnalysis }) {
  const parts: string[] = []

  parts.push(
    analysis.priceAboveMa20 && analysis.priceAboveMa60 && analysis.priceAboveMa250
      ? "收盘价高于MA20、MA60、MA250，属于中期多头结构。"
      : analysis.priceAboveMa20
        ? "收盘价站上MA20，但尚未完全脱离长周期压力。"
        : "收盘价位于关键均线下方，趋势偏弱。"
  )

  if (analysis.lastSlope.ma20Slope != null && analysis.lastSlope.ma60Slope != null) {
    if (analysis.lastSlope.ma20Slope > 0 && analysis.lastSlope.ma60Slope > 0) {
      parts.push("MA20和MA60均向上，趋势健康。")
    } else if (analysis.lastSlope.ma20Slope > 0 && analysis.lastSlope.ma60Slope <= 0) {
      parts.push("MA20向上但MA60走平或向下，可能是趋势初期，需要时间确认。")
    } else if (analysis.lastSlope.ma20Slope <= 0 && analysis.lastSlope.ma60Slope > 0) {
      parts.push("MA20走弱但MA60仍向上，短线调整，关注MA60支撑。")
    } else {
      parts.push("MA20和MA60均向下，趋势转弱。")
    }
  }

  if (analysis.volumeRatio != null) {
    if (analysis.volumeRatio >= 1.5) {
      parts.push(`今日成交量为5日均量的${analysis.volumeRatio.toFixed(1)}倍，放量明显。${analysis.priceAboveMa60 ? "若伴随突破关键均线，有效性较强。" : "需关注能否有效突破。"}`)
    } else if (analysis.volumeRatio >= 1.0) {
      parts.push("量能正常，没有明显的放量或缩量信号。")
    } else {
      parts.push("成交量缩小，可能处于调整或交投清淡阶段。")
    }
  }

  if (analysis.lastBias.ma20Bias != null && analysis.lastBias.ma20Bias > 0.08) {
    parts.push(`价格高于MA20约${(analysis.lastBias.ma20Bias * 100).toFixed(1)}%，短线存在回踩风险，不适合追高。`)
  }

  if (analysis.lastRsi6 != null && analysis.lastRsi6 > 80) {
    parts.push("RSI6高于80，短线情绪过热。")
  }

  if (analysis.lastRsi6 != null && analysis.lastRsi6 < 30) {
    parts.push("RSI6低于30，处于超卖区，但超跌不等于买点，需等待止跌信号。")
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-4">
      <div className="mb-2 flex items-center gap-2">
        <IconGauge className="size-4 text-slate-500" />
        <span className="text-sm font-medium text-slate-700">指标解读</span>
      </div>
      <div className="space-y-2 text-sm leading-relaxed text-slate-600">
        {parts.map((text, i) => (
          <p key={i}>{text}</p>
        ))}
      </div>
    </div>
  )
}

function KeyPriceZoneSection({ analysis }: { analysis: TrendAnalysis }) {
  const zone = analysis.keyPriceZone
  const lastClose = analysis.lastClose

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <IconTarget className="size-4 text-indigo-500" />
        <span className="text-sm font-medium text-slate-700">关键价位区</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-700">
            <IconArrowUp className="size-3" />
            支撑位
          </div>
          {zone.supports.length === 0 ? (
            <div className="text-xs text-slate-400">当前无有效支撑</div>
          ) : (
            <div className="space-y-1.5">
              {zone.supports.slice(0, 4).map((s, i) => {
                const dist = lastClose != null ? ((lastClose - s.price) / lastClose * 100) : null
                return (
                  <div key={i} className="flex items-center justify-between rounded bg-white/80 px-2 py-1">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs font-medium ${s.source === "ma" ? "text-purple-600" : "text-teal-600"}`}>{s.label}</span>
                      <span className="text-[10px] text-slate-400">{s.source === "ma" ? "均线" : "波谷"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold tabular-nums text-emerald-600">{s.price.toFixed(2)}</span>
                      {dist != null && <span className="text-[10px] text-slate-400">距{dist.toFixed(1)}%</span>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="space-y-2 rounded-lg border border-red-200 bg-red-50/60 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-red-700">
            <IconArrowUp className="size-3 rotate-180" />
            压力位
          </div>
          {zone.resistances.length === 0 ? (
            <div className="text-xs text-slate-400">当前无明确压力</div>
          ) : (
            <div className="space-y-1.5">
              {zone.resistances.slice(0, 4).map((r, i) => {
                const dist = lastClose != null ? ((r.price - lastClose) / lastClose * 100) : null
                return (
                  <div key={i} className="flex items-center justify-between rounded bg-white/80 px-2 py-1">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs font-medium ${r.source === "ma" ? "text-purple-600" : "text-orange-600"}`}>{r.label}</span>
                      <span className="text-[10px] text-slate-400">{r.source === "ma" ? "均线" : "波峰"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold tabular-nums text-red-600">{r.price.toFixed(2)}</span>
                      {dist != null && <span className="text-[10px] text-slate-400">+{dist.toFixed(1)}%</span>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {zone.stopLoss && (
        <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700">
            <IconShield className="size-3" />
            止损参考
          </div>
          <div className="flex items-center justify-between rounded bg-white/80 px-3 py-2">
            <div>
              <div className="text-sm font-bold tabular-nums text-amber-600">{zone.stopLoss.price.toFixed(2)}</div>
              <div className="text-xs text-slate-500">{zone.stopLoss.method}</div>
            </div>
            {lastClose != null && (
              <div className="text-right">
                <div className="text-xs text-slate-500">止损幅度</div>
                <div className="text-sm font-bold text-red-500">
                  {((lastClose - zone.stopLoss.price) / lastClose * 100).toFixed(2)}%
                </div>
              </div>
            )}
          </div>
          {zone.atrStop && zone.atrStop.price !== zone.stopLoss.price && (
            <div className="flex items-center justify-between rounded bg-white/60 px-3 py-2">
              <div className="text-xs text-slate-500">ATR止损参考</div>
              <span className="text-sm font-bold tabular-nums text-slate-600">{zone.atrStop.price.toFixed(2)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function BacktestSection({ analysis }: { analysis: TrendAnalysis }) {
  const bt = analysis.backtest
  if (bt.signals.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <IconHistory className="size-4 text-blue-500" />
          <span className="text-sm font-medium text-slate-700">历史信号回测</span>
        </div>
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-4 py-4 text-center text-xs text-slate-400">
          {bt.note}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <IconHistory className="size-4 text-blue-500" />
          <span className="text-sm font-medium text-slate-700">历史信号回测</span>
        </div>
        <span className="text-[10px] text-slate-400">
          {bt.dataPeriod.start} ~ {bt.dataPeriod.end} · {bt.dataPeriod.bars}根K线
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              <th className="px-2 py-1.5 text-left font-medium">信号</th>
              <th className="px-2 py-1.5 text-right font-medium">出现次数</th>
              <th className="px-2 py-1.5 text-right font-medium">胜率(20期)</th>
              <th className="px-2 py-1.5 text-right font-medium">均收益5期</th>
              <th className="px-2 py-1.5 text-right font-medium">均收益10期</th>
              <th className="px-2 py-1.5 text-right font-medium">均收益20期</th>
              <th className="px-2 py-1.5 text-right font-medium">最大收益</th>
              <th className="px-2 py-1.5 text-right font-medium">最差收益</th>
            </tr>
          </thead>
          <tbody>
            {bt.signals.map((sb) => {
              const isCurrentSignal = analysis.signals.some((s) => s.id === sb.signalId)
              return (
                <tr key={sb.signalId} className={`border-b border-slate-100 ${isCurrentSignal ? "bg-blue-50/60" : "hover:bg-slate-50"}`}>
                  <td className="px-2 py-1.5">
                    <span className="font-medium text-slate-800">{sb.signalLabel}</span>
                    {isCurrentSignal && <span className="ml-1 rounded bg-blue-500 px-1 py-0.5 text-[10px] text-white">当前</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-600">{sb.totalOccurrences}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {sb.winRate != null ? (
                      <span className={`font-medium ${sb.winRate >= 0.6 ? "text-emerald-500" : sb.winRate >= 0.45 ? "text-amber-500" : "text-red-500"}`}>
                        {(sb.winRate * 100).toFixed(0)}%
                      </span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {sb.avgReturn5 != null ? (
                      <span className={returnColorByDirection(sb.avgReturn5, sb.signalDirection)}>{formatPct(sb.avgReturn5)}</span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {sb.avgReturn10 != null ? (
                      <span className={returnColorByDirection(sb.avgReturn10, sb.signalDirection)}>{formatPct(sb.avgReturn10)}</span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {sb.avgReturn20 != null ? (
                      <span className={returnColorByDirection(sb.avgReturn20, sb.signalDirection)}>{formatPct(sb.avgReturn20)}</span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-emerald-500">
                    {sb.maxReturn20 != null ? formatPct(sb.maxReturn20) : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-red-500">
                    {sb.worstReturn20 != null ? formatPct(sb.worstReturn20) : "—"}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="space-y-1.5">
        {bt.signals.filter((sb) => sb.totalOccurrences > 0).map((sb) => (
          <div key={sb.signalId} className="flex items-center gap-2 text-xs">
            <span className="font-medium text-slate-600">{sb.signalLabel}</span>
            <span className="text-slate-400">—</span>
            <span className="text-slate-500">{sb.summary}</span>
          </div>
        ))}
      </div>

      <div className="text-[10px] text-slate-400">{bt.note}</div>
    </div>
  )
}

export function TechnicalIndicatorPanel({ bars }: { bars: StockKlineBar[] }) {
  const analysis = useMemo(() => {
    if (bars.length === 0) return null
    return analyzeTrend(bars)
  }, [bars])

  if (!analysis) {
    return (
      <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
        <CardHeader>
          <CardTitle className="text-base">技术指标</CardTitle>
          <CardDescription>请先选择股票加载K线数据</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-6 text-sm text-slate-400">
            暂无K线数据，请在上方选择股票后加载。
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">技术指标 · 趋势状态面板</CardTitle>
            <CardDescription>基于均线结构、斜率、量能、MACD等综合判断当前趋势状态</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <TrendStatusOverview analysis={analysis} />

        <div className="grid gap-4 md:grid-cols-3">
          <TechnicalScoreCard analysis={analysis} />
          <RiskScoreCard analysis={analysis} />
          <CompositeScoreCard analysis={analysis} />
        </div>

        <Separator />

        <MAPositionSection analysis={analysis} />

        <div className="grid gap-4 md:grid-cols-2">
          <MASlopeSection analysis={analysis} />
          <BiasRateSection analysis={analysis} />
        </div>

        <MAAlignmentSection analysis={analysis} />

        <VolumeMetricsSection analysis={analysis} />

        <div className="grid gap-4 md:grid-cols-2">
          <MACDSection analysis={analysis} />
          <RSIATRSection analysis={analysis} />
        </div>

        <Separator />

        <div>
          <div className="mb-3 flex items-center gap-2">
            <IconFlame className="size-4 text-amber-500" />
            <span className="text-sm font-medium text-slate-700">信号卡片</span>
          </div>
          <SignalCards signals={analysis.signals} />
        </div>

        <Separator />

        <KeyPriceZoneSection analysis={analysis} />

        <Separator />

        <BacktestSection analysis={analysis} />

        <Separator />

        <InterpretationText analysis={analysis} />
      </CardContent>
    </Card>
  )
}
