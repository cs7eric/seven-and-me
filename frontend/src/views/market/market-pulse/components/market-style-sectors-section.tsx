import { useMemo } from "react"
import { Loader2, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { StyleSectorsHeatmap } from "./style-sectors-heatmap"
import type { StyleSectorItem } from "@/lib/api"

interface MarketStyleSectorsSectionProps {
  items: StyleSectorItem[]
  loading: boolean
  error: string | null
  fetchedAt: string | null
  onRefresh: () => void
  onCellClick: (name: string) => void
}

/**
 * 风格板块涨跌幅 section
 *
 * 用途: Market Pulse 第 4 区块. 标题 + refresh 按钮 + error 提示 + 420px
 *       固定高度 treemap 容器 (容器高度很关键, 不写 treemap canvas 高度就是 0).
 *
 * 来源: 之前是 market-pulse.tsx 主页内联 JSX (line ~659-706), 抽出来.
 *       排序 (按 change_pct desc) 保留在组件内, 跟原逻辑一致.
 */
export function MarketStyleSectorsSection({
  items,
  loading,
  error,
  fetchedAt,
  onRefresh,
  onCellClick,
}: MarketStyleSectorsSectionProps) {
  const sorted = useMemo(
    () => [...items].sort((a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity)),
    [items],
  )
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            风格板块涨跌幅
          </h2>
          <p className="text-sm leading-6 text-muted-foreground">
            29 个动态股票池, 等权平均涨跌幅 (TDX 风格板块口径)
            {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={onRefresh} disabled={loading}>
          {loading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          <span className="ml-1">Refresh</span>
        </Button>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          拉取失败: {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="h-[320px] w-full animate-pulse rounded-2xl border border-border/30 bg-muted/30 sm:h-[380px] lg:h-[420px]" />
      ) : (
        // **h-[420px] 固定高度父容器**: StyleSectorsHeatmap 内部用
        // flex h-full min-h-0 flex-col, h-full 一路吃高度到这里的 420px,
        // 才能让 treemap 拿到稳定 420-legend 高度的 canvas. 不写这个父级
        // h-[420px], heatmap 自己没高度, treemap canvas 就是 0, 渲染怪.
        <div className="h-[320px] sm:h-[380px] lg:h-[420px]">
          <StyleSectorsHeatmap
            items={sorted}
            loading={loading}
            onCellClick={onCellClick}
          />
        </div>
      )}
    </div>
  )
}
