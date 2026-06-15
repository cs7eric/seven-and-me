import { Gauge, LayoutDashboard } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { OverviewCard } from "@/components/overview-card"
import { NextStepSection } from "./components/next-step-section"
import { dashboardCards } from "./lib/content"

export default function DashboardPage() {
  return (
    <WorkspaceShell sectionLabel="Dashboard" pageTitle="Workspace Overview">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <LayoutDashboard className="size-3.5" />
          Dashboard
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Dashboard
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            跨应用的总览：MP4 转写、市场行情、调度任务、近期活动等关键指标集中展示。
            后续会按主题分区接入实时数据，先用静态卡片占位。
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {dashboardCards.map((item) => (
          <OverviewCard
            key={item.title}
            title={item.title}
            description={item.description}
          />
        ))}
      </div>

      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Gauge className="size-4" />
        数据接入占位
      </div>

      <NextStepSection />
    </WorkspaceShell>
  )
}
