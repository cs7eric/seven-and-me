import { Flame } from "lucide-react"

/**
 * Market Pulse 页面头部
 *
 * 用途: 顶部 chip + 标题 h1 + 描述 p 三件套, 给 "市场脉搏" page 用.
 *
 * 来源: 之前是 market-pulse.tsx 主页内联 JSX (line ~376-390), 抽出来便于阅读.
 */
export function MarketPulseHeader() {
  return (
    <div className="space-y-3">
      <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
        <Flame className="size-3.5" />
        Mock Workspace
      </div>
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-4xl">
          Market Pulse
        </h1>
        <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
          市场脉搏的预留页面,后续接入指数快照、板块热力、涨跌停统计、北向资金等实时指标。
        </p>
      </div>
    </div>
  )
}
