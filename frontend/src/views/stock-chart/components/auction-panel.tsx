import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import type { StockAuctionPhaseSnapshot, StockAuctionSnapshot } from "../lib/types"

function formatPercent(value?: number) {
  return typeof value === "number" ? `${value}%` : "--"
}

function formatRatio(value?: number) {
  return typeof value === "number" ? value.toFixed(4) : "--"
}

function getGapTone(value?: number) {
  if (typeof value !== "number") return "outline" as const
  if (value > 0) return "default" as const
  if (value < 0) return "destructive" as const
  return "secondary" as const
}

function getStrengthTone(label?: string) {
  if (!label) return "outline" as const
  if (label.includes("强")) return "default" as const
  if (label.includes("弱")) return "destructive" as const
  return "secondary" as const
}

function calcBuySellProgress(phase?: StockAuctionPhaseSnapshot) {
  const buy = phase?.unmatchedBuyVolume ?? 0
  const sell = phase?.unmatchedSellVolume ?? 0
  const total = buy + sell
  if (total <= 0) return 50
  return Math.round((buy / total) * 100)
}

function calcAuctionVolumeProgress(phase?: StockAuctionPhaseSnapshot) {
  const ratio = phase?.auctionVolumeRatio ?? 0
  return Math.max(0, Math.min(100, ratio * 100))
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

function PhaseBlock({ title, phase }: { title: string; phase?: StockAuctionPhaseSnapshot }) {
  const buySellProgress = calcBuySellProgress(phase)
  const auctionVolumeProgress = calcAuctionVolumeProgress(phase)

  return (
    <div className="space-y-4 rounded-2xl border border-border/60 bg-background/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="text-xs text-muted-foreground">时间：{phase?.time ?? "--"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={getGapTone(phase?.gapRate)}>{typeof phase?.gapRate === "number" ? (phase.gapRate >= 0 ? "高开" : "低开") : "未知"}</Badge>
          <Badge variant={getStrengthTone(phase?.strengthLabel)}>{phase?.strengthLabel ?? "--"}</Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="竞价价格" value={phase?.price?.toString() ?? "--"} subValue={`撮合价：${phase?.matchPrice ?? "--"}`} />
        <MetricCard label="高开/低开幅度" value={formatPercent(phase?.gapRate)} subValue={`竞价量比：${formatRatio(phase?.auctionVolumeRatio)}`} />
        <MetricCard label="未匹配买卖差" value={phase?.unmatchedDelta?.toString() ?? "--"} subValue={`买量 ${phase?.unmatchedBuyVolume ?? "--"} / 卖量 ${phase?.unmatchedSellVolume ?? "--"}`} />
        <MetricCard label="成交概览" value={phase?.volume?.toString() ?? "--"} subValue={`成交额：${phase?.amount ?? "--"}`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-2 rounded-xl border border-border/60 bg-background/70 p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>未匹配买卖力量对比</span>
            <span>买 {buySellProgress}% / 卖 {100 - buySellProgress}%</span>
          </div>
          <Progress value={buySellProgress} className="h-3" />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>买方未匹配量：{phase?.unmatchedBuyVolume ?? "--"}</span>
            <span>卖方未匹配量：{phase?.unmatchedSellVolume ?? "--"}</span>
          </div>
        </div>

        <div className="space-y-2 rounded-xl border border-border/60 bg-background/70 p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>竞价量占比图示</span>
            <span>{formatPercent(typeof phase?.auctionVolumeRatio === "number" ? phase.auctionVolumeRatio * 100 : undefined)}</span>
          </div>
          <Progress value={auctionVolumeProgress} className="h-3" />
          <div className="text-xs text-muted-foreground">当前用公开行情源可得口径，表示竞价量相对当日总成交量的占比。</div>
        </div>
      </div>
    </div>
  )
}

export function AuctionPanel({ auction }: { auction: StockAuctionSnapshot | null }) {
  return (
    <Card className="border-white/70 bg-white/80 shadow-sm">
      <CardHeader>
        <CardTitle className="text-base">集合竞价面板</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 xl:grid-cols-2">
        <PhaseBlock title="早盘集合竞价" phase={auction?.opening} />
        <PhaseBlock title="尾盘集合竞价" phase={auction?.closing} />
      </CardContent>
    </Card>
  )
}
