import { Badge } from "@/components/ui/badge"
import type { StockOverlayAnnotation } from "../../stock-chart/lib/types"

export function OverlayTable({ items }: { items: StockOverlayAnnotation[] }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700 sm:px-4">AI 可渲染标注 · {items.length}</div>
      <div className="divide-y divide-slate-100">
        {items.length ? items.map((item, index) => (
          <div key={`${item.overlay_type}-${index}`} className="grid min-w-0 gap-2 px-3 py-3 text-sm md:grid-cols-[160px_1fr_120px] md:px-4">
            <Badge className="w-fit rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{item.overlay_type}</Badge>
            <div className="min-w-0 break-words text-slate-700">{item.text || "未命名标注"}</div>
            <div className="text-slate-400">{item.points.length} points</div>
          </div>
        )) : <div className="px-4 py-8 text-sm text-slate-400">AI 没有返回可渲染标注。</div>}
      </div>
    </div>
  )
}
