import type { LucideIcon } from "lucide-react"

export interface MetricCardProps {
  label: string
  value: string
  icon: LucideIcon
  tone?: "slate" | "teal" | "violet"
}

/**
 * 通用 MetricCard · 小指标卡
 *
 * 用途:
 *   - 任何需要展示"label + value + icon"的小指标卡
 *   - 3 种 tone (slate / teal / violet) 决定背景与文本强调色
 *
 * 来源: 从 application-analysis/components/metric-card.tsx 抽出,
 * 原本仅在 application-analysis 内部用, 现挪到公共目录以便复用.
 */
export function MetricCard({ label, value, icon: Icon, tone = "slate" }: MetricCardProps) {
  const toneClass =
    tone === "teal"
      ? "bg-gradient-to-br from-teal-50 to-white text-teal-700"
      : tone === "violet"
        ? "bg-gradient-to-br from-violet-50 to-white text-violet-700"
        : "bg-gradient-to-br from-slate-50 to-white text-slate-700"
  return (
    <div className={`flex items-center gap-3 rounded-2xl border border-slate-200/80 px-3 py-2.5 shadow-[0_2px_8px_rgba(15,23,42,0.04)] ${toneClass}`}>
      <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-white/80 ring-1 ring-slate-200/70">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 leading-tight">
        <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">{label}</div>
        <div className="truncate text-sm font-semibold tracking-[-0.01em] text-slate-900">{value}</div>
      </div>
    </div>
  )
}
