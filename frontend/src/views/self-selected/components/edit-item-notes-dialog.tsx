import { useEffect, useState } from "react"

import type { SelfSelectedItem } from "@/services/market/self-selected"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"

interface EditItemNotesDialogProps {
  open: boolean
  item: SelfSelectedItem | null
  pending?: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: { notes?: string }) => Promise<void>
}

export function EditItemNotesDialog({
  open,
  item,
  pending = false,
  onOpenChange,
  onSubmit,
}: EditItemNotesDialogProps) {
  const [notes, setNotes] = useState("")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      const timer = window.setTimeout(() => {
        setNotes(item?.notes || "")
        setError(null)
      }, 0)
      return () => window.clearTimeout(timer)
    }
    return undefined
  }, [open, item])

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError(null)
    try {
      await onSubmit({ notes: notes.trim() || undefined })
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存备注失败")
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>编辑备注</DialogTitle>
            <DialogDescription>
              {item ? `为 ${item.name || item.symbol} 添加或更新备注。` : "更新这只自选股的备注。"}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="edit-item-notes">备注</Label>
            <textarea
              id="edit-item-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="例如：观察支撑位、行业催化、入场逻辑"
              rows={4}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>
              取消
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "保存中…" : "保存备注"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
