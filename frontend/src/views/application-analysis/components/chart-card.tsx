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
}) {
  return (
    <CollapsibleCard
      title="K 线分析"
      description={loadingBars ? "正在加载真实 K 线..." : "AI overlay_annotations 会直接叠加到 K 线图"}
      icon={LineChart}
      badge={String(overlays.length)}
      collapsed={collapsed}
      onToggle={onToggle}
    >
      <div className="-mx-1 h-full min-h-0 flex-1">
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
        />
      </div>
    </CollapsibleCard>
  )
}
