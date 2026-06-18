import { TrendingUp } from "lucide-react"

/**
 * Market Pulse "路线"注释
 *
 * 用途: Market Pulse 页面底部 dashed border 的路线说明 box, 提示
 *       "未来把 mock-market.tsx 的模块逐步迁入本页面".
 *
 * 来源: 之前是 market-pulse.tsx 主页内联 JSX (line ~744-750), 抽出来.
 */
export function MarketRoadmapNote() {
  return (
    <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-5 text-sm text-muted-foreground">
      <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
        <TrendingUp className="size-4" />
        路线
      </div>
      后续把 stock-overview/mock-market.tsx 中的强势板块 / 主力净流入 / 行业轮动 三个核心模块拆解后,逐步迁入本页面。
    </div>
  )
}
