import { Link } from "react-router-dom"
import {
  ArrowRight,
  Download,
  FileText,
  LineChart,
  Sparkles,
  TrendingUp,
} from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Button } from "@/components/ui/button"

const applications = [
  {
    name: "Downloader",
    description: "统一管理媒体下载、批量任务与来源链接整理。",
    href: "/downloader",
    icon: Download,
  },
  {
    name: "MP4 to Word",
    description: "将音视频内容转换为 Transcript、Polish、Summary 与结构化问答。",
    href: "/mp4-to-word",
    icon: FileText,
  },
  {
    name: "Stock Overview",
    description: "识别市场所处阶段，查看区间定位、支撑压力、风格轮动与历史相似情景。",
    href: "/stock-overview",
    icon: TrendingUp,
  },
  {
    name: "Stock Review",
    description: "沉淀股票复盘、观点记录与后续策略观察的工作流。",
    href: "/stock-review",
    icon: LineChart,
  },
]

export default function HomePage() {
  return (
    <WorkspaceShell sectionLabel="Application Hub" pageTitle="Workspace Home">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="size-3.5" />
          Application Hub
        </div>
      </div>

      <div className="grid auto-rows-min gap-4 md:grid-cols-3">
        {applications.map((application) => {
          const Icon = application.icon

          return (
            <Link
              key={application.name}
              to={application.href}
              className="group flex aspect-video flex-col justify-between rounded-2xl border border-border/25 bg-muted/35 p-5 transition-colors hover:bg-muted/55"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex size-10 items-center justify-center rounded-xl bg-background/80 text-foreground shadow-sm shadow-black/5">
                  <Icon className="size-5" />
                </div>
                <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">
                  {application.name}
                </div>
                <p className="text-sm leading-6 text-muted-foreground">
                  {application.description}
                </p>
              </div>
            </Link>
          )
        })}
      </div>

      <div className="flex-1 bg-muted/35 rounded-2xl border border-border/25 p-6">
        <div className="mx-auto flex h-full max-w-5xl flex-col justify-between gap-8">
          <div className="space-y-4">
            <div className="inline-flex rounded-full bg-background/80 px-3 py-1 text-xs font-medium text-muted-foreground">
              Featured Workspace
            </div>
            <div className="space-y-3">
              <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
                MP4 to Word Workspace
              </h2>
              <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
                当前主力工作区已经具备完整流程：上传、转录、AI polish、AI summary、
                Ask AI 与导出。其余 application 先以 mock 页面占位，方便后续逐步接入真实功能。
              </p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
            <div className="rounded-2xl border border-border/25 bg-background/70 p-5 shadow-sm shadow-black/5">
              <div className="mb-3 text-sm font-medium text-foreground">Workflow</div>
              <div className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
                <div className="rounded-xl bg-muted/50 p-4">Upload → Transcribe</div>
                <div className="rounded-xl bg-muted/50 p-4">Polish → Summary</div>
                <div className="rounded-xl bg-muted/50 p-4">Ask AI structured answer</div>
                <div className="rounded-xl bg-muted/50 p-4">Export / Read mode / Copy</div>
              </div>
            </div>

            <div className="rounded-2xl border border-border/25 bg-background/70 p-5 shadow-sm shadow-black/5">
              <div className="mb-2 text-sm font-medium text-foreground">Open Tool</div>
              <p className="mb-5 text-sm leading-6 text-muted-foreground">
                进入当前可用的核心业务页面。
              </p>
              <Button asChild className="w-full rounded-xl">
                <Link to="/mp4-to-word">
                  进入工作台
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </WorkspaceShell>
  )
}
