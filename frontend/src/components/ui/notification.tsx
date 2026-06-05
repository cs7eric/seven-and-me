/**
 * 项目级 Notification / Message 组件。
 *
 * 4 个 variant，对齐项目的颜色 token（border / bg / text 都用项目里 `bg-*-500/10` / `text-*-600` 这套）：
 * - success  → emerald   (绿)
 * - info     → blue      (蓝)
 * - warn     → amber     (黄)
 * - danger   → destructive (红，用项目语义色)
 *
 * 用法：
 * ```tsx
 * // 1) 在应用根（WorkspaceShell）放一次：
 * <NotificationRoot />
 *
 * // 2) 业务代码里直接调：
 * import { notification } from "@/components/ui/notification"
 * notification.success({ title: "已保存", description: "..." })
 * notification.danger({ title: "出错了", description: err.message })
 * notification.dismiss(id)
 * ```
 *
 * 用 React 18 的 `createPortal` 渲到 `document.body`，避免被父级 `overflow-hidden` 裁掉。
 */
import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react"

import { cn } from "@/lib/utils"

export type NotificationVariant = "success" | "info" | "warn" | "danger"

export interface NotificationItem {
  id: string
  variant: NotificationVariant
  title: string
  description?: ReactNode
  duration?: number
}

interface VariantStyle {
  border: string
  bg: string
  text: string
  icon: ComponentType<{ className?: string }>
}

const VARIANT_STYLES: Record<NotificationVariant, VariantStyle> = {
  success: {
    border: "border-emerald-500/30",
    bg: "bg-emerald-500/10",
    text: "text-emerald-600",
    icon: CheckCircle2,
  },
  info: {
    border: "border-blue-500/30",
    bg: "bg-blue-500/10",
    text: "text-blue-600",
    icon: Info,
  },
  warn: {
    border: "border-amber-500/30",
    bg: "bg-amber-500/10",
    text: "text-amber-600",
    icon: AlertTriangle,
  },
  danger: {
    border: "border-destructive/30",
    bg: "bg-destructive/10",
    text: "text-destructive",
    icon: AlertCircle,
  },
}

const DEFAULT_DURATION_MS = 4000

// ---------------------------------------------------------------------------
// singleton state（不依赖 Provider / context，业务代码直接 import 就能用）
// ---------------------------------------------------------------------------

let counter = 0
let store: NotificationItem[] = []
const listeners = new Set<(items: NotificationItem[]) => void>()

function emit() {
  const snapshot = [...store]
  listeners.forEach((l) => l(snapshot))
}

function push(
  variant: NotificationVariant,
  opts: { title: string; description?: ReactNode; duration?: number },
): string {
  const id = `notif-${Date.now()}-${counter++}`
  const item: NotificationItem = {
    id,
    variant,
    title: opts.title,
    description: opts.description,
    duration: opts.duration ?? DEFAULT_DURATION_MS,
  }
  store = [...store, item]
  emit()
  if (item.duration && item.duration > 0) {
    setTimeout(() => {
      store = store.filter((i) => i.id !== id)
      emit()
    }, item.duration)
  }
  return id
}

export interface NotificationApi {
  success: (opts: { title: string; description?: ReactNode; duration?: number }) => string
  info: (opts: { title: string; description?: ReactNode; duration?: number }) => string
  warn: (opts: { title: string; description?: ReactNode; duration?: number }) => string
  danger: (opts: { title: string; description?: ReactNode; duration?: number }) => string
  dismiss: (id: string) => void
  dismissAll: () => void
}

export const notification: NotificationApi = {
  success: (opts) => push("success", opts),
  info: (opts) => push("info", opts),
  warn: (opts) => push("warn", opts),
  danger: (opts) => push("danger", opts),
  dismiss: (id) => {
    store = store.filter((i) => i.id !== id)
    emit()
  },
  dismissAll: () => {
    store = []
    emit()
  },
}

// ---------------------------------------------------------------------------
// root component：渲染到 document.body
// ---------------------------------------------------------------------------

export function NotificationRoot() {
  const [items, setItems] = useState<NotificationItem[]>([])

  useEffect(() => {
    const handler = (next: NotificationItem[]) => setItems(next)
    listeners.add(handler)
    // 初始化同步（处理 hot reload / 二次挂载时 store 已有内容的情况）
    setItems([...store])
    return () => {
      listeners.delete(handler)
    }
  }, [])

  if (typeof document === "undefined") return null

  return createPortal(
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed top-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
    >
      {items.map((item) => (
        <NotificationCard key={item.id} item={item} />
      ))}
    </div>,
    document.body,
  )
}

// ---------------------------------------------------------------------------
// single card
// ---------------------------------------------------------------------------

function NotificationCard({ item }: { item: NotificationItem }) {
  const styles = VARIANT_STYLES[item.variant]
  const Icon = styles.icon

  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto flex items-start gap-3 rounded-2xl border bg-card/95 p-3 shadow-lg backdrop-blur-sm",
        "animate-in slide-in-from-right-full fade-in-0 duration-300",
        styles.border,
      )}
    >
      <div
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-xl",
          styles.bg,
        )}
      >
        <Icon className={cn("size-4", styles.text)} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-foreground">{item.title}</div>
        {item.description ? (
          <div className="mt-0.5 text-xs leading-5 text-muted-foreground">
            {item.description}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => notification.dismiss(item.id)}
        className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="关闭"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
