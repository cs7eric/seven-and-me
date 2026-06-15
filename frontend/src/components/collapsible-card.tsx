import { ChevronDown, ChevronRight } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export interface CollapsibleCardProps {
  title: string
  description?: string
  icon?: LucideIcon
  badge?: string
  collapsed: boolean
  onToggle: () => void
  children: React.ReactNode
  className?: string
}

/**
 * 通用 CollapsibleCard · 可折叠卡
 *
 * 用途:
 *   - 任何需要"标题 + 折叠按钮 + 可选内容区"的卡片
 *   - icon / description / badge 全部可选
 *
 * 来源: 从 application-analysis/components/collapsible-card.tsx 抽出,
 * 原本在 application-analysis 内部 4 处复用, 现挪到公共目录.
 */
export function CollapsibleCard({
  title,
  description,
  icon: Icon,
  badge,
  collapsed,
  onToggle,
  children,
  className,
}: CollapsibleCardProps) {
  return (
    <Card
      className={`flex h-full min-h-0 flex-col rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)] ${className ?? ""}`}
    >
      <CardHeader className="shrink-0 pb-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            {Icon ? (
              <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                <Icon className="size-3.5" />
              </div>
            ) : null}
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <CardTitle className="truncate text-sm font-semibold text-slate-900">{title}</CardTitle>
                {badge ? (
                  <Badge className="rounded-full border-slate-200 bg-slate-100 px-2 py-0 text-[10px] text-slate-600" variant="outline">
                    {badge}
                  </Badge>
                ) : null}
              </div>
              {description ? <CardDescription className="mt-0.5 text-[11px] text-slate-500">{description}</CardDescription> : null}
             </div>
            </div>
            <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="size-7 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            onClick={onToggle}
            aria-label={collapsed ? `展开 ${title}` : `折叠 ${title}`}
          >
            {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </Button>
        </div>
      </CardHeader>
      {!collapsed ? (
        <CardContent className="flex min-h-0 flex-1 flex-col overflow-auto pt-0">{children}</CardContent>
      ) : null}
    </Card>
  )
}
