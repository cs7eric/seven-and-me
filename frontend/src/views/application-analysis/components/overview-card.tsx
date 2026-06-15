import { Bot, CheckCircle2, FileJson, LineChart } from "lucide-react"

import { CollapsibleCard } from "@/components/collapsible-card"
import { MetricCard } from "@/components/metric-card"

export function OverviewCard({
  collapsed,
  onToggle,
  selectedName,
  selectedSymbol,
  barsCount,
  running,
  resultReady,
  overlayCount,
}: {
  collapsed: boolean
  onToggle: () => void
  selectedName: string | null
  selectedSymbol: string | null
  barsCount: number
  running: boolean
  resultReady: boolean
  overlayCount: number
}) {
  const targetLabel = selectedName && selectedSymbol ? `${selectedName} · ${selectedSymbol}` : "—"
  return (
    <CollapsibleCard
      title="分析概览"
      description="当前目标的基础状态信息"
      icon={LineChart}
      collapsed={collapsed}
      onToggle={onToggle}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <MetricCard icon={LineChart} tone="teal" label="当前目标" value={targetLabel} />
        <MetricCard icon={FileJson} tone="violet" label="日 K 数量" value={String(barsCount)} />
        <MetricCard icon={Bot} label="AI 状态" value={running ? "分析中" : resultReady ? "已完成" : "待执行"} />
        <MetricCard icon={CheckCircle2} tone="teal" label="可渲染标注" value={String(overlayCount)} />
      </div>
    </CollapsibleCard>
  )
}
