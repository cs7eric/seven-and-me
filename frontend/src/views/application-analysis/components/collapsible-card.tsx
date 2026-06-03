import { ChevronDown, ChevronRight } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function CollapsibleCard({
  title,
  description,
  icon: Icon,
  badge,
  collapsed,
  onToggle,
  children,
}: {
  title: string
  description?: string
  icon?: LucideIcon
  badge?: string
  collapsed: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <Card className="rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)]">
      <CardHeader className="pb-3">
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
      {!collapsed ? <CardContent className="pt-0">{children}</CardContent> : null}
    </Card>
  )
}
