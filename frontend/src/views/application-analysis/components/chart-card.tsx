import { useEffect, useState } from "react"
import { LineChart } from "lucide-react"

import { CollapsibleCard } from "@/components/collapsible-card"
import { ChartPanel, type ChartPanelSelectionItem } from "../../stock-chart/components/chart-panel"
import type { StockKlineBar, StockOverlayAnnotation } from "../../stock-chart/lib/types"

export function ChartCard({
  collapsed,
  onToggle,
  selectedSymbol,
  bars,
  overlays,
  selectionColors,
  selectedBarTimestamps,
  onSelectionChange,
  onAnalyzeSelection,
  loadingBars,
  mobileCompact = false,
  cardClassName,
}: {
  collapsed: boolean
  onToggle: () => void
  selectedSymbol: string
  bars: StockKlineBar[]
  overlays: StockOverlayAnnotation[]
  selectionColors: Record<string, string>
  selectedBarTimestamps: number[]
  onSelectionChange: (items: ChartPanelSelectionItem[]) => void
  onAnalyzeSelection: (item: ChartPanelSelectionItem) => void
  loadingBars: boolean
  mobileCompact?: boolean
  cardClassName?: string
}) {
  const [showMobileHint, setShowMobileHint] = useState(true)

  useEffect(() => {
    if (!showMobileHint) return
    const timer = window.setTimeout(() => setShowMobileHint(false), 3500)
    return () => window.clearTimeout(timer)
  }, [showMobileHint])

  return (
    <CollapsibleCard
      title="K 线分析"
      description={loadingBars ? "正在加载真实 K 线..." : "AI overlay_annotations 会直接叠加到 K 线图"}
      icon={LineChart}
      badge={String(overlays.length)}
      collapsed={collapsed}
      onToggle={onToggle}
      className={cardClassName}
    >
      <div className={`relative -mx-1 max-w-full overflow-hidden ${mobileCompact ? "h-[50svh] min-h-[300px]" : "h-[54svh] min-h-[340px]"} max-h-[520px] sm:h-[440px] lg:h-full lg:max-h-none lg:min-h-0 lg:flex-1`}>
        {showMobileHint ? (
          <button
            type="button"
            className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border border-slate-200 bg-white/95 px-3 py-1 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur lg:hidden"
            onClick={() => setShowMobileHint(false)}
          >
            可横向拖动 / 点选 K 柱
          </button>
        ) : null}
        <ChartPanel
          bars={bars}
          annotations={[]}
          overlayAnnotations={overlays}
          bsSignals={[]}
          manualSignalMode={null}
          onManualSignalCreate={() => undefined}
          symbol={selectedSymbol}
          period="1d"
          indicators={["MA", "AMOUNT"]}
          maLines={[5, 10, 20, 60]}
          selectionMode="multiple"
          selectionColors={selectionColors}
          selectedBarTimestamps={selectedBarTimestamps}
          onSelectionChange={onSelectionChange}
          onAnalyzeSelection={onAnalyzeSelection}
          mobileCompact={mobileCompact}
        />
      </div>
    </CollapsibleCard>
  )
}
