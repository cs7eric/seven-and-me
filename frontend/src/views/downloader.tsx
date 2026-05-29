import { Link } from "react-router-dom"
import { ArrowRight, Download, Sparkles } from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Button } from "@/components/ui/button"

export default function DownloaderPage() {
  return (
    <WorkspaceShell sectionLabel="Downloader" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Download className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Downloader
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            这是 downloader 的预留页面，后续可以接入媒体下载、来源管理、任务队列与批量处理能力。
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Input Sources</div>
          <p className="text-sm leading-6 text-muted-foreground">
            支持 URL、播放列表、渠道源和手动导入。
          </p>
        </div>
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Task Queue</div>
          <p className="text-sm leading-6 text-muted-foreground">
            预留并发下载、失败重试和进度反馈能力。
          </p>
        </div>
        <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
          <div className="mb-2 text-sm font-medium text-foreground">Output Pipeline</div>
          <p className="text-sm leading-6 text-muted-foreground">
            下载完成后可以继续进入转录或整理流程。
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
            当前为 mock 页面，占位完成后你后面就可以直接在这里填真实 downloader 业务。
          </p>
          <Button asChild className="rounded-xl">
            <Link to="/mp4-to-word">
              查看现有工作台
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </div>
    </WorkspaceShell>
  )
}
