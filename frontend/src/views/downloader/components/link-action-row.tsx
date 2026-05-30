import { Check, Copy, ExternalLink } from "lucide-react"

import { Button } from "@/components/ui/button"
import { summarizeUrl } from "../lib/format"

export function LinkActionRow({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string
  value: string | null | undefined
  copied: boolean
  onCopy: (value: string) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-muted/25 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="truncate text-xs text-muted-foreground">
          {value ? summarizeUrl(value) : "当前没有可用链接"}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={!value} onClick={() => value && onCopy(value)}>
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          {copied ? "已复制" : "Copy"}
        </Button>
        <Button asChild size="sm" disabled={!value}>
          <a href={value || "#"} target="_blank" rel="noreferrer">
            <ExternalLink className="size-4" />
            Open
          </a>
        </Button>
      </div>
    </div>
  )
}
