import { Bar, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, XAxis, YAxis } from "recharts"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import type { StockAuctionPhaseSnapshot, StockAuctionPoint, StockAuctionSnapshot } from "../lib/types"

const PRICE_AXIS_COLOR = "#dc2626"
const MATCHED_VOLUME_COLOR = "#facc15"
const BUY_UNMATCHED_COLOR = "#dc2626"
const SELL_UNMATCHED_COLOR = "#16a34a"
const DELTA_LINE_COLOR = "#2563eb"
const ANCHOR_COLOR = "#f59e0b"
const PANEL_GRID_COLOR = "#cbd5e1"
const PANEL_AXIS_COLOR = "#475569"
const CROSSHAIR_COLOR = "#64748b"
const TOOLTIP_CLASSNAME = "border-slate-300 bg-white text-slate-900 shadow-2xl [&_*]:text-slate-900"

const priceChartConfig = {
  buyPrice: {
    label: "买方主导价线",
    color: BUY_UNMATCHED_COLOR,
  },
  sellPrice: {
    label: "卖方主导价线",
    color: SELL_UNMATCHED_COLOR,
  },
  matchedVolume: {
    label: "匹配量",
    color: MATCHED_VOLUME_COLOR,
  },
  anchorMarker: {
    label: "锚点",
    color: ANCHOR_COLOR,
  },
} satisfies ChartConfig

const unmatchedChartConfig = {
  buyUnmatched: {
    label: "未匹配买量",
    color: BUY_UNMATCHED_COLOR,
  },
  sellUnmatched: {
    label: "未匹配卖量",
    color: SELL_UNMATCHED_COLOR,
  },
  imbalanceDelta: {
    label: "买卖差额线",
    color: DELTA_LINE_COLOR,
  },
} satisfies ChartConfig

function formatPercent(value?: number) {
  return typeof value === "number" ? `${value}%` : "--"
}

function formatRatio(value?: number) {
  return typeof value === "number" ? value.toFixed(4) : "--"
}

function formatNumber(value?: number | null) {
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "--"
}

function formatSignedNumber(value?: number | null, digits = 3) {
  if (typeof value !== "number") return "--"
  const text = value.toFixed(digits)
  return value > 0 ? `+${text}` : text
}

function formatAmount(value?: number) {
  return typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : "--"
}

function formatShortTime(value?: string) {
  if (!value) return "--"
  return value.slice(0, 5)
}

function getRiseFallBadgeClass(value?: number) {
  if (typeof value !== "number") {
    return "border-border bg-background text-foreground"
  }
  if (value > 0) {
    return "border-red-200 bg-red-50 text-red-600"
  }
  if (value < 0) {
    return "border-emerald-200 bg-emerald-50 text-emerald-600"
  }
  return "border-slate-200 bg-slate-50 text-slate-600"
}

function getStrengthBadgeClass(label?: string) {
  if (!label) {
    return "border-border bg-background text-foreground"
  }
  if (label.includes("高开") || label.includes("强") || label.includes("抢筹")) {
    return "border-red-200 bg-red-50 text-red-600"
  }
  if (label.includes("低开") || label.includes("弱") || label.includes("抛压")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-600"
  }
  return "border-slate-200 bg-slate-50 text-slate-600"
}

function getConfidenceTone(label?: string) {
  if (label === "高") return "default" as const
  if (label === "中") return "secondary" as const
  if (label === "低") return "destructive" as const
  return "outline" as const
}

function hasDirectionData(phase?: StockAuctionPhaseSnapshot) {
  return (phase?.unmatchedBuyVolume ?? 0) > 0 || (phase?.unmatchedSellVolume ?? 0) > 0
}

function calcBuySellProgress(phase?: StockAuctionPhaseSnapshot) {
  if (!hasDirectionData(phase)) return null
  const buy = phase?.unmatchedBuyVolume ?? 0
  const sell = phase?.unmatchedSellVolume ?? 0
  const total = buy + sell
  if (total <= 0) return null
  return Math.round((buy / total) * 100)
}

function calcAuctionVolumeProgress(phase?: StockAuctionPhaseSnapshot) {
  const ratio = phase?.auctionVolumeRatio ?? 0
  return Math.max(0, Math.min(100, ratio * 100))
}

function getAnchorBadge(phase?: StockAuctionPhaseSnapshot) {
  if (!phase?.anchorTargetTime) {
    return { variant: "outline" as const, text: "锚点未知" }
  }
  if (phase.anchorExact) {
    return { variant: "default" as const, text: `${phase.anchorTargetTime} 精确` }
  }
  return { variant: "secondary" as const, text: `${phase.anchorTargetTime} 近似` }
}

function getDirectionText(point: StockAuctionPoint) {
  if ((point.unmatched_direction_raw ?? 0) > 0) return "买方占优"
  if ((point.unmatched_direction_raw ?? 0) < 0) return "卖方占优"
  return "方向未知"
}

function calcRangePriceTrend(points: StockAuctionPoint[], startTime: string, endTime: string) {
  const rangePoints = points.filter((point) => point.time_label >= startTime && point.time_label <= endTime && typeof point.price === "number")
  if (rangePoints.length < 2) {
    return { trend: "--", change: null as number | null }
  }

  const firstPrice = rangePoints[0]?.price
  const lastPrice = rangePoints[rangePoints.length - 1]?.price
  if (typeof firstPrice !== "number" || typeof lastPrice !== "number") {
    return { trend: "--", change: null as number | null }
  }

  const change = Number((lastPrice - firstPrice).toFixed(3))
  const trend = change > 0 ? "上行" : change < 0 ? "下行" : "走平"
  return { trend, change }
}

function getSplitTrendMetrics(title: string, points: StockAuctionPoint[]) {
  if (title.includes("早盘")) {
    return [
      {
        label: "09:15-09:20 价格趋势",
        ...calcRangePriceTrend(points, "09:15:00", "09:20:00"),
      },
      {
        label: "09:20-09:25 价格趋势",
        ...calcRangePriceTrend(points, "09:20:00", "09:25:00"),
      },
    ]
  }

  return [
    {
      label: "14:57-14:59 价格趋势",
      ...calcRangePriceTrend(points, "14:57:00", "14:59:00"),
    },
    {
      label: "14:59-15:00 价格趋势",
      ...calcRangePriceTrend(points, "14:59:00", "15:00:00"),
    },
  ]
}

function getInitialAuctionSnapshot(points: StockAuctionPoint[]) {
  const firstPoint = points.find((point) => typeof point.matched_volume === "number" || typeof point.unmatched_volume === "number")
  if (!firstPoint) {
    return null
  }

  return {
    time: firstPoint.time_label,
    matchedVolume: Number(firstPoint.matched_volume ?? 0),
    unmatchedVolume: Number(firstPoint.unmatched_volume ?? 0),
    directionText: getDirectionText(firstPoint),
  }
}

function MetricCard({ label, value, subValue }: { label: string; value: string; subValue?: string }) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/70 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold text-foreground">{value}</div>
      {subValue ? <div className="mt-1 text-xs text-muted-foreground">{subValue}</div> : null}
    </div>
  )
}

function DetailTimeline({ title, points }: { title: string; points: StockAuctionPoint[] }) {
  const latest = points.slice(-8).reverse()

  return (
    <div className="space-y-3 rounded-xl border border-border/60 bg-background/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <Badge variant="outline">{points.length} 条</Badge>
      </div>
      <div className="space-y-2">
        {latest.length ? latest.map((point) => (
          <div key={`${title}-${point.time_label}`} className="grid grid-cols-5 gap-2 rounded-lg border border-border/50 px-3 py-2 text-xs">
            <div>
              <div className="text-muted-foreground">时间</div>
              <div className="font-medium text-foreground">{point.time_label}</div>
            </div>
            <div>
              <div className="text-muted-foreground">价格</div>
              <div className="font-medium text-foreground">{point.price ?? "--"}</div>
            </div>
            <div>
              <div className="text-muted-foreground">虚拟成交量</div>
              <div className="font-medium text-foreground">{formatNumber(point.matched_volume)}</div>
            </div>
            <div>
              <div className="text-muted-foreground">未匹配量</div>
              <div className="font-medium text-foreground">{formatNumber(point.unmatched_volume)}</div>
            </div>
            <div>
              <div className="text-muted-foreground">委托方向</div>
              <div className="font-medium text-foreground">{getDirectionText(point)}</div>
            </div>
          </div>
        )) : <div className="text-xs text-muted-foreground">暂无竞价明细</div>}
      </div>
    </div>
  )
}

type AuctionChartDatum = {
  time: string
  price: number | null
  buyPrice: number | null
  sellPrice: number | null
  matchedVolume: number
  buyUnmatched: number
  sellUnmatched: number
  buyUnmatchedAbs: number
  sellUnmatchedAbs: number
  imbalanceDelta: number
  isAnchor: boolean
}

function buildAuctionChartData(points: StockAuctionPoint[], phase?: StockAuctionPhaseSnapshot): AuctionChartDatum[] {
  return points.map((point, index) => {
    const price = typeof point.price === "number" ? Number(point.price.toFixed(3)) : null
    const unmatchedVolume = Number(point.unmatched_volume ?? 0)
    const direction = Number(point.unmatched_direction_raw ?? 0)
    const previousDirection = index > 0 ? Number(points[index - 1]?.unmatched_direction_raw ?? 0) : direction
    const nextDirection = index < points.length - 1 ? Number(points[index + 1]?.unmatched_direction_raw ?? 0) : direction
    const buyUnmatched = direction > 0 ? unmatchedVolume : 0
    const sellUnmatchedAbs = direction < 0 ? unmatchedVolume : 0
    const shouldPaintBuy = direction > 0 || (direction === 0 && (previousDirection > 0 || nextDirection > 0))
    const shouldPaintSell = direction < 0 || (direction === 0 && (previousDirection < 0 || nextDirection < 0))

    return {
      time: point.time_label,
      price,
      buyPrice: shouldPaintBuy ? price : null,
      sellPrice: shouldPaintSell ? price : null,
      matchedVolume: Number(point.matched_volume ?? 0),
      buyUnmatched,
      sellUnmatched: sellUnmatchedAbs > 0 ? -sellUnmatchedAbs : 0,
      buyUnmatchedAbs: buyUnmatched,
      sellUnmatchedAbs,
      imbalanceDelta: buyUnmatched - sellUnmatchedAbs,
      isAnchor: phase?.time === point.time_label,
    }
  })
}

function TdxLegend() {
  return (
    <div className="grid gap-2 rounded-lg border border-slate-300 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-4">
      <div className="flex items-center gap-2">
        <span className="h-0.5 w-5 rounded" style={{ backgroundColor: BUY_UNMATCHED_COLOR }} />
        <span>红线：买方主导价线</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="h-0.5 w-5 rounded" style={{ backgroundColor: SELL_UNMATCHED_COLOR }} />
        <span>绿线：卖方主导价线</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="h-2 w-5 rounded" style={{ backgroundColor: MATCHED_VOLUME_COLOR }} />
        <span>黄柱：匹配量</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="h-2 w-5 rounded" style={{ backgroundColor: BUY_UNMATCHED_COLOR }} />
        <span>红/绿柱：未匹配买卖量</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="h-0.5 w-5 rounded" style={{ backgroundColor: DELTA_LINE_COLOR }} />
        <span>蓝线：买卖差额线</span>
      </div>
    </div>
  )
}

function PriceVolumeChart({
  data,
  phase,
  dividerTime,
  syncId,
}: {
  data: AuctionChartDatum[]
  phase?: StockAuctionPhaseSnapshot
  dividerTime?: string
  syncId: string
}) {
  const anchorPoint = data.find((point) => point.isAnchor)
  const targetTime = phase?.anchorTargetTime
  const showTargetLine = Boolean(targetTime && data.some((point) => point.time === targetTime))
  const showDividerLine = Boolean(dividerTime && data.some((point) => point.time === dividerTime))

  return (
    <ChartContainer config={priceChartConfig} className="h-[228px] w-full rounded-none border-b border-slate-300">
      <ComposedChart syncId={syncId} data={data} margin={{ left: 6, right: 6, top: 10, bottom: 0 }}>
        <CartesianGrid vertical={true} strokeDasharray="2 2" stroke={PANEL_GRID_COLOR} />
        <XAxis
          dataKey="time"
          tickLine={false}
          axisLine={false}
          tickFormatter={formatShortTime}
          interval="preserveStartEnd"
          minTickGap={20}
          height={24}
          tick={{ fill: "transparent", fontSize: 11 }}
        />
        <YAxis
          yAxisId="price"
          orientation="left"
          tickLine={false}
          axisLine={false}
          domain={["dataMin - 0.01", "dataMax + 0.01"]}
          width={48}
          tickFormatter={(value: number) => value.toFixed(2)}
          tick={{ fill: PRICE_AXIS_COLOR, fontSize: 11 }}
        />
        <YAxis
          yAxisId="volume"
          orientation="right"
          tickLine={false}
          axisLine={false}
          width={56}
          domain={[0, "dataMax + 1"]}
          tickFormatter={(value: number) => formatNumber(value)}
          tick={{ fill: PANEL_AXIS_COLOR, fontSize: 11 }}
        />

        {showDividerLine ? (
          <ReferenceLine
            x={dividerTime}
            stroke={PANEL_AXIS_COLOR}
            strokeDasharray="3 3"
            ifOverflow="extendDomain"
            label={{ value: `${formatShortTime(dividerTime)} 分界`, position: "insideBottomRight", fill: PANEL_AXIS_COLOR, fontSize: 11 }}
          />
        ) : null}
        {showTargetLine ? (
          <ReferenceLine
            x={targetTime}
            stroke={MATCHED_VOLUME_COLOR}
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
            label={{ value: `${formatShortTime(targetTime)} 定价`, position: "insideTopRight", fill: MATCHED_VOLUME_COLOR, fontSize: 11 }}
          />
        ) : null}
        {anchorPoint ? (
          <ReferenceLine
            x={anchorPoint.time}
            stroke={ANCHOR_COLOR}
            strokeDasharray="2 3"
            ifOverflow="extendDomain"
            label={{ value: phase?.anchorExact ? "当前锚点" : "近似锚点", position: "insideTopLeft", fill: ANCHOR_COLOR, fontSize: 11 }}
          />
        ) : null}

        <ChartTooltip
          cursor={{ stroke: CROSSHAIR_COLOR, strokeWidth: 1, strokeDasharray: "3 3" }}
          content={
            <ChartTooltipContent
              className={TOOLTIP_CLASSNAME}
              labelFormatter={(label) => `时间 ${formatShortTime(String(label ?? ""))}`}
              formatter={(value, name, item) => {
                const point = item.payload as AuctionChartDatum
                if (name === "buyPrice" || name === "sellPrice") {
                  return (
                    <div className="grid w-full gap-1">
                      <div className="flex items-center justify-between gap-3">
                        <span>{name === "buyPrice" ? "买方主导价线" : "卖方主导价线"}</span>
                        <span className="font-mono">{typeof value === "number" ? value.toFixed(3) : value}</span>
                      </div>
                      {point.isAnchor ? <div className="text-[11px] text-slate-500">当前摘要锚点</div> : null}
                    </div>
                  )
                }
                return (
                  <div className="flex items-center justify-between gap-3">
                    <span>匹配量</span>
                    <span className="font-mono">{formatNumber(typeof value === "number" ? value : undefined)}</span>
                  </div>
                )
              }}
            />
          }
        />

        <Bar
          yAxisId="volume"
          dataKey="matchedVolume"
          name="matchedVolume"
          fill="var(--color-matchedVolume)"
          radius={[1, 1, 0, 0]}
          barSize={5}
        />
        <Line
          yAxisId="price"
          type="linear"
          dataKey="buyPrice"
          name="buyPrice"
          stroke="var(--color-buyPrice)"
          strokeWidth={2}
          dot={false}
          connectNulls={true}
          isAnimationActive={false}
        />
        <Line
          yAxisId="price"
          type="linear"
          dataKey="sellPrice"
          name="sellPrice"
          stroke="var(--color-sellPrice)"
          strokeWidth={2}
          dot={false}
          connectNulls={true}
          isAnimationActive={false}
        />
        {anchorPoint && typeof anchorPoint.price === "number" ? (
          <ReferenceDot
            x={anchorPoint.time}
            y={anchorPoint.price}
            yAxisId="price"
            r={4}
            fill={ANCHOR_COLOR}
            stroke="#ffffff"
            strokeWidth={1}
            ifOverflow="extendDomain"
          />
        ) : null}
      </ComposedChart>
    </ChartContainer>
  )
}

function UnmatchedChart({
  data,
  dividerTime,
  targetTime,
  syncId,
}: {
  data: AuctionChartDatum[]
  dividerTime?: string
  targetTime?: string
  syncId: string
}) {
  const showDividerLine = Boolean(dividerTime && data.some((point) => point.time === dividerTime))
  const showTargetLine = Boolean(targetTime && data.some((point) => point.time === targetTime))

  return (
    <ChartContainer config={unmatchedChartConfig} className="h-[168px] w-full rounded-none">
      <ComposedChart syncId={syncId} data={data} margin={{ left: 6, right: 6, top: 0, bottom: 4 }}>
        <CartesianGrid vertical={true} strokeDasharray="2 2" stroke={PANEL_GRID_COLOR} />
        <XAxis
          dataKey="time"
          tickLine={false}
          axisLine={false}
          tickFormatter={formatShortTime}
          interval="preserveStartEnd"
          minTickGap={20}
          height={24}
          tick={{ fill: PANEL_AXIS_COLOR, fontSize: 11 }}
        />
        <YAxis
          yAxisId="leftSpacer"
          orientation="left"
          tickLine={false}
          axisLine={false}
          width={48}
          hide
        />
        <YAxis
          yAxisId="delta"
          orientation="left"
          tickLine={false}
          axisLine={false}
          width={48}
          hide
          domain={([dataMin, dataMax]) => {
            const maxAbs = Math.max(Math.abs(Number(dataMin ?? 0)), Math.abs(Number(dataMax ?? 0)), 1)
            return [-maxAbs, maxAbs]
          }}
        />
        <YAxis
          yAxisId="unmatched"
          orientation="right"
          tickLine={false}
          axisLine={false}
          width={56}
          domain={([dataMin, dataMax]) => {
            const maxAbs = Math.max(Math.abs(Number(dataMin ?? 0)), Math.abs(Number(dataMax ?? 0)), 1)
            return [-maxAbs, maxAbs]
          }}
          tickFormatter={(value: number) => formatNumber(Math.abs(value))}
          tick={{ fill: PANEL_AXIS_COLOR, fontSize: 11 }}
        />

        {showDividerLine ? (
          <ReferenceLine
            x={dividerTime}
            stroke={PANEL_AXIS_COLOR}
            strokeDasharray="3 3"
            ifOverflow="extendDomain"
          />
        ) : null}
        {showTargetLine ? (
          <ReferenceLine
            x={targetTime}
            stroke={MATCHED_VOLUME_COLOR}
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
        ) : null}
        <ReferenceLine y={0} stroke="#475569" strokeOpacity={0.9} />

        <ChartTooltip
          cursor={{ stroke: CROSSHAIR_COLOR, strokeWidth: 1, strokeDasharray: "3 3" }}
          content={
            <ChartTooltipContent
              className={TOOLTIP_CLASSNAME}
              labelFormatter={(label) => `时间 ${formatShortTime(String(label ?? ""))}`}
              formatter={(_value, name, item) => {
                const point = item.payload as AuctionChartDatum
                if (name === "buyUnmatched") {
                  return (
                    <div className="flex items-center justify-between gap-3">
                      <span>未匹配买量</span>
                      <span className="font-mono">{formatNumber(point.buyUnmatchedAbs)}</span>
                    </div>
                  )
                }
                if (name === "sellUnmatched") {
                  return (
                    <div className="flex items-center justify-between gap-3">
                      <span>未匹配卖量</span>
                      <span className="font-mono">{formatNumber(point.sellUnmatchedAbs)}</span>
                    </div>
                  )
                }
                return (
                  <div className="flex items-center justify-between gap-3">
                    <span>买卖差额线</span>
                    <span className="font-mono">{formatSignedNumber(point.imbalanceDelta, 0)}</span>
                  </div>
                )
              }}
            />
          }
        />

        <Bar dataKey="buyUnmatched" yAxisId="unmatched" name="buyUnmatched" fill="var(--color-buyUnmatched)" barSize={6} radius={[1, 1, 0, 0]} />
        <Bar dataKey="sellUnmatched" yAxisId="unmatched" name="sellUnmatched" fill="var(--color-sellUnmatched)" barSize={6} radius={[0, 0, 1, 1]} />
        <Line
          yAxisId="delta"
          type="linear"
          dataKey="imbalanceDelta"
          name="imbalanceDelta"
          stroke="var(--color-imbalanceDelta)"
          strokeWidth={1.75}
          dot={false}
          connectNulls={true}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ChartContainer>
  )
}

function TdxAuctionChart({
  title,
  points,
  phase,
  dividerTime,
}: {
  title: string
  points: StockAuctionPoint[]
  phase?: StockAuctionPhaseSnapshot
  dividerTime?: string
}) {
  const chartData = buildAuctionChartData(points, phase)
  const targetTime = phase?.anchorTargetTime
  const syncId = `auction-${title}`

  return (
    <div className="space-y-3 rounded-xl border border-slate-300 p-3 text-slate-900">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-slate-900">{title}</div>
          <div className="text-xs text-slate-500">按通达信竞价图结构：上价量，下未匹配买卖，同步十字线联动</div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {dividerTime ? <Badge variant="outline" className="border-slate-300 bg-white text-slate-700">分界 {formatShortTime(dividerTime)}</Badge> : null}
          {targetTime ? <Badge variant="outline" className="border-slate-300 bg-white text-slate-700">定价 {formatShortTime(targetTime)}</Badge> : null}
          {phase?.time ? <Badge variant={phase?.anchorExact ? "default" : "secondary"}>锚点 {formatShortTime(phase.time)}</Badge> : null}
        </div>
      </div>

      <TdxLegend />

      {chartData.length ? (
        <div className="overflow-hidden rounded-lg border border-slate-300">
          <PriceVolumeChart data={chartData} phase={phase} dividerTime={dividerTime} syncId={syncId} />
          <UnmatchedChart data={chartData} dividerTime={dividerTime} targetTime={targetTime} syncId={syncId} />
        </div>
      ) : (
        <div className="text-xs text-slate-500">暂无可绘制的竞价趋势数据</div>
      )}
    </div>
  )
}

function EnhancedMetrics({ phase, title, points }: { phase?: StockAuctionPhaseSnapshot; title: string; points: StockAuctionPoint[] }) {
  const trendMetrics = getSplitTrendMetrics(title, points)
  const initialAuctionSnapshot = getInitialAuctionSnapshot(points)

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="竞价价格区间"
        value={phase?.priceRange ? `${phase.priceRange.low} ~ ${phase.priceRange.high}` : "--"}
        subValue={`区间振幅：${phase?.priceRange ? phase.priceRange.spread.toFixed(3) : "--"}`}
      />
      <MetricCard
        label={trendMetrics[0]?.label ?? "阶段一价格趋势"}
        value={trendMetrics[0]?.trend ?? "--"}
        subValue={`价格变化：${formatSignedNumber(trendMetrics[0]?.change)}`}
      />
      <MetricCard
        label={trendMetrics[1]?.label ?? "阶段二价格趋势"}
        value={trendMetrics[1]?.trend ?? "--"}
        subValue={`价格变化：${formatSignedNumber(trendMetrics[1]?.change)}`}
      />
      <MetricCard
        label="09:15 初始竞价量"
        value={initialAuctionSnapshot ? formatNumber(initialAuctionSnapshot.matchedVolume) : "--"}
        subValue={initialAuctionSnapshot ? `${formatShortTime(initialAuctionSnapshot.time)} 未匹配 ${formatNumber(initialAuctionSnapshot.unmatchedVolume)} · ${initialAuctionSnapshot.directionText}` : "暂无 09:15 数据"}
      />
      <MetricCard
        label="最近虚拟成交量增量"
        value={formatNumber(phase?.recentVolumeDelta)}
        subValue={`量比：${formatRatio(phase?.auctionVolumeRatio)}`}
      />
      <MetricCard
        label="主导方向"
        value={phase?.dominantDirection ?? "--"}
        subValue={`切换次数：${phase?.directionFlipCount ?? "--"}`}
      />
      <MetricCard
        label="方向稳定度"
        value={phase?.directionStability ?? "--"}
        subValue={`失衡压力：${formatRatio(phase?.imbalancePressure ?? undefined)}`}
      />
      <MetricCard
        label="数据可信度"
        value={phase?.dataConfidence ?? "--"}
        subValue={`锚点：${phase?.anchorExact ? "精确" : "近似"}`}
      />
    </div>
  )
}

function PhaseBlock({ title, phase, points }: { title: string; phase?: StockAuctionPhaseSnapshot; points: StockAuctionPoint[] }) {
  const buySellProgress = calcBuySellProgress(phase)
  const auctionVolumeProgress = calcAuctionVolumeProgress(phase)
  const anchorBadge = getAnchorBadge(phase)
  const hasDirection = hasDirectionData(phase)
  const dividerTime = title.includes("早盘") ? "09:20:00" : undefined

  return (
    <div className="space-y-4 rounded-2xl border border-border/60 bg-background/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="text-xs text-muted-foreground">时间：{phase?.time ?? "--"}</div>
          <div className="text-xs text-muted-foreground">锚点来源：{phase?.anchorSource ?? "--"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={anchorBadge.variant}>{anchorBadge.text}</Badge>
          <Badge variant="outline" className={cn(getRiseFallBadgeClass(phase?.gapRate))}>{typeof phase?.gapRate === "number" ? (phase.gapRate >= 0 ? "高开" : "低开") : "未知"}</Badge>
          <Badge variant="outline" className={cn(getStrengthBadgeClass(phase?.strengthLabel))}>{phase?.strengthLabel ?? "--"}</Badge>
          <Badge variant={getConfidenceTone(phase?.dataConfidence)}>可信度 {phase?.dataConfidence ?? "--"}</Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="竞价价格" value={phase?.price?.toString() ?? "--"} subValue={`撮合价：${phase?.matchPrice ?? "--"}`} />
        <MetricCard label="高开/低开幅度" value={formatPercent(phase?.gapRate)} subValue={`竞价量比：${formatRatio(phase?.auctionVolumeRatio)}`} />
        <MetricCard label="未匹配买卖差" value={phase?.unmatchedDelta?.toString() ?? "--"} subValue={`买量 ${phase?.unmatchedBuyVolume ?? "--"} / 卖量 ${phase?.unmatchedSellVolume ?? "--"}`} />
        <MetricCard label="成交概览" value={formatNumber(phase?.volume)} subValue={`成交额：${formatAmount(phase?.amount)}`} />
      </div>

      <TdxAuctionChart title={`${title}竞价图`} points={points} phase={phase} dividerTime={dividerTime} />

      <EnhancedMetrics phase={phase} title={title} points={points} />

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-2 rounded-xl border border-border/60 bg-background/70 p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>未匹配买卖力量对比</span>
            <span>{hasDirection && buySellProgress !== null ? `买 ${buySellProgress}% / 卖 ${100 - buySellProgress}%` : "暂无方向数据"}</span>
          </div>
          {buySellProgress !== null ? <Progress value={buySellProgress} className="h-3" /> : <div className="rounded-md border border-dashed border-border/60 px-3 py-2 text-xs text-muted-foreground">当前锚点没有可判定的未匹配方向数据</div>}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>买方未匹配量：{phase?.unmatchedBuyVolume ?? "--"}</span>
            <span>卖方未匹配量：{phase?.unmatchedSellVolume ?? "--"}</span>
          </div>
          <div className="text-xs text-muted-foreground">{phase?.dominantDirection ?? "方向未知"} · {phase?.directionStability ?? "暂无方向数据"}</div>
        </div>

        <div className="space-y-2 rounded-xl border border-border/60 bg-background/70 p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>竞价量占比图示</span>
            <span>{formatPercent(typeof phase?.auctionVolumeRatio === "number" ? phase.auctionVolumeRatio * 100 : undefined)}</span>
          </div>
          <Progress value={auctionVolumeProgress} className="h-3" />
          <div className="text-xs text-muted-foreground">当前已切换为通达信系竞价明细口径，量比按竞价量相对当日总成交量派生。</div>
        </div>
      </div>

      <DetailTimeline title={`${title}明细`} points={points} />
    </div>
  )
}

export function AuctionPanel({ auction }: { auction: StockAuctionSnapshot | null }) {
  const openingPoints = auction?.details?.openingPoints ?? []
  const closingPoints = auction?.details?.closingPoints ?? []
  const allPoints = auction?.details?.allPoints ?? []
  const snapshot0925 = auction?.details?.auction0925 as Record<string, unknown> | undefined

  return (
    <Card className="border-white/70 bg-white/80 shadow-sm">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-base">集合竞价面板</CardTitle>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">交易日 {auction?.trade_date ?? "--"}</Badge>
            <Badge variant="outline">总明细 {allPoints.length}</Badge>
            <Badge variant={snapshot0925?.has_auction_0925 ? "default" : "secondary"}>09:25 {snapshot0925?.has_auction_0925 ? "命中" : "未命中"}</Badge>
            <Badge variant={auction?.closing?.anchorExact ? "default" : "secondary"}>15:00 {auction?.closing?.anchorExact ? "命中" : "近似"}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 xl:grid-cols-2">
          <PhaseBlock title="早盘集合竞价" phase={auction?.opening} points={openingPoints} />
          <PhaseBlock title="尾盘集合竞价" phase={auction?.closing} points={closingPoints} />
        </div>
      </CardContent>
    </Card>
  )
}
