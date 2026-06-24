import { Activity, Sparkles, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

import { BarSummary } from "./bar-summary"
import { CollapsibleCard } from "@/components/collapsible-card"
import { fmtDateTime } from "../lib/format"
import type { ChartPanelSelectionItem } from "../../stock-chart/components/chart-panel"

export function SelectionPanel(props: {
  collapsed: boolean
  onToggle: () => void
  items: ChartPanelSelectionItem[]
  selectionColorMap: Record<string, string>
  analysisFocusKey: string | null
  prevCloseMap: Record<string, number | null>
  prevVolumeMap: Record<string, number | null>
  prevTurnoverMap: Record<string, number | null>
  panelRef: React.RefObject<HTMLDivElement | null>
  onRemoveItem: (item: ChartPanelSelectionItem) => void
  onClearAll: () => void
  onAnalyzeBar: (item: Extract<ChartPanelSelectionItem, { kind: "bar" }>) => void
}) {
  const {
    collapsed,
    onToggle,
    items,
    selectionColorMap,
    analysisFocusKey,
    prevCloseMap,
    prevVolumeMap,
    prevTurnoverMap,
    panelRef,
    onClearAll,
    onAnalyzeBar,
  } = props
  return (
    <div ref={panelRef}>
      <CollapsibleCard
        title="选中分析项"
        description="图上可多选 K 柱；详情会在这里集中展示"
        icon={Sparkles}
        badge={String(items.length)}
        collapsed={collapsed}
        onToggle={onToggle}
      >
        {items.length ? (
          <div className="space-y-2.5">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClearAll}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
              >
                <X className="h-3.5 w-3.5" />
                <span>取消全部</span>
              </button>
            </div>
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
                  <button
                    type="button"
                    onClick={() => props.onRemoveItem(item)}
                    className="absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                    aria-label="移除选中项"
                    title="移除选中项"
                  >
                    <X className="h-4 w-4" />
                  </button>
                    <div className="min-w-0 pl-3 pr-8">
                    {item.kind === "bar" ? (
                      <>
                        <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0 flex-1">
                            <BarSummary
                              bar={item.bar}
                              prevClose={prevCloseMap[item.key] ?? null}
                              prevVolume={prevVolumeMap[item.key] ?? null}
                              prevTurnover={prevTurnoverMap[item.key] ?? null}
                              color={color}
                              focused={analysisFocusKey === item.key}
                            />
                          </div>
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            className="mt-0.5 h-7 w-full gap-1.5 rounded-md border-slate-200 px-2.5 text-[11px] sm:w-auto"
                            onClick={() => onAnalyzeBar(item)}
                          >
                            <Activity className="h-3.5 w-3.5" />
                            Analysis
                          </Button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="mb-1.5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                          <div className="break-words text-sm font-semibold text-slate-900 sm:truncate">{item.typeLabel} · {item.shortText}</div>
                          <Badge
                            className="w-fit rounded-full bg-white text-[10px]"
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
                            <span className="break-all font-mono text-slate-700">
                              {fmtDateTime(item.startTimestamp)} → {fmtDateTime(item.endTimestamp)}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-400">价格</span>{" "}
                            <span className="break-all font-mono text-slate-700">
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
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-[11px] leading-5 break-words text-slate-500">
            先在右侧 K 线图中点击 K 柱，或点选标注标签，这里会展示当前选中的分析对象。
          </div>
        )}
      </CollapsibleCard>
    </div>
  )
}
