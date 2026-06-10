import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { StockAdjust, StockPeriod } from "../lib/types"

const periods: Array<{ value: StockPeriod; label: string }> = [
  { value: "5m", label: "5分" },
  { value: "15m", label: "15分" },
  { value: "30m", label: "30分" },
  { value: "60m", label: "60分" },
  { value: "1d", label: "日K" },
  { value: "1w", label: "周K" },
]
const adjusts: Array<{ value: StockAdjust; label: string }> = [
  { value: "none", label: "不复权" },
  { value: "qfq", label: "前复权" },
  { value: "hfq", label: "后复权" },
]

const minutePeriods: StockPeriod[] = ["5m", "15m", "30m", "60m"]
const indicators = [
  { key: "EXPMA", label: "EXPMA" },
  { key: "BOLL", label: "BOLL" },
  { key: "MACD", label: "MACD" },
  { key: "AMOUNT", label: "成交额" },
]
const maLineOptions = [5, 10, 30, 60]

export function IndicatorToolbar({
  period,
  adjust,
  activeIndicators,
  maLines,
  onPeriodChange,
  onAdjustChange,
  onToggleIndicator,
  onToggleMALine,
  compact = false,
}: {
  period: StockPeriod
  adjust: StockAdjust
  activeIndicators: string[]
  maLines: number[]
  onPeriodChange: (value: StockPeriod) => void
  onAdjustChange: (value: StockAdjust) => void
  onToggleIndicator: (value: string) => void
  onToggleMALine: (value: number) => void
  /** compact: 用在 dialog 等空间紧的场景, button/badge 全部 xs 字号, 间距收紧 */
  compact?: boolean
}) {
  const availableAdjusts = minutePeriods.includes(period) ? adjusts.filter((item) => item.value === "none") : adjusts
  const btnSize = compact ? "xs" : "sm"
  const badgeSize = compact ? "text-[10px]" : "text-xs"
  return (
    <div className={cn("rounded-2xl border border-white/70 bg-white/80 shadow-sm", compact ? "space-y-1.5 p-2" : "space-y-3 p-4")}>
      <div className={cn("flex flex-wrap items-center", compact ? "gap-1" : "gap-2")}>
        {periods.map((item) => (
          <Button key={item.value} size={btnSize} variant={period === item.value ? "default" : "outline"} onClick={() => onPeriodChange(item.value)}>
            {item.label}
          </Button>
        ))}
        {availableAdjusts.map((item) => (
          <Button key={item.value} size={btnSize} variant={adjust === item.value ? "default" : "outline"} onClick={() => onAdjustChange(item.value)}>
            {item.label}
          </Button>
        ))}
      </div>
      <div className={cn("flex flex-wrap items-center", compact ? "gap-1" : "gap-2")}>
        <span className={cn("font-medium text-muted-foreground", compact ? "text-[10px]" : "text-xs")}>主图均线</span>
        {maLineOptions.map((item) => (
          <Badge key={item} variant={maLines.includes(item) ? "default" : "outline"} className={cn("cursor-pointer", badgeSize)} onClick={() => onToggleMALine(item)}>
            MA{item}
          </Badge>
        ))}
      </div>
      <div className={cn("flex flex-wrap items-center", compact ? "gap-1" : "gap-2")}>
        <span className={cn("font-medium text-muted-foreground", compact ? "text-[10px]" : "text-xs")}>副图指标</span>
        {indicators.map((item) => (
          <Badge key={item.key} variant={activeIndicators.includes(item.key) ? "default" : "outline"} className={cn("cursor-pointer", badgeSize)} onClick={() => onToggleIndicator(item.key)}>
            {item.label}
          </Badge>
        ))}
      </div>
    </div>
  )
}
