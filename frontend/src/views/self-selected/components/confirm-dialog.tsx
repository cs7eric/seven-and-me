import { useState, type ReactNode } from "react"
import { AlertTriangle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  /** 弹窗顶部小图标（默认 destructive 时给 AlertTriangle） */
  icon?: ReactNode
  /** 触发 onConfirm 时是否展示 loading；onConfirm 返回 Promise 时会等 */
  onConfirm: () => void | Promise<void>
  confirmText?: string
  cancelText?: string
  /** destructive=true 时按钮变红、icon 变 AlertTriangle */
  destructive?: boolean
  /** 父组件控制的 pending（比如网络请求中），会一起 disable 两个按钮 */
  pending?: boolean
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  icon,
  onConfirm,
  confirmText = "确认",
  cancelText = "取消",
  destructive = false,
  pending = false,
}: ConfirmDialogProps) {
  const [internalPending, setInternalPending] = useState(false)
  const busy = pending || internalPending

  const handleConfirm = async () => {
    if (busy) return
    setInternalPending(true)
    try {
      await onConfirm()
      onOpenChange(false)
    } catch {
      // 让调用方自己处理 error（toast 等），这里只关掉 loading
    } finally {
      setInternalPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <div className="flex items-start gap-3">
            {icon !== null ? (
              <div
                className={cn(
                  "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full",
                  destructive
                    ? "bg-destructive/10 text-destructive"
                    : "bg-muted text-foreground",
                )}
              >
                {icon ?? (
                  <AlertTriangle className="size-4" />
                )}
              </div>
            ) : null}
            <div className="min-w-0 flex-1 space-y-1.5">
              <DialogTitle>{title}</DialogTitle>
              {description ? (
                <DialogDescription>{description}</DialogDescription>
              ) : null}
            </div>
          </div>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            {cancelText}
          </Button>
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={busy}
          >
            {busy ? "处理中…" : confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
