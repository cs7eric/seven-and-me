/**
 * Design entry:
 * - Data/API: market-sentiment-index + nine factor cards with snapshot/history endpoints
 * - Front design: design/front/market-sentiment.md
 * - Backend design: design/backend/market-sentiment-pipeline.md
 * - Change rule: review design before edits; sync design if factor set, date linkage, or API composition changes.
 */
/**
 * Market Sentiment 页面入口
 *
 * 顶部 1 张 composite 大卡 + 9 张子卡:
 *   Top:   Market Sentiment Index (9 张卡加权, composite_score 0-100)
 *   Row 1: Risk Appetite | Market Breadth (合成) | 252 日新高
 *   Row 2: Sector Breadth | Turnover Activity | Limit Emotion
 *   Row 3: Volatility Sentiment | Style Risk Appetite | Profit Effect
 *
 * + 4 张占位卡 (规划中: Bull-Bear / Social Buzz / Margin / Regime)
 */
import { useState } from "react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { MarketSentimentIndexCard } from "./components/market-sentiment-index-card"
import { RiskAppetiteCard } from "./components/risk-appetite-card"
import { MarketBreadthCard } from "./components/market-breadth-card"
import { NewHigh252dCard } from "./components/new-high-252d-card"
import { SectorBreadthCard } from "./components/sector-breadth-card"
import { TurnoverActivityCard } from "./components/turnover-activity-card"
import { LimitEmotionCard } from "./components/limit-emotion-card"
import { VolatilitySentimentCard } from "./components/volatility-sentiment-card"
import { StyleRiskAppetiteCard } from "./components/style-risk-appetite-card"
import { ProfitEffectCard } from "./components/profit-effect-card"

export default function MarketSentimentPage() {
  // null = 后端默认行为 (上一交易日). 切换时 5 张卡 + history 一起重拉.
  const [date, setDate] = useState<string | null>(null)
  const reset = () => setDate(null)
  // "今天" 本地 00:00 (calendar disabled 用, 避免当前时间让今天也被禁)
  const now = new Date()
  const maxDate = new Date(now.getFullYear(), now.getMonth(), now.getDate())

  return (
    <WorkspaceShell sectionLabel="Market Sentiment" pageTitle="Mock Workspace">
      <div className="grid gap-4 md:grid-cols-[5fr_2fr] md:h-[calc(100vh-7rem)]">
        {/* 左侧 5/6: 合成指数折线大卡 (撑满高度) */}
        <div className="min-w-0 min-h-0">
          <MarketSentimentIndexCard date={date} onDateChange={setDate} onReset={reset} maxDate={maxDate} />
        </div>

        {/* 右侧 1/6: 9 张子卡竖列 (滚动) */}
        <div className="grid grid-cols-1 gap-3 min-w-0 min-h-0 overflow-visible pr-0 md:overflow-y-auto md:pr-1">
          <RiskAppetiteCard date={date} />
          <MarketBreadthCard date={date} />
          <NewHigh252dCard date={date} />
          <SectorBreadthCard date={date} />
          <TurnoverActivityCard date={date} />
          <LimitEmotionCard date={date} />
          <VolatilitySentimentCard date={date} />
          <StyleRiskAppetiteCard date={date} />
          <ProfitEffectCard date={date} />
        </div>
      </div>
    </WorkspaceShell>
  )
}
