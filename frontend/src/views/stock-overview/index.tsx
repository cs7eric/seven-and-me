/**
 * Design entry:
 * - Data/API: market-overview composite response
 * - Front design: design/front/stock-overview.md
 * - Change rule: review design before edits; sync design if response structure or panel responsibilities change.
 */
import { useEffect, useMemo, useState } from "react"
import { Activity, AlertTriangle, BarChart3, CheckCircle2, LineChart, RefreshCw, ShieldAlert, Target, TrendingUp, Zap } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fetchMarketOverview } from "@/lib/api"
import { notification } from "@/components/ui/notification"
import DogLoader from "@/components/loader/dog-loader"

interface MarketLevel {
  price: number
  type: string
  source: string
  strength: number
  label: string
  distancePct: number
}

interface PriceZone {
  zoneLow: number
  zoneHigh: number
  type: "support" | "resistance"
  strength: number
  sources: string[]
  distancePct: number
  label: string
}

interface ShanghaiChartBar {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  volumeRatio: number
  turnoverProxy: number
  limitUpCount: number | null
  breakRate: number | null
}

interface WindowMetrics {
  window: number
  returnN: number | null
  highN: number | null
  lowN: number | null
  rangePosition: number | null
  drawdownFromHigh: number | null
  reboundFromLow: number | null
  volatility: number | null
  atrPct: number | null
  upDaysRatio: number | null
  volumeRatio: number | null
  amountRatio: number | null
  closeAboveMa20: boolean
  closeAboveMa60: boolean
  ma20Slope: number | null
  ma60Slope: number | null
}

interface IndustryRow {
  name: string
  indexName: string
  symbol: string
  industryQuery: string
  provider: string
  relativeReturn5: number | null
  relativeReturn20: number | null
  relativeReturn60: number | null
  state: string
  score: number
}

interface StyleRow {
  style: string
  source: string
  relativeReturn5: number | null
  relativeReturn20: number | null
  relativeReturn60: number | null
  state: string
}

interface SimilarForwardStat {
  forwardDays: number
  winRate: number
  avgReturn: number
  medianReturn: number
  maxReturn: number
  worstReturn: number
  medianMaxDrawdown: number
  positiveRatio: number
}

interface SimilarMatchDetail {
  date: string
  distance: number
  regimeBucket: string
  dominantStyle: string
  sentimentTrend: string
  rangePos60: number
  return20: number
  return60: number
}

interface MarketOverview {
  tradeDate: string
  hero: {
    regime: string
    headline: string
    overallScore: number
    attackLevel: number
    riskLevel: string
    oneSentence: string
  }
  actionPlan: {
    stance: "进攻" | "结构性参与" | "观察" | "防守"
    suitable: string[]
    avoid: string[]
    confirmationSignals: string[]
    invalidationSignals: string[]
  }
  shanghaiMap: {
    close: number
    rangeType: string
    currentZone: string
    supportZones: PriceZone[]
    resistanceZones: PriceZone[]
    nearestSupport: PriceZone | null
    nearestResistance: PriceZone | null
    chartBars: ShanghaiChartBar[]
  }
  cycleMatrix: WindowMetrics[]
  internalStructure: {
    sentiment: {
      todayScore: number
      trendScore: number
      riskDiffusionScore: number
      state: string
      trend: string
      score5: number
      score20: number
    }
    style: {
      dominantStyle: string
      dominant: StyleRow | null
      spread20: number
      rows: StyleRow[]
      conclusion: string
    }
    industry: {
      available: boolean
      leadings: IndustryRow[]
      laggings: IndustryRow[]
      strongCount: number
      weakCount: number
      conclusion: string
    }
    combinedConclusion: string
  }
  similarScenarios: {
    matchedCount: number
    medianDistance: number | null
    matchThreshold: number
    conclusion: string
    matchedDetails: SimilarMatchDetail[]
    forwardStats: SimilarForwardStat[]
  }
  summary: {
    regime: string
    overallScore: number
    shortTermState: string
    midTermState: string
    longTermState: string
    dominantStyle: string
    riskState: string
    conclusion: string
  }
  shanghai: {
    close: number
    rangeType: string
    windowMetrics: WindowMetrics[]
    supportLevels: MarketLevel[]
    resistanceLevels: MarketLevel[]
    nearestSupport: MarketLevel | null
    nearestResistance: MarketLevel | null
    ma20: number | null
    ma60: number | null
    ma120: number | null
    ma250: number | null
    cycleConclusion?: string
  }
  sentiment: MarketOverview["internalStructure"]["sentiment"]
  styles: StyleRow[]
  industries: IndustryRow[]
  similarScenarioBacktest: MarketOverview["similarScenarios"]
}

const cardChrome = "max-w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.045)]"
const panelChrome = "min-w-0 rounded-2xl border border-slate-200 bg-slate-50/70"
const ink = "text-slate-950"
const secondaryInk = "text-slate-500"

function fmtPct(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toFixed(digits)
}

function stateForWindow(item: WindowMetrics) {
  const rp = item.rangePosition
  const ret = item.returnN ?? 0
  if (rp === null) return "未知"
  if (rp > 0.82 && ret > 0) return "上沿"
  if (rp < 0.18 && ret < 0) return "下沿"
  if (ret > 0.03) return "偏强"
  if (ret < -0.03) return "偏弱"
  return "震荡"
}

function stanceTone(stance: string) {
  if (stance === "进攻") return "border-slate-300 bg-slate-950 text-white"
  if (stance === "结构性参与") return "border-slate-300 bg-slate-100 text-slate-900"
  if (stance === "防守") return "border-red-200 bg-red-50 text-red-700"
  return "border-amber-200 bg-amber-50 text-amber-700"
}

function trendTone(value: number | null | undefined) {
  const safeValue = value ?? 0
  if (safeValue > 0.01) return "text-emerald-700"
  if (safeValue < -0.01) return "text-red-700"
  return "text-slate-700"
}

function zoneRange(zone: PriceZone) {
  if (Math.abs(zone.zoneHigh - zone.zoneLow) < 0.5) return fmtNum(zone.zoneLow, 0)
  return `${fmtNum(zone.zoneLow, 0)} - ${fmtNum(zone.zoneHigh, 0)}`
}

function SectionHeader({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <CardHeader className="border-b border-slate-100 bg-white pb-5">
      <div className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">{eyebrow}</div>
        <CardTitle className={`break-words text-lg font-semibold ${ink} sm:text-xl`}>{title}</CardTitle>
        <CardDescription className={`max-w-3xl leading-6 ${secondaryInk}`}>{description}</CardDescription>
      </div>
    </CardHeader>
  )
}

function RegimeHero({ data, onRefresh, loading }: { data: MarketOverview; onRefresh: () => void; loading: boolean }) {
  return (
    <div className="max-w-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <div className="border-b border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-4 sm:p-8 xl:p-10">
        <div className="flex flex-col gap-8 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 max-w-5xl space-y-6">
            <div className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
              <LineChart className="size-3.5 text-slate-500" />
              A股市场情景驾驶舱 · {data.tradeDate}
            </div>
            <div className="space-y-4">
              <h1 className="max-w-5xl break-words text-3xl font-semibold leading-tight text-slate-950 sm:text-6xl">{data.hero.headline}</h1>
              <p className="max-w-3xl text-base leading-8 text-slate-600">{data.hero.oneSentence}</p>
            </div>
          </div>
          <div className="grid w-full gap-3 sm:grid-cols-3 xl:w-80 xl:grid-cols-1">
            <HeroStat label="综合环境分" value={String(data.hero.overallScore)} suffix="/100" progress={data.hero.overallScore} />
            <HeroStat label="进攻等级" value={String(data.hero.attackLevel)} suffix="/5" />
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs text-slate-500">风险等级</div>
              <div className="mt-2 text-2xl font-semibold tracking-[-0.035em] text-slate-950">{data.hero.riskLevel}</div>
              <Button className="mt-4 w-full rounded-xl bg-slate-950 text-white hover:bg-slate-800" size="sm" onClick={onRefresh} disabled={loading}>
                <RefreshCw className={`mr-2 size-4 ${loading ? "animate-spin" : ""}`} />
                刷新判断
              </Button>
            </div>
          </div>
        </div>
      </div>
      <div className="grid gap-px bg-slate-100 sm:grid-cols-3">
        <HeroMini label="最近压力" value={data.shanghaiMap.nearestResistance?.label ?? "暂无明确压力区"} tone="danger" />
        <HeroMini label="最近支撑" value={data.shanghaiMap.nearestSupport?.label ?? "暂无明确支撑区"} tone="success" />
        <HeroMini label="主导风格" value={data.summary.dominantStyle} tone="neutral" />
      </div>
    </div>
  )
}

function HeroStat({ label, value, suffix, progress }: { label: string; value: string; suffix: string; progress?: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between text-xs text-slate-500"><span>{label}</span><span>{value}{suffix}</span></div>
      <div className="mt-2 flex items-end gap-2"><span className="text-4xl font-semibold tracking-[-0.055em] text-slate-950">{value}</span><span className="pb-1 text-sm text-slate-400">{suffix}</span></div>
      {progress !== undefined ? <Progress value={progress} className="mt-4 h-1.5 bg-slate-100 [&_[data-slot=progress-indicator]]:bg-slate-900" /> : null}
    </div>
  )
}

function HeroMini({ label, value, tone }: { label: string; value: string; tone: "danger" | "success" | "neutral" }) {
  const toneClass = tone === "danger" ? "text-red-700" : tone === "success" ? "text-emerald-700" : "text-slate-800"
  return (
    <div className="bg-white p-5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</div>
      <div className={`mt-2 line-clamp-2 text-sm font-medium leading-6 ${toneClass}`}>{value}</div>
    </div>
  )
}

function ActionPlanCard({ data }: { data: MarketOverview }) {
  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="Playbook" title="今日行动剧本" description="把情景判断翻译成适合、回避、确认和失效信号。" />
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs text-slate-500">当前策略姿态</div>
            <div className="mt-1 text-2xl font-semibold tracking-[-0.035em] text-slate-950">{data.actionPlan.stance}</div>
          </div>
          <Badge className={`w-fit rounded-full px-3 py-1 ${stanceTone(data.actionPlan.stance)}`} variant="outline">进攻 {data.hero.attackLevel}/5</Badge>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <SignalList icon={CheckCircle2} title="适合" items={data.actionPlan.suitable} tone="success" />
          <SignalList icon={AlertTriangle} title="不适合" items={data.actionPlan.avoid} tone="danger" />
          <SignalList icon={Target} title="确认信号" items={data.actionPlan.confirmationSignals} tone="neutral" />
          <SignalList icon={ShieldAlert} title="失效信号" items={data.actionPlan.invalidationSignals} tone="warning" />
        </div>
      </CardContent>
    </Card>
  )
}

function SignalList({ icon: Icon, title, items, tone }: { icon: typeof CheckCircle2; title: string; items: string[]; tone: "success" | "danger" | "neutral" | "warning" }) {
  const toneMap = {
    success: "border-l-emerald-500",
    danger: "border-l-red-500",
    neutral: "border-l-slate-500",
    warning: "border-l-amber-500",
  }
  const iconTone = {
    success: "text-emerald-700",
    danger: "text-red-700",
    neutral: "text-slate-700",
    warning: "text-amber-700",
  }
  return (
    <div className={`rounded-2xl border border-slate-200 border-l-4 bg-white p-4 ${toneMap[tone]}`}>
      <div className={`mb-3 flex items-center gap-2 text-sm font-semibold ${iconTone[tone]}`}><Icon className="size-4" />{title}</div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item} className="break-words rounded-xl bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">{item}</div>
        ))}
      </div>
    </div>
  )
}

function clampPct(value: number) {
  return Math.max(0, Math.min(100, value))
}

function priceToY(price: number, min: number, max: number) {
  if (max === min) return 50
  return clampPct(((max - price) / (max - min)) * 100)
}

function zoneDisplayName(zone: PriceZone) {
  return zone.sources.slice(0, 2).join(" / ") || zone.label
}

function formatDate(value: number) {
  if (!value) return "—"
  const date = new Date(value)
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
}

function strengthAlpha(strength: number) {
  return Math.max(0.12, Math.min(0.42, strength / 240))
}

function ShanghaiZoneMap({ data }: { data: MarketOverview }) {
  const bars = data.shanghaiMap.chartBars.slice(-90)
  const resistances = data.shanghaiMap.resistanceZones.slice(0, 5)
  const supports = data.shanghaiMap.supportZones.slice(0, 5)
  const zones = [...resistances, ...supports]
  const close = data.shanghaiMap.close
  const priceValues = [
    close,
    ...bars.flatMap((bar) => [bar.high, bar.low]),
    ...zones.flatMap((zone) => [zone.zoneLow, zone.zoneHigh]),
  ]
  const rawMin = Math.min(...priceValues)
  const rawMax = Math.max(...priceValues)
  const padding = Math.max((rawMax - rawMin) * 0.08, close * 0.008, 8)
  const min = rawMin - padding
  const max = rawMax + padding
  const ticks = [max, max - (max - min) * 0.25, max - (max - min) * 0.5, max - (max - min) * 0.75, min]
  const maxVolume = Math.max(...bars.map((bar) => bar.volume), 1)
  const maxAmount = Math.max(...bars.map((bar) => bar.amount), 1)
  const latest = bars[bars.length - 1]
  const plotLeft = 64
  const plotRight = 18
  const chartWidth = 920
  const candleHeight = 360
  const volumeHeight = 112
  const innerWidth = chartWidth - plotLeft - plotRight
  const gap = bars.length > 0 ? innerWidth / bars.length : innerWidth
  const candleWidth = Math.max(3, Math.min(9, gap * 0.55))

  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="K-Line Zone POC" title="上证 K 线区间图" description="把压力/支撑直接叠加到 K 线上：颜色深浅代表区间权重，下方同步观察成交量、成交额代理换手强度和涨停情绪。" />
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 md:grid-cols-4">
          <ZoneSummaryCard label="最近压力" zone={data.shanghaiMap.nearestResistance} tone="danger" />
          <ZoneSummaryCard label="最近支撑" zone={data.shanghaiMap.nearestSupport} tone="success" />
          <MetricTile label="最新量能" value={latest ? fmtPct(latest.volumeRatio) : "—"} />
          <MetricTile label="涨停 / 炸板" value={latest ? `${latest.limitUpCount ?? 0} / ${fmtNum(latest.breakRate, 0)}%` : "—"} />
        </div>

        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <svg viewBox={`0 0 ${chartWidth} 560`} className="min-w-[860px]">
            <rect x="0" y="0" width={chartWidth} height="560" rx="14" fill="#f8fafc" />
            <rect x={plotLeft} y="24" width={innerWidth} height={candleHeight} fill="#ffffff" stroke="#e2e8f0" />
            <rect x={plotLeft} y="410" width={innerWidth} height={volumeHeight} fill="#ffffff" stroke="#e2e8f0" />

            {ticks.map((tick) => {
              const y = 24 + (priceToY(tick, min, max) / 100) * candleHeight
              return (
                <g key={tick}>
                  <line x1={plotLeft} x2={chartWidth - plotRight} y1={y} y2={y} stroke="#e2e8f0" strokeDasharray="4 4" />
                  <text x={plotLeft - 10} y={y + 4} textAnchor="end" fontSize="11" fill="#64748b">{fmtNum(tick, 0)}</text>
                </g>
              )
            })}

            {zones.map((zone) => (
              <KLineZoneBand key={`${zone.type}-${zone.label}`} zone={zone} min={min} max={max} plotLeft={plotLeft} plotWidth={innerWidth} chartTop={24} chartHeight={candleHeight} />
            ))}

            {bars.map((bar, index) => {
              const x = plotLeft + index * gap + gap / 2
              const openY = 24 + (priceToY(bar.open, min, max) / 100) * candleHeight
              const closeY = 24 + (priceToY(bar.close, min, max) / 100) * candleHeight
              const highY = 24 + (priceToY(bar.high, min, max) / 100) * candleHeight
              const lowY = 24 + (priceToY(bar.low, min, max) / 100) * candleHeight
              const up = bar.close >= bar.open
              const color = up ? "#b91c1c" : "#047857"
              const bodyY = Math.min(openY, closeY)
              const bodyHeight = Math.max(1, Math.abs(closeY - openY))
              const volumeBarHeight = Math.max(1, (bar.volume / maxVolume) * (volumeHeight - 18))
              const amountLineY = 410 + volumeHeight - 10 - (bar.amount / maxAmount) * (volumeHeight - 22)
              const showDate = index === 0 || index === bars.length - 1 || index % 22 === 0

              return (
                <g key={bar.timestamp}>
                  <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeWidth="1" />
                  <rect x={x - candleWidth / 2} y={bodyY} width={candleWidth} height={bodyHeight} fill={up ? "#fee2e2" : "#dcfce7"} stroke={color} strokeWidth="1" />
                  <rect x={x - candleWidth / 2} y={410 + volumeHeight - volumeBarHeight - 8} width={candleWidth} height={volumeBarHeight} fill={up ? "#fecaca" : "#bbf7d0"} opacity="0.9" />
                  <circle cx={x} cy={amountLineY} r="1.5" fill="#334155" opacity="0.7" />
                  {showDate ? <text x={x} y="546" textAnchor="middle" fontSize="10" fill="#94a3b8">{formatDate(bar.timestamp)}</text> : null}
                </g>
              )
            })}

            {bars.length > 1 ? (
              <polyline
                fill="none"
                stroke="#334155"
                strokeWidth="1"
                opacity="0.65"
                points={bars.map((bar, index) => {
                  const x = plotLeft + index * gap + gap / 2
                  const y = 410 + volumeHeight - 10 - (bar.amount / maxAmount) * (volumeHeight - 22)
                  return `${x},${y}`
                }).join(" ")}
              />
            ) : null}

            <line x1={plotLeft} x2={chartWidth - plotRight} y1={24 + (priceToY(close, min, max) / 100) * candleHeight} y2={24 + (priceToY(close, min, max) / 100) * candleHeight} stroke="#0f172a" strokeWidth="1" />
            <text x={chartWidth - plotRight - 4} y={24 + (priceToY(close, min, max) / 100) * candleHeight - 6} textAnchor="end" fontSize="11" fontWeight="600" fill="#0f172a">当前 {fmtNum(close)}</text>

            <text x={plotLeft} y="404" fontSize="11" fill="#64748b">成交量柱 / 成交额代理换手强度线</text>
            <text x={plotLeft} y="538" fontSize="11" fill="#64748b">红K上涨，绿K下跌；压力/支撑区间颜色越深，代表聚类权重越高。</text>
          </svg>
        </div>
      </CardContent>
    </Card>
  )
}

function ZoneSummaryCard({ label, zone, tone }: { label: string; zone: PriceZone | null; tone: "danger" | "success" }) {
  const toneClass = tone === "danger" ? "text-red-700" : "text-emerald-700"
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 text-2xl font-semibold tracking-[-0.045em] ${toneClass}`}>{zone ? zoneRange(zone) : "—"}</div>
      <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{zone ? zoneDisplayName(zone) : "暂无明确区间"}</div>
    </div>
  )
}

function KLineZoneBand({ zone, min, max, plotLeft, plotWidth, chartTop, chartHeight }: { zone: PriceZone; min: number; max: number; plotLeft: number; plotWidth: number; chartTop: number; chartHeight: number }) {
  const top = chartTop + (priceToY(zone.zoneHigh, min, max) / 100) * chartHeight
  const bottom = chartTop + (priceToY(zone.zoneLow, min, max) / 100) * chartHeight
  const height = Math.max(bottom - top, 5)
  const isResistance = zone.type === "resistance"
  const alpha = strengthAlpha(zone.strength)
  const fill = isResistance ? `rgba(248,113,113,${alpha})` : `rgba(52,211,153,${alpha})`
  const stroke = isResistance ? "#ef4444" : "#10b981"
  const labelY = top + Math.max(12, Math.min(height / 2 + 4, height - 4))

  return (
    <g>
      <rect x={plotLeft} y={top} width={plotWidth} height={height} fill={fill} stroke={stroke} strokeOpacity="0.35" />
      <text x={plotLeft + 8} y={labelY} fontSize="11" fontWeight="600" fill={isResistance ? "#991b1b" : "#047857"}>{zoneRange(zone)}</text>
      <text x={plotLeft + 92} y={labelY} fontSize="10" fill="#475569">{zoneDisplayName(zone)}</text>
      <text x={plotLeft + plotWidth - 8} y={labelY} textAnchor="end" fontSize="10" fill="#475569">权重 {zone.strength}</text>
    </g>
  )
}

function CycleMatrix({ data }: { data: MarketOverview }) {
  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="Cycle Matrix" title="多周期结构矩阵" description={data.shanghai.cycleConclusion ?? "短、中、长周期结构对照。"} />
      <CardContent className="p-5">
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <Table className="min-w-[640px]">
            <TableHeader className="bg-slate-50">
              <TableRow className="hover:bg-transparent">
                <TableHead className="font-semibold text-slate-500">周期</TableHead>
                <TableHead className="font-semibold text-slate-500">涨跌幅</TableHead>
                <TableHead className="font-semibold text-slate-500">区间位置</TableHead>
                <TableHead className="font-semibold text-slate-500">距高点</TableHead>
                <TableHead className="font-semibold text-slate-500">状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.cycleMatrix.map((item) => (
                <TableRow key={item.window} className="border-slate-100 hover:bg-slate-50/70">
                  <TableCell className="font-semibold text-slate-800">{item.window}日</TableCell>
                  <TableCell className={`font-medium ${trendTone(item.returnN)}`}>{fmtPct(item.returnN)}</TableCell>
                  <TableCell><div className="flex min-w-32 items-center gap-3"><Progress value={(item.rangePosition ?? 0) * 100} className="h-1.5 bg-slate-100 [&_[data-slot=progress-indicator]]:bg-slate-800" /><span className="w-12 text-xs text-slate-500">{fmtPct(item.rangePosition, 0)}</span></div></TableCell>
                  <TableCell className="text-slate-500">{fmtPct(item.drawdownFromHigh)}</TableCell>
                  <TableCell><Badge className="rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{stateForWindow(item)}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function InternalStructurePanel({ data }: { data: MarketOverview }) {
  const sentiment = data.internalStructure.sentiment
  const style = data.internalStructure.style
  const industry = data.internalStructure.industry
  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="Market Internals" title="情绪 / 风格 / 行业三联动" description={data.internalStructure.combinedConclusion} />
      <CardContent className="grid gap-4 p-4 sm:p-5 xl:grid-cols-3">
        <StructureCard icon={Activity} title="市场情绪" value={String(Math.round(sentiment.todayScore))} tone="neutral" lines={[`5日趋势：${sentiment.trend}`, `风险扩散：${fmtNum(sentiment.riskDiffusionScore, 0)}`, `5日 / 20日：${fmtNum(sentiment.score5, 0)} / ${fmtNum(sentiment.score20, 0)}`]} />
        <StructureCard icon={Zap} title="主导风格" value={style.dominantStyle} tone="neutral" lines={[style.conclusion, `20日风格分化：${fmtPct(style.spread20)}`, `状态：${style.dominant?.state ?? "均衡"}`]} />
        <StructureCard icon={BarChart3} title="行业主线" value={industry.available ? `${industry.strongCount} 强` : "未接入"} tone="neutral" lines={[industry.conclusion, `弱势行业：${industry.weakCount}`, industry.available ? industry.leadings.map((item) => item.name).slice(0, 3).join(" / ") : "不使用风格数据冒充行业"]} />
      </CardContent>
    </Card>
  )
}

function StructureCard({ icon: Icon, title, value, lines }: { icon: typeof Activity; title: string; value: string; lines: string[]; tone: "neutral" }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Icon className="size-4 text-slate-500" />{title}</div>
        <Badge className="rounded-full border-slate-200 bg-white px-3 py-1 text-slate-700" variant="outline">{value}</Badge>
      </div>
      <div className="mt-5 space-y-2 text-sm leading-6 text-slate-600">
        {lines.map((line) => <div key={line} className="break-words rounded-xl border border-slate-200 bg-white px-3 py-2">{line}</div>)}
      </div>
    </div>
  )
}

function SimilarScenarioPanel({ data }: { data: MarketOverview }) {
  const stat20 = data.similarScenarios.forwardStats.find((item) => item.forwardDays === 20) ?? data.similarScenarios.forwardStats[0]
  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="Historical Context" title="历史相似市场" description={data.similarScenarios.conclusion} />
      <CardContent className="space-y-5 p-5">
        <div className="grid gap-3 md:grid-cols-4">
          <MetricTile label="相似样本" value={String(data.similarScenarios.matchedCount)} />
          <MetricTile label="中位距离" value={fmtNum(data.similarScenarios.medianDistance)} />
          <MetricTile label="20日上涨概率" value={fmtPct(stat20?.winRate)} />
          <MetricTile label="20日平均收益" value={fmtPct(stat20?.avgReturn)} />
        </div>
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <Table className="min-w-[620px]">
            <TableHeader className="bg-slate-50">
              <TableRow className="hover:bg-transparent">
                <TableHead className="font-semibold text-slate-500">后续</TableHead>
                <TableHead className="font-semibold text-slate-500">上涨概率</TableHead>
                <TableHead className="font-semibold text-slate-500">平均收益</TableHead>
                <TableHead className="font-semibold text-slate-500">中位回撤</TableHead>
                <TableHead className="font-semibold text-slate-500">结论</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.similarScenarios.forwardStats.map((item) => (
                <TableRow key={item.forwardDays} className="border-slate-100 hover:bg-slate-50/70">
                  <TableCell className="font-semibold text-slate-800">{item.forwardDays}日</TableCell>
                  <TableCell className="text-slate-600">{fmtPct(item.winRate)}</TableCell>
                  <TableCell className={trendTone(item.avgReturn)}>{fmtPct(item.avgReturn)}</TableCell>
                  <TableCell className="text-red-700">{fmtPct(item.medianMaxDrawdown)}</TableCell>
                  <TableCell><Badge className="rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{item.winRate >= 0.6 ? "偏正" : item.winRate >= 0.48 ? "震荡" : "偏谨慎"}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-3 break-words text-2xl font-semibold text-slate-950 sm:text-3xl">{value}</div>
    </div>
  )
}

function IndustryLeadership({ data }: { data: MarketOverview }) {
  const industry = data.internalStructure.industry
  if (!industry.available) {
    return (
      <Card className={cardChrome}>
        <SectionHeader eyebrow="Industry" title="行业主线" description={industry.conclusion} />
      </Card>
    )
  }
  return (
    <Card className={cardChrome}>
      <SectionHeader eyebrow="Leadership" title="强弱行业排行" description="基于真实行业指数相对上证表现，不再用风格数据代替行业。" />
      <CardContent className="grid gap-5 p-4 sm:p-5 xl:grid-cols-2">
        <IndustryList title="强势行业" icon={TrendingUp} items={industry.leadings} tone="success" />
        <IndustryList title="弱势行业" icon={ShieldAlert} items={industry.laggings} tone="danger" />
      </CardContent>
    </Card>
  )
}

function IndustryList({ title, icon: Icon, items, tone }: { title: string; icon: typeof TrendingUp; items: IndustryRow[]; tone: "success" | "danger" }) {
  const isStrong = tone === "success"
  return (
    <div className={`${panelChrome} p-4`}>
      <div className={`mb-4 flex items-center gap-2 text-sm font-semibold ${isStrong ? "text-emerald-700" : "text-red-700"}`}><Icon className="size-4" />{title}</div>
      <div className="space-y-3">
        {items.map((item, index) => (
          <div key={`${title}-${item.symbol}-${item.name}`} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-xs font-semibold text-slate-600">{index + 1}</div>
                <div>
                  <div className="break-words font-semibold text-slate-900">{item.name}</div>
                  <div className="mt-1 text-xs text-slate-400">{item.indexName} · {item.symbol}</div>
                </div>
              </div>
              <Badge className={`w-fit rounded-full ${isStrong ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`} variant="outline">{item.state}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
              <IndustryStat label="5日" value={fmtPct(item.relativeReturn5)} valueClass={trendTone(item.relativeReturn5)} />
              <IndustryStat label="20日" value={fmtPct(item.relativeReturn20)} valueClass={trendTone(item.relativeReturn20)} />
              <IndustryStat label="60日" value={fmtPct(item.relativeReturn60)} valueClass={trendTone(item.relativeReturn60)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function IndustryStat({ label, value, valueClass }: { label: string; value: string; valueClass: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-2 py-2">
      <div className="text-slate-400">{label}</div>
      <div className={`mt-1 font-semibold ${valueClass}`}>{value}</div>
    </div>
  )
}

export default function StockOverviewPage() {
  const [data, setData] = useState<MarketOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await fetchMarketOverview()
      setData(result as unknown as MarketOverview)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载市场概览失败"
      setError(msg)
      notification.danger({ title: "加载市场概览失败", description: msg })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  const hasData = useMemo(() => Boolean(data), [data])

  return (
    <WorkspaceShell sectionLabel="Market Regime" pageTitle="市场情景驾驶舱">
      <div className="relative -mx-2 -my-4 max-w-full overflow-hidden rounded-3xl border border-slate-200 bg-[#f6f7f9] p-2 sm:p-5 xl:p-6">
        <div className="relative space-y-6">
          {error ? (
            <Alert variant="destructive" className="rounded-2xl border-red-200 bg-red-50">
              <ShieldAlert className="size-4" />
              <AlertTitle>加载失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {!hasData && !error ? (
            <DogLoader overlay size={25} label="正在生成市场情景判断..." />
          ) : null}

          {data ? (
            <>
              <RegimeHero data={data} onRefresh={() => void load()} loading={loading} />
              <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
                <ShanghaiZoneMap data={data} />
                <ActionPlanCard data={data} />
              </div>
              <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
                <CycleMatrix data={data} />
                <SimilarScenarioPanel data={data} />
              </div>
              <InternalStructurePanel data={data} />
              <IndustryLeadership data={data} />
            </>
          ) : null}
        </div>
      </div>
    </WorkspaceShell>
  )
}
