/**
 * 9 张子卡 / 合成大卡 loading 占位.
 * 标题/描述保留静态, 内容用 skeleton 摆出真实布局轮廓.
 */
import { Activity, Smile } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import DogLoader from "@/components/loader/dog-loader"

// 9 张子卡 loading 占位
export function SubCardSkeleton() {
  return (
    <div className="space-y-3">
      {/* 大数字 + 分母 */}
      <div className="flex items-baseline gap-2">
        <Skeleton className="h-9 w-16 bg-foreground/10" />
        <Skeleton className="h-3.5 w-24 bg-foreground/10" />
      </div>
      {/* 副标题 (raw value / spread 等) */}
      <Skeleton className="h-3.5 w-3/4 bg-foreground/10" />
      {/* sparkline */}
      <Skeleton className="h-[60px] w-full bg-foreground/10" />
      {/* 阈值说明 */}
      <Skeleton className="h-3 w-2/3 bg-foreground/10" />
    </div>
  )
}

// 合成指数大卡 loading 占位: 静态文字直接渲染, 折线区中央 DogLoader
export function CompositeCardSkeleton() {
  return (
    <div className="grid h-full grid-rows-[3fr_1fr] gap-3">
      <div className="flex min-h-0 flex-col gap-3">
        {/* chip: Market Sentiment */}
        <div className="inline-flex items-center gap-2 rounded-full bg-background px-3 py-1 text-xs font-medium text-muted-foreground self-start">
          <Smile className="size-3.5" />
          Market Sentiment
        </div>
        {/* score 行: 大数字 + /100 + 中性 chip + 日期 (静态文字, 数字位置用 skeleton) */}
        <div className="flex items-end gap-3">
          <span className="text-5xl font-semibold tabular-nums text-muted-foreground/40">—</span>
          <span className="text-xs text-muted-foreground">/ 100</span>
          <span className="ml-1 rounded-full border border-border/60 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            —
          </span>
          <span className="ml-1 inline-flex items-center text-xs text-muted-foreground tabular-nums">
            —
          </span>
        </div>
        {/* 描述行 */}
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Activity className="size-3.5" />
          <span>实时情绪指标</span>
          <span className="text-red-600/70">≥70 极热</span>
          <span className="text-orange-600/70">60-70 偏热</span>
          <span className="text-amber-600/70">50-60 偏多</span>
          <span className="text-sky-500/80">40-50 偏弱</span>
          <span className="text-blue-600/70">30-40 低迷</span>
          <span className="text-slate-400">＜30 冰点</span>
          <span className="text-border">·</span>
          <span className="text-xs">顶部 1 张合成指数 + 9 张子卡 / duckdb 持久化 / 工作日自动更新</span>
        </div>
        {/* 折线区: DogLoader 居中 */}
        <div className="relative min-h-0 flex-1 rounded-md border border-border/30 bg-background overflow-hidden">
          <div className="absolute inset-0 flex items-center justify-center">
            <DogLoader size={50} label="loading" />
          </div>
        </div>
      </div>
      {/* 下方 1/4 占位 */}
      <Skeleton className="min-h-0 rounded-xl bg-foreground/10" />
    </div>
  )
}