import { Link } from "react-router-dom"
import { ArrowRight, LineChart, Sparkles } from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Button } from "@/components/ui/button"

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
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Review Notes</div>
          <p className="text-sm leading-6 text-muted-foreground">
            汇总当日市场观察、个股行为与板块脉络。
          </p>
        </div>
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Decision Log</div>
          <p className="text-sm leading-6 text-muted-foreground">
            记录买卖原因、执行结果与复盘反馈。
          </p>
        </div>
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Watchlist</div>
          <p className="text-sm leading-6 text-muted-foreground">
            预留观察池、风险提示和后续跟踪计划。
          </p>
        </div>
      </div>

      <div className="rounded-3xl border border-border/30 bg-background p-6 shadow-sm shadow-black/5">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="size-3.5" />
          Next Step
        </div>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
            这个 mock 页面已经准备好承接后续真实模块，风格上会和 Home / Sidebar 保持一致。
          </p>
          <Button asChild className="rounded-xl">
            <Link to="/">
              返回应用总览
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </div>
    </WorkspaceShell>
  )
}
