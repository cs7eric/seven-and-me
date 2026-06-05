import { ArrowRight, FileText, LineChart, Settings, Sparkles } from "lucide-react"
import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"

const steps = [
  {
    icon: LineChart,
    title: "Stock Workspace",
    description: "查看今日 A 股市场情绪、行业轮动与历史相似情景。",
    href: "/stock-overview",
  },
  {
    icon: FileText,
    title: "MP4 to Word",
    description: "上传音频 / 视频，自动转写 + AI Polish + 导出 Markdown。",
    href: "/mp4-to-word",
  },
  {
    icon: Settings,
    title: "Settings · Scheduler",
    description: "查看 / 启停 / 触发所有调度任务，实时监控状态。",
    href: "/settings/scheduler",
  },
]

export function NextStepSection() {
  return (
    <div className="rounded-2xl border border-border/30 bg-muted/30 p-6">
      <div className="mb-5 flex items-center gap-2">
        <Sparkles className="size-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          下一步
        </h2>
        <span className="text-xs text-muted-foreground">
          常用入口 · 跳转到对应功能
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((step) => {
          const Icon = step.icon
          return (
            <Link
              key={step.title}
              to={step.href}
              className="group flex items-start gap-3 rounded-xl border border-border/25 bg-background/60 p-4 transition-colors hover:bg-muted/60"
            >
              <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
                <Icon className="size-4" />
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="text-sm font-medium text-foreground">
                  {step.title}
                </div>
                <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {step.description}
                </p>
              </div>
              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>
          )
        })}
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <Button asChild variant="outline" className="rounded-xl">
          <Link to="/stock-overview">
            <LineChart className="size-4" />
            打开市场概览
          </Link>
        </Button>
        <Button asChild className="rounded-xl">
          <Link to="/mp4-to-word">
            <FileText className="size-4" />
            立即转写
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </div>
    </div>
  )
}
