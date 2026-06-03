import { RefreshCw, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { StockAdjust } from "../../stock-chart/lib/types"

export function ChartHeader({
  selectedLabel,
  adjust,
  onAdjustChange,
  running,
  canRun,
  onTrigger,
  onManualRun,
}: {
  selectedLabel: string
  adjust: StockAdjust
  onAdjustChange: (value: StockAdjust) => void
  running: boolean
  canRun: boolean
  onTrigger: () => void
  onManualRun: () => void
}) {
  return (
    <Card className="rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-slate-950 text-white shadow-sm">
              <Sparkles className="size-4" />
            </div>
            <div className="min-w-0 space-y-0.5">
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {selectedLabel}
              </div>
              <CardTitle className="truncate text-lg font-semibold tracking-[-0.02em] text-slate-950">AI K 线结构标注分析</CardTitle>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <Select value={adjust} onValueChange={(value) => onAdjustChange(value as StockAdjust)}>
              <SelectTrigger className="h-8 w-28 rounded-lg text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="qfq">前复权</SelectItem>
                <SelectItem value="none">不复权</SelectItem>
                <SelectItem value="hfq">后复权</SelectItem>
              </SelectContent>
            </Select>
            <Button
              className="h-8 rounded-lg bg-slate-950 px-3 text-xs text-white hover:bg-slate-800"
              onClick={onTrigger}
              disabled={!canRun || running}
            >
              <RefreshCw className={`mr-1.5 size-3.5 ${running ? "animate-spin" : ""}`} />120 日 / 4 段刷新
            </Button>
            <Button
              className="h-8 rounded-lg px-3 text-xs"
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
