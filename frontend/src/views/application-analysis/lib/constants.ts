export const DEFAULT_HORIZON = { days: 120, segments: 4, monthly_keep: 6, weekly_keep: 12 }

export const SELECTION_COLORS = ["#0f766e", "#2563eb", "#7c3aed", "#ea580c", "#be123c", "#0891b2", "#4f46e5", "#65a30d"]

export const BIAS_TONE: Record<string, { label: string; cls: string }> = {
  bullish: { label: "偏多", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  neutral_bullish: { label: "中性偏多", cls: "bg-rose-50/70 text-rose-700 border-rose-200" },
  neutral: { label: "中性", cls: "bg-slate-50 text-slate-700 border-slate-200" },
  neutral_bearish: { label: "中性偏空", cls: "bg-emerald-50/70 text-emerald-700 border-emerald-200" },
  bearish: { label: "偏空", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  unclear: { label: "不可判断", cls: "bg-slate-50 text-slate-500 border-slate-200" },
}
