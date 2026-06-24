import { Clock, RefreshCw, Sparkles, TrendingUp } from "lucide-react"

import type { ApplicationAnalysisTarget } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useIsMobile } from "@/hooks/use-mobile"
import type { StockAdjust } from "../../stock-chart/lib/types"

export function ChartHeader({
  target,
  selectedLabel,
  adjust,
  onAdjustChange,
  running,
  canRun,
  onTrigger,
  onManualRun,
}: {
  target?: ApplicationAnalysisTarget | null
  selectedLabel: string
  adjust: StockAdjust
  onAdjustChange: (value: StockAdjust) => void
  running: boolean
  canRun: boolean
  onTrigger: () => void
  onManualRun: () => void
}) {
  const isMobile = useIsMobile()
  const title = target ? `${target.name} · ${target.symbol}` : selectedLabel || "请选择左侧目标"
  return (
    <Card className="rounded-none border-x-0 border-t-0 border-slate-200/80 bg-white py-2 shadow-[0_1px_0_rgba(15,23,42,0.04)] sm:rounded-2xl sm:border-x sm:border-t sm:py-6 sm:shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
      <CardHeader className="px-3 pt-1.5 pb-2 sm:px-4 sm:pt-0 sm:pb-3 2xl:px-6">
        <div className="flex flex-row items-center gap-2 lg:justify-between">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {!isMobile ? (
              <div className="flex size-7 shrink-0 items-center justify-center rounded-xl bg-slate-950 text-white shadow-sm sm:size-9">
                <Sparkles className="size-3 sm:size-4" />
              </div>
            ) : null}
            <div className="min-w-0 space-y-0.5">
              <CardTitle className="flex min-w-0 items-center gap-1.5 truncate text-[15px] font-semibold text-slate-950 sm:text-lg">
                <TrendingUp className="size-3.5 shrink-0 text-slate-500 sm:size-4" />
                <span className="truncate">{title}</span>
              </CardTitle>
              {target ? (
                <div className="hidden items-center gap-x-1.5 gap-y-1 text-[10px] text-slate-500 sm:flex sm:text-[11px]">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="size-3" />
                    <span>每 {target.interval_minutes} 分钟</span>
                  </span>
                  <span className="hidden text-slate-300 sm:inline">·</span>
                  {target.enabled ? (
                    <Badge
                      className="rounded-full border-emerald-200 bg-emerald-50 px-1.5 py-0 text-[10px] text-emerald-700"
                      variant="outline"
                    >
                      启用
                    </Badge>
                  ) : (
                    <Badge
                      className="rounded-full border-slate-200 bg-slate-100 px-1.5 py-0 text-[10px] text-slate-500"
                      variant="outline"
                    >
                      停用
                    </Badge>
                  )}
                  {target.last_updated_at ? (
                    <>
                      <span className="hidden text-slate-300 sm:inline">·</span>
                      <span className="hidden sm:inline">最近 {new Date(target.last_updated_at).toLocaleString()}</span>
                    </>
                  ) : null}
                  <span className="hidden text-slate-300 sm:inline">·</span>
                  <Badge
                    className="rounded-full border-slate-200 bg-slate-50 px-1.5 py-0 text-[10px] text-slate-600"
                    variant="outline"
                  >
                    {target.target_type}
                  </Badge>
                </div>
              ) : null}
            </div>
          </div>
          <div className="grid shrink-0 grid-cols-2 items-stretch gap-1.5 sm:grid-cols-3 lg:justify-end">
            <Select value={adjust} onValueChange={(value) => onAdjustChange(value as StockAdjust)}>
              <SelectTrigger className="hidden h-7 w-full justify-center rounded-xl px-1.5 text-center text-[10px] leading-none text-slate-900 [&>svg:last-child]:hidden sm:flex sm:w-28 sm:rounded-lg sm:px-3 sm:text-xs sm:[&>svg:last-child]:inline-flex">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="qfq">Forward</SelectItem>
                <SelectItem value="none">Raw</SelectItem>
                <SelectItem value="hfq">Backward</SelectItem>
              </SelectContent>
            </Select>
            <Button
              className="h-6 w-full justify-center rounded-xl bg-secondary px-1 text-[9px] leading-none text-center text-secondary-foreground hover:bg-secondary/90 [&>svg]:hidden sm:h-7 sm:w-auto sm:rounded-lg sm:px-3 sm:text-xs sm:[&>svg]:inline-flex"
              onClick={onTrigger}
              disabled={!canRun || running}
              variant="secondary"
            >
              <RefreshCw className={`mr-1 size-3 ${running ? "animate-spin" : ""}`} />
              <span className="max-lg:hidden">120D / 4S Refresh</span>
              <span className="lg:hidden">Refresh</span>
            </Button>
            <Button
              className="h-6 w-full justify-center rounded-xl px-1 text-[9px] leading-none text-center sm:h-7 sm:w-auto sm:rounded-lg sm:px-3 sm:text-xs"
              variant="outline"
              onClick={onManualRun}
              disabled={!canRun || running}
            >
              <span className="max-lg:hidden">Manual Run</span>
              <span className="lg:hidden">Once</span>
            </Button>
          </div>
        </div>
      </CardHeader>
    </Card>
  )
}
