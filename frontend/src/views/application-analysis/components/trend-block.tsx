import { Badge } from "@/components/ui/badge"
import { fmt } from "../lib/format"

export function TrendBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        <Badge className="rounded-full border-slate-200 bg-slate-50 text-slate-700" variant="outline">{fmt(data.state)}</Badge>
      </div>
      <div className="grid gap-2 text-sm text-slate-600">
        <div>趋势分：{fmt(data.score)} · 置信度：{fmt(data.confidence)}</div>
        <div>均线：{fmt(data.ma_structure)}</div>
        <div>价格结构：{fmt(data.price_structure)}</div>
        <div>量能：{fmt(data.volume_state)}</div>
        <div>换手：{fmt(data.turnover_state)}</div>
      </div>
    </div>
  )
}
