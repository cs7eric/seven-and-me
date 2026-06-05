import { Plus } from "lucide-react"

import { cn } from "@/lib/utils"

interface AddItemTileProps {
  onClick: () => void
  /** 用于边框 / 高亮颜色，比如跟随 group 的 color */
  accentClass?: string
  className?: string
  label?: string
}

/** items 网格里的"占位加号"tile，点开 CreateItemDialog。 */
export function AddItemTile({
  onClick,
  accentClass = "border-border/40",
  className,
  label = "加入自选",
}: AddItemTileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex min-h-[112px] flex-col items-center justify-center gap-1.5 rounded-2xl border-2 border-dashed bg-muted/15 p-4 text-muted-foreground transition-all",
        "hover:border-solid hover:border-border/60 hover:bg-muted/40 hover:text-foreground hover:shadow-sm",
        "active:scale-[0.99]",
        accentClass,
        className,
      )}
    >
      <div className="flex size-8 items-center justify-center rounded-full border border-current/30 bg-background/60 transition-transform group-hover:scale-110">
        <Plus className="size-4" />
      </div>
      <span className="text-sm font-medium">{label}</span>
    </button>
  )
}
