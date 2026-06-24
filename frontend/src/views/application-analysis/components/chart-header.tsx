import { Clock, RefreshCw, Sparkles } from "lucide-react"

import type { ApplicationAnalysisTarget } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
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
  const title = target ? `${target.name} · ${target.symbol}` : selectedLabel || "请选择左侧目标"
  return (
    <Card className="rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
      <CardHeader className="px-3 pb-3 pt-4 sm:px-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-start gap-3 sm:items-center">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-slate-950 text-white shadow-sm">
              <Sparkles className="size-4" />
            </div>
            <div className="min-w-0 space-y-1">
              <CardTitle className="break-words text-base font-semibold text-slate-950 sm:truncate sm:text-lg">
                {title}
              </CardTitle>
              {target ? (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="size-3" />
                    <span>每 {target.interval_minutes} 分钟</span>
                  </span>
                  <span className="text-slate-300">·</span>
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
                      <span className="text-slate-300">·</span>
                      <span>最近 {new Date(target.last_updated_at).toLocaleString()}</span>
                    </>
                  ) : null}
                  <span className="text-slate-300">·</span>
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
          <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:items-center xl:justify-end">
            <Select value={adjust} onValueChange={(value) => onAdjustChange(value as StockAdjust)}>
              <SelectTrigger className="h-8 w-full rounded-lg text-xs sm:w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="qfq">前复权</SelectItem>
                <SelectItem value="none">不复权</SelectItem>
                <SelectItem value="hfq">后复权</SelectItem>
              </SelectContent>
            </Select>
            <Button
              className="h-8 w-full rounded-lg bg-slate-950 px-3 text-xs text-white hover:bg-slate-800 sm:w-auto"
              onClick={onTrigger}
              disabled={!canRun || running}
            >
              <RefreshCw className={`mr-1.5 size-3.5 ${running ? "animate-spin" : ""}`} />120 日 / 4 段刷新
            </Button>
            <Button
              className="h-8 w-full rounded-lg px-3 text-xs sm:w-auto"
              variant="outline"
              onClick={onManualRun}
              disabled={!canRun || running}
            >
              手动单次
            </Button>
          </div>
        </div>
      </CardHeader>
    </Card>
  )
}
