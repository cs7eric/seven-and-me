import { LineChart } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { OverviewCard } from "@/components/overview-card"
import { NextStepSection } from "./components/next-step-section"
import { overviewCards } from "./lib/content"

export default function StockReviewPage() {
  return (
    <WorkspaceShell sectionLabel="Stock Review" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <LineChart className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Stock Review
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            这是 stock review 的预留页面，后续可以接入复盘记录、主题判断、策略跟踪与决策日志。
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {overviewCards.map((item) => (
          <OverviewCard key={item.title} title={item.title} description={item.description} />
        ))}
      </div>

      <NextStepSection />
    </WorkspaceShell>
  )
}
