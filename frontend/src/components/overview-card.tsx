export interface OverviewCardProps {
  title: string
  description: string
}

/**
 * 通用 OverviewCard · 占位 / 简介型卡片
 *
 * 用途:
 *   - 任何需要展示"标题 + 一行描述"的静态占位卡
 *   - 早期版本散落在 dashboard / stock-review 两份完全相同的副本,
 *     现统一抽到 src/components/ 公共目录.
 *
 * 区别于 application-analysis/components/overview-card.tsx:
 *   那个是"分析概览"复合卡 (内部拼 4 个 MetricCard), 命名空间隔离,
 *   不会被本组件替换.
 */
export function OverviewCard({ title, description }: OverviewCardProps) {
  return (
    <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
      <div className="mb-2 text-sm font-medium text-foreground">{title}</div>
      <p className="text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  )
}
