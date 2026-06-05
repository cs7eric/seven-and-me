import { useState } from "react"
import { Trash2 } from "lucide-react"

import type { SelfSelectedItem } from "@/lib/api"
import { Button } from "@/components/ui/button"

import { ConfirmDialog } from "./confirm-dialog"
import { getMarketClasses } from "../lib/constants"

interface ItemRowProps {
  item: SelfSelectedItem
  pending: boolean
  onDelete: (itemId: string) => void | Promise<void>
}

export function ItemRow({ item, pending, onDelete }: ItemRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)

  const label = item.name ? `${item.symbol}（${item.name}）` : item.symbol

  return (
    <div className="group relative flex flex-col gap-1.5 rounded-2xl border border-border/30 bg-background/60 p-4 transition-all hover:border-border/60 hover:shadow-sm">
      <Button
        size="icon-sm"
        variant="ghost"
        className="absolute right-2 top-2 size-7 rounded-lg text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
        onClick={() => {
          if (pending) return
          setConfirmOpen(true)
        }}
        disabled={pending}
        aria-label="delete"
        title="删除"
      >
        <Trash2 className="size-3.5" />
      </Button>

      <div className="flex items-center gap-2 pr-8">
        <span className="font-mono text-base font-bold tracking-tight text-foreground">
          {item.symbol}
        </span>
        {item.market ? (
          <span
            className={`inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${getMarketClasses(item.market)}`}
          >
            {item.market}
          </span>
        ) : null}
      </div>

      {item.name ? (
        <div className="truncate pr-8 text-sm font-medium text-foreground">
          {item.name}
        </div>
      ) : (
        <div className="pr-8 text-xs italic text-muted-foreground/60">未命名</div>
      )}

      {item.notes ? (
        <div className="line-clamp-2 pr-8 text-xs leading-relaxed text-muted-foreground">
          {item.notes}
        </div>
      ) : null}

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
