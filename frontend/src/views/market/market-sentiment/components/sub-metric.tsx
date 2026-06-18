/**
 * 子项指标块 + 涨跌停情绪等级 meta + 合成指数等级 meta.
 * 多张子卡复用.
 */
import { cn } from "@/lib/utils"
import type { LimitEmotionLevel } from "@/lib/api"

export const LEVEL_META: Record<
  LimitEmotionLevel,
  { label: string; tone: string; chip: string }
> = {
  hot: { label: "火热", tone: "text-red-600", chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃", tone: "text-orange-600", chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性", tone: "text-slate-700", chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak: { label: "弱势", tone: "text-blue-600", chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice: { label: "冰点", tone: "text-slate-400", chip: "border-slate-300 bg-slate-100 text-slate-500" },
}

export const MSI_LEVEL_META: Record<string, { label: string; tone: string; chip: string }> = {
  hot:    { label: "火热",   tone: "text-red-600",    chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃",   tone: "text-orange-600", chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性",   tone: "text-slate-700",  chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak:   { label: "弱势",   tone: "text-blue-600",   chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice:    { label: "冰点",   tone: "text-slate-400",  chip: "border-slate-300 bg-slate-100 text-slate-500" },
}

interface SubMetricProps {
  title: string
  value: string
  subValue: string | null
  score: number | null
  invertTone?: boolean
}

export function SubMetric({
  title,
  value,
  subValue,
  score,
  invertTone = false,
}: SubMetricProps) {
  const tone =
    score == null
      ? "text-slate-700"
      : invertTone
        ? score >= 70
          ? "text-emerald-600"
          : score >= 40
            ? "text-amber-600"
            : "text-red-600"
        : score >= 70
          ? "text-red-600"
          : score >= 40
            ? "text-amber-600"
            : "text-emerald-600"
  return (
    <div className="rounded-xl bg-muted/30 p-2.5">
      <div className="text-[10px] text-muted-foreground">{title}</div>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className={cn("text-sm font-semibold tabular-nums", tone)}>{value}</span>
        {subValue && (
          <span className="text-[10px] tabular-nums text-muted-foreground">{subValue}</span>
        )}
      </div>
      {score != null && (
        <div className="mt-0.5 text-[10px] tabular-nums text-muted-foreground">
          得分 {score.toFixed(0)}
        </div>
      )}
    </div>
  )
}