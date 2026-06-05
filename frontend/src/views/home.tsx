import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  ArrowRight,
  AudioWaveform,
  Download,
  FileText,
  LineChart,
  Settings,
  Sparkles,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Button } from "@/components/ui/button"

interface ApplicationItem {
  name: string
  description: string
  href: string
  icon: LucideIcon
  gradient: string
  illustration: ReactNode
}

interface SectionItem {
  key: string
  title: string
  description: string
  icon: LucideIcon
  items: ApplicationItem[]
}

const svgBase = {
  viewBox: "0 0 100 100",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: "size-full",
}

// ---- 每个 app 的专属插画（手画 SVG） ----

const DownloaderIllustration = (
  <svg {...svgBase}>
    {/* 三道进度条 */}
    <rect x="14" y="20" width="52" height="7" rx="3.5" fill="currentColor" stroke="none" opacity="0.55" />
    <rect x="14" y="34" width="40" height="7" rx="3.5" fill="currentColor" stroke="none" opacity="0.42" />
    <rect x="14" y="48" width="24" height="7" rx="3.5" fill="currentColor" stroke="none" opacity="0.3" />
    {/* 下载箭头 */}
    <path d="M 74 58 L 74 84" />
    <path d="M 62 72 L 74 84 L 86 72" />
  </svg>
)

const Mp4ToWordIllustration = (
  <svg {...svgBase}>
    {/* 视频框 */}
    <rect x="12" y="22" width="56" height="56" rx="5" opacity="0.22" />
    {/* play 三角 */}
    <polygon points="34,40 34,60 56,50" fill="currentColor" stroke="none" opacity="0.65" />
    {/* 右侧文本线 */}
    <line x1="74" y1="32" x2="90" y2="32" opacity="0.45" />
    <line x1="74" y1="48" x2="88" y2="48" opacity="0.38" />
    <line x1="74" y1="64" x2="84" y2="64" opacity="0.3" />
  </svg>
)

const StockOverviewIllustration = (
  <svg {...svgBase}>
    {/* 底轴 */}
    <line x1="8" y1="85" x2="92" y2="85" opacity="0.35" />
    {/* 柱状图 */}
    <rect x="14" y="55" width="11" height="30" fill="currentColor" stroke="none" opacity="0.45" />
    <rect x="32" y="38" width="11" height="47" fill="currentColor" stroke="none" opacity="0.6" />
    <rect x="50" y="48" width="11" height="37" fill="currentColor" stroke="none" opacity="0.48" />
    <rect x="68" y="26" width="11" height="59" fill="currentColor" stroke="none" opacity="0.72" />
  </svg>
)

const StockReviewIllustration = (
  <svg {...svgBase}>
    {/* 文档框 */}
    <rect x="20" y="22" width="56" height="64" rx="5" opacity="0.2" />
    {/* 顶部夹子 */}
    <rect x="36" y="14" width="24" height="14" rx="3" opacity="0.5" />
    {/* 文本行 */}
    <line x1="30" y1="42" x2="66" y2="42" opacity="0.42" />
    <line x1="30" y1="54" x2="60" y2="54" opacity="0.36" />
    <line x1="30" y1="66" x2="55" y2="66" opacity="0.3" />
    <line x1="30" y1="78" x2="48" y2="78" opacity="0.24" />
  </svg>
)

const SettingsIllustration = (
  <svg {...svgBase}>
    {/* 中心圆 + 内核 */}
    <circle cx="50" cy="50" r="17" opacity="0.5" />
    <circle cx="50" cy="50" r="3.5" fill="currentColor" stroke="none" opacity="0.65" />
    {/* 八条齿轮射线 */}
    <line x1="50" y1="20" x2="50" y2="33" opacity="0.5" />
    <line x1="50" y1="67" x2="50" y2="80" opacity="0.5" />
    <line x1="20" y1="50" x2="33" y2="50" opacity="0.5" />
    <line x1="67" y1="50" x2="80" y2="50" opacity="0.5" />
    <line x1="29" y1="29" x2="38" y2="38" opacity="0.42" />
    <line x1="62" y1="62" x2="71" y2="71" opacity="0.42" />
    <line x1="71" y1="29" x2="62" y2="38" opacity="0.42" />
    <line x1="38" y1="62" x2="29" y2="71" opacity="0.42" />
  </svg>
)

const sections: SectionItem[] = [
  {
    key: "media-tools",
    title: "Media Tools",
    description: "音视频下载、转写与文档化工作流。",
    icon: AudioWaveform,
    items: [
      {
        name: "Downloader",
        description: "统一管理媒体下载、批量任务与来源链接整理。",
        href: "/downloader",
        icon: Download,
        gradient: "from-sky-500/10 via-cyan-500/5 to-transparent",
        illustration: DownloaderIllustration,
      },
      {
        name: "MP4 to Word",
        description: "将音视频内容转换为 Transcript、Polish、Summary 与结构化问答。",
        href: "/mp4-to-word",
        icon: FileText,
        gradient: "from-violet-500/10 via-fuchsia-500/5 to-transparent",
        illustration: Mp4ToWordIllustration,
      },
    ],
  },
  {
    key: "stock-workspace",
    title: "Stock Workspace",
    description: "行情、复盘与策略观察的统一入口。",
    icon: TrendingUp,
    items: [
      {
        name: "Stock Overview",
        description: "识别市场所处阶段，查看区间定位、支撑压力、风格轮动与历史相似情景。",
        href: "/stock-overview",
        icon: TrendingUp,
        gradient: "from-emerald-500/10 via-teal-500/5 to-transparent",
        illustration: StockOverviewIllustration,
      },
      {
        name: "Stock Review",
        description: "沉淀股票复盘、观点记录与后续策略观察的工作流。",
        href: "/stock-review",
        icon: LineChart,
        gradient: "from-amber-500/10 via-orange-500/5 to-transparent",
        illustration: StockReviewIllustration,
      },
    ],
  },
  {
    key: "settings",
    title: "Settings",
    description: "系统级入口与调度任务管理。",
    icon: Settings,
    items: [
      {
        name: "Settings · Scheduler",
        description: "统一管理所有调度任务：实时状态、启停、手动触发。",
        href: "/settings/scheduler",
        icon: Settings,
        gradient: "from-slate-500/10 via-zinc-500/5 to-transparent",
        illustration: SettingsIllustration,
      },
    ],
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

      <div className="flex flex-col gap-5">
        {sections.map((section) => {
          const SectionIcon = section.icon
          return (
            <div key={section.key} className="mx-auto w-4/5 space-y-2">
              <div className="flex items-center gap-2 px-1">
                <SectionIcon className="size-3.5 text-muted-foreground" />
                <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {section.title}
                </div>
                <span className="text-xs text-muted-foreground/60">
                  · {section.items.length}
                </span>
              </div>
              <div className="grid auto-rows-min gap-3 md:grid-cols-2 xl:grid-cols-4">
                {section.items.map((application) => {
                  const Icon = application.icon
                  return (
                    <Link
                      key={application.name}
                      to={application.href}
                      className={`group relative flex aspect-[5/2] flex-col justify-between overflow-hidden rounded-2xl border border-border/25 bg-gradient-to-br ${application.gradient} p-4 transition-all hover:shadow-md`}
                    >
                      {/* 背景插画 */}
                      <div className="pointer-events-none absolute inset-y-0 right-0 w-3/5 text-foreground/20 transition-colors group-hover:text-foreground/30">
                        {application.illustration}
                      </div>
                      {/* 主体内容 */}
                      <div className="relative z-10 flex items-start justify-between gap-2">
                        <div className="flex size-8 items-center justify-center rounded-lg bg-background/80 text-foreground shadow-sm shadow-black/5 backdrop-blur-sm">
                          <Icon className="size-4" />
                        </div>
                        <ArrowRight className="size-3.5 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground" />
                      </div>
                      <div className="relative z-10 space-y-1">
                        <div className="truncate text-sm font-medium text-foreground">
                          {application.name}
                        </div>
                        <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
                          {application.description}
                        </p>
                      </div>
                    </Link>
                  )
                })}
              </div>
            </div>
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
