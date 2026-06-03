import { Sparkles } from "lucide-react"

import { Badge } from "@/components/ui/badge"

import { BarSummary } from "./bar-summary"
import { CollapsibleCard } from "./collapsible-card"
import { fmtDateTime } from "../lib/format"
import type { ChartPanelSelectionItem } from "../../stock-chart/components/chart-panel"

export function SelectionPanel({
  collapsed,
  onToggle,
  items,
  selectionColorMap,
  analysisFocusKey,
  prevCloseMap,
  prevVolumeMap,
  prevTurnoverMap,
  panelRef,
}: {
  collapsed: boolean
  onToggle: () => void
  items: ChartPanelSelectionItem[]
  selectionColorMap: Record<string, string>
  analysisFocusKey: string | null
  prevCloseMap: Record<string, number | null>
  prevVolumeMap: Record<string, number | null>
  prevTurnoverMap: Record<string, number | null>
  panelRef: React.RefObject<HTMLDivElement | null>
}) {
  return (
    <div ref={panelRef}>
      <CollapsibleCard
        title="选中分析项"
        description="图上可多选 K 柱；选中后不再在图中显示 tooltip，详情统一在这里展示"
        icon={Sparkles}
        badge={String(items.length)}
        collapsed={collapsed}
        onToggle={onToggle}
      >
        {items.length ? (
          <div className="space-y-2.5">
            {items.map((item) => {
              const color = selectionColorMap[item.key] || "#94a3b8"
              return (
                <div
                  key={item.key}
                  className={`relative rounded-xl border p-3 transition ${
                    analysisFocusKey === item.key
                      ? "border-slate-300 bg-white shadow-[0_4px_16px_rgba(15,23,42,0.06)]"
                      : "border-slate-200/80 bg-slate-50/60 hover:bg-white"
                  }`}
                >
                  <span
                    className="absolute inset-y-2 left-0 w-1 rounded-r-full"
                    style={{ backgroundColor: color }}
                  />
                  <div className="pl-3">
                    {item.kind === "bar" ? (
                      <BarSummary
                        bar={item.bar}
                        prevClose={prevCloseMap[item.key] ?? null}
                        prevVolume={prevVolumeMap[item.key] ?? null}
                        prevTurnover={prevTurnoverMap[item.key] ?? null}
                        color={color}
                        focused={analysisFocusKey === item.key}
                      />
                    ) : (
                      <>
                        <div className="mb-1.5 flex items-center justify-between gap-2">
                          <div className="truncate text-sm font-semibold text-slate-900">{item.typeLabel} · {item.shortText}</div>
                          <Badge
                            className="rounded-full bg-white text-[10px]"
                            style={{ borderColor: color, color }}
                            variant="outline"
                          >
                            {item.overlayType}
                          </Badge>
                        </div>
                        <div className="grid gap-0.5 text-[11px] leading-5 text-slate-600">
                          <div className="line-clamp-2">{item.fullText || "未提供 annotation 描述"}</div>
                          <div>
                            <span className="text-slate-400">区间</span>{" "}
                            <span className="font-mono text-slate-700">
                              {fmtDateTime(item.startTimestamp)} → {fmtDateTime(item.endTimestamp)}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-400">价格</span>{" "}
                            <span className="font-mono text-slate-700">
                              {item.minValue.toFixed(2)} - {item.maxValue.toFixed(2)}
                            </span>{" "}
                            <span className="text-slate-400">· 点位 {item.annotation.points.length}</span>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-[11px] text-slate-500">
            先在右侧 K 线图中点击 K 柱，或点选 annotation 标签，这里会展示当前选中的分析对象。
          </div>
        )}
      </CollapsibleCard>
    </div>
  )
}
