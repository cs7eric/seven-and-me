import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
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
}: {
  period: StockPeriod
  adjust: StockAdjust
  activeIndicators: string[]
  maLines: number[]
  onPeriodChange: (value: StockPeriod) => void
  onAdjustChange: (value: StockAdjust) => void
  onToggleIndicator: (value: string) => void
  onToggleMALine: (value: number) => void
}) {
  const availableAdjusts = minutePeriods.includes(period) ? adjusts.filter((item) => item.value === "none") : adjusts
  return (
    <div className="space-y-3 rounded-2xl border border-white/70 bg-white/80 p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        {periods.map((item) => (
          <Button key={item.value} size="sm" variant={period === item.value ? "default" : "outline"} onClick={() => onPeriodChange(item.value)}>
            {item.label}
          </Button>
        ))}
        {availableAdjusts.map((item) => (
          <Button key={item.value} size="sm" variant={adjust === item.value ? "default" : "outline"} onClick={() => onAdjustChange(item.value)}>
            {item.label}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">主图均线</span>
        {maLineOptions.map((item) => (
          <Badge key={item} variant={maLines.includes(item) ? "default" : "outline"} className="cursor-pointer" onClick={() => onToggleMALine(item)}>
            MA{item}
          </Badge>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">副图指标</span>
        {indicators.map((item) => (
          <Badge key={item.key} variant={activeIndicators.includes(item.key) ? "default" : "outline"} className="cursor-pointer" onClick={() => onToggleIndicator(item.key)}>
            {item.label}
          </Badge>
        ))}
      </div>
    </div>
  )
}
