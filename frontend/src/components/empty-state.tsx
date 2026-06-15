import type { ReactNode } from "react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export interface EmptyStateProps {
  title: string
  description?: string
  /** 顶部小图标, 可选 */
  icon?: ReactNode
  /** 自定义内容, 例如一个 CTA 按钮; 传了就忽略默认的 CardDescription 渲染 */
  children?: ReactNode
  /** 是否用 Card 包裹, 默认 true; false 时退化为最简 div (无 border / shadow) */
  asCard?: boolean
}

/**
 * 通用 EmptyState · 空态 / 占位
 *
 * 用途:
 *   - 任何 Tab / 模块 "暂不适用" / "暂无数据" 的占位
 *   - 默认用 Card 包裹, 视觉与项目内其他卡一致
 *
 * 来源: 统一了 industry-application 的 `NotApplicableCard`
 *         和 stock-overview/mock-market 的 `EmptyCard`,
 *       两份 props 几乎相同 (一个用 description, 一个用 desc), 这里统一用 description.
 */
export function EmptyState({
  title,
  description,
  icon,
  children,
  asCard = true,
}: EmptyStateProps) {
  if (!asCard) {
    return (
      <div className="px-4 py-8 text-center text-sm text-slate-500">
        {title}
        {description ? <div className="mt-1 text-xs">{description}</div> : null}
      </div>
    )
  }
  return (
    <Card className="overflow-hidden rounded-2xl border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.045)]">
      <CardHeader>
        {icon ? (
          <div className="mb-2 flex size-8 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            {icon}
          </div>
        ) : null}
        <CardTitle className="text-base text-slate-900">{title}</CardTitle>
        {description ? (
          <CardDescription className="text-sm text-slate-500">{description}</CardDescription>
        ) : null}
      </CardHeader>
      {children ? <CardContent>{children}</CardContent> : null}
    </Card>
  )
}
