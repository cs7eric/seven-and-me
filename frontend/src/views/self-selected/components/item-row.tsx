import { useState } from "react"
import { Trash2, ChevronRight, FileEdit, Compass } from "lucide-react"
import { useNavigate } from "react-router-dom"

import type { SelfSelectedItem } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getMarketClasses, getMarketAccentClasses } from "../lib/constants"

interface ItemRowProps {
  item: SelfSelectedItem
  pending: boolean
  /** group 颜色，决定左侧 accent bar 的色调（blue/rose/amber...） */
  accentBgClass?: string
  /** 当前 symbol 已加入「应用分析」targets */
  inAnalysis?: boolean
  onDelete: (itemId: string) => void | Promise<void>
  onEdit?: (item: SelfSelectedItem) => void
}

export function ItemRow({
  item,
  pending,
  accentBgClass = "bg-blue-500/70",
  inAnalysis = false,
  onDelete,
  onEdit,
}: ItemRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const navigate = useNavigate()

  const label = item.name ? `${item.symbol}（${item.name}）` : item.symbol
  const market = (item.market || "").toUpperCase()
  const marketBadge = getMarketClasses(market)
  const marketAccent = getMarketAccentClasses(market)

  // 点击卡片任意空白处 → 跳到 application-analysis 页面，并把当前股票以
  // query string 带过去；该页面会按 symbol 自动定位 / 添加到 targets
  const goToChart = () => {
    const params = new URLSearchParams({
      target_type: item.target_type || (market === "HK" ? "hk_stock" : "stock"),
      symbol: item.symbol,
      name: item.name || item.symbol,
      market: market,
    })
    navigate(`/stock-overview/application-analysis?${params.toString()}`)
  }

  // 删除按钮：阻止冒泡，不触发卡片跳转
  const openDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (pending) return
    setConfirmOpen(true)
  }

  const openEdit = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (pending) return
    onEdit?.(item)
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      goToChart()
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={goToChart}
      onKeyDown={handleKey}
      aria-label={`分析 ${item.symbol} ${item.name ?? ""} 的应用面`}
      className={cn(
        "group relative flex w-full cursor-pointer items-stretch overflow-hidden rounded-2xl border border-border/40 bg-card text-left",
        "transition-all duration-150",
        "hover:-translate-y-0.5 hover:border-border/70 hover:shadow-md hover:shadow-black/5",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
        pending && "pointer-events-none opacity-60",
      )}
    >
      {/* 左侧 accent bar：group 主题色（用 accentBgClass），未识别市场时回退到 group 主题色 */}
      <div
        className={cn(
          "w-1 shrink-0 transition-colors duration-150",
          accentBgClass,
          "group-hover:opacity-100",
        )}
        aria-hidden
      />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-3.5">
        {/* code + market badge row */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-[15px] font-bold tracking-tight text-foreground">
            {item.symbol}
          </span>
          {market ? (
            <span
              className={cn(
                "inline-flex h-5 items-center rounded border px-1.5 font-mono text-[10px] font-bold tracking-wider",
                marketBadge,
              )}
            >
              {market}
            </span>
          ) : null}
          {inAnalysis ? (
            <span
              className="inline-flex h-5 items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 text-[10px] font-medium text-emerald-700"
              title="已加入应用分析 targets"
            >
              <Compass className="size-3" />
              已加入
            </span>
          ) : null}
          {/* hover 时在右侧出现的箭头，提示可点击 */}
          <ChevronRight
            className="ml-auto size-3.5 shrink-0 text-muted-foreground/0 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-muted-foreground"
            aria-hidden
          />
        </div>

        {/* 股票名 */}
        {item.name ? (
          <div className="truncate pr-1 text-sm font-medium text-foreground/85">
            {item.name}
          </div>
        ) : (
          <div className="pr-1 text-xs italic text-muted-foreground/50">未命名</div>
        )}

        {/* 备注 / 行业提示 */}
        {item.notes ? (
          <div className="line-clamp-2 pr-1 text-xs leading-relaxed text-muted-foreground/75">
            {item.notes}
          </div>
        ) : null}

        {/* 底部：market 主题色横条，弱化但有辨识度 */}
        {market ? (
          <div
            className={cn("mt-1 h-0.5 w-10 rounded-full", marketAccent)}
            aria-hidden
          />
        ) : null}
      </div>

      {/* hover 时浮出的操作按钮组（绝对定位右上） */}
      <div className="pointer-events-none absolute right-1.5 top-1.5 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100">
        {onEdit ? (
          <Button
            size="icon-sm"
            variant="ghost"
            className="size-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={openEdit}
            disabled={pending}
            aria-label="编辑备注"
            title="编辑备注"
          >
            <FileEdit className="size-3.5" />
          </Button>
        ) : null}
        <Button
          size="icon-sm"
          variant="ghost"
          className="size-7 rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          onClick={openDelete}
          disabled={pending}
          aria-label="删除"
          title="删除"
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="从分类中移除"
        description={
          <>
            确定要把 <span className="font-mono font-semibold text-foreground">{label}</span>{" "}
            从这个分类中移除吗？
          </>
        }
        confirmText="移除"
        destructive
        pending={pending}
        onConfirm={() => onDelete(item.id)}
      />
    </div>
  )
}
