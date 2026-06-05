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
  // 整张卡片的填充（用对应主题色 10% 透明，淡而不刺眼）
  cardBg: string
  // 卡片描边（对应主题色 30%）
  border: string
  // 图标徽章底色（对应主题色 25%，让 icon 在淡色卡片上更突出）
  badgeBg: string
  // 主题色（用于 icon / 标题 / 描述）
  text: string
  // 标题色（更深一档，确保可读性）
  titleText: string
  // 描述色（主题色降饱和）
  descText: string
  icon: ComponentType<{ className?: string }>
}

const VARIANT_STYLES: Record<NotificationVariant, VariantStyle> = {
  success: {
    cardBg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    badgeBg: "bg-emerald-500/25",
    text: "text-emerald-600",
    titleText: "text-emerald-700",
    descText: "text-emerald-700/80",
    icon: CheckCircle2,
  },
  info: {
    cardBg: "bg-blue-500/10",
    border: "border-blue-500/30",
    badgeBg: "bg-blue-500/25",
    text: "text-blue-600",
    titleText: "text-blue-700",
    descText: "text-blue-700/80",
    icon: Info,
  },
  warn: {
    cardBg: "bg-amber-500/10",
    border: "border-amber-500/30",
    badgeBg: "bg-amber-500/25",
    text: "text-amber-600",
    titleText: "text-amber-700",
    descText: "text-amber-700/80",
    icon: AlertTriangle,
  },
  danger: {
    cardBg: "bg-destructive/10",
    border: "border-destructive/30",
    badgeBg: "bg-destructive/25",
    text: "text-destructive",
    titleText: "text-destructive",
    descText: "text-destructive/80",
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
        "pointer-events-auto flex w-full min-w-[320px] items-start gap-3 rounded-2xl border p-3 shadow-lg backdrop-blur-sm",
        "animate-in slide-in-from-right-full fade-in-0 duration-300",
        styles.cardBg,
        styles.border,
      )}
    >
      <div
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-xl",
          styles.badgeBg,
        )}
      >
        <Icon className={cn("size-4", styles.text)} />
      </div>
      <div className="min-w-0 flex-1">
        <div className={cn("text-sm font-semibold", styles.titleText)}>
          {item.title}
        </div>
        {item.description ? (
          <div className={cn("mt-0.5 text-xs leading-5", styles.descText)}>
            {item.description}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => notification.dismiss(item.id)}
        className={cn(
          "shrink-0 rounded-md p-1 transition-colors hover:bg-black/5",
          styles.text,
        )}
        aria-label="关闭"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
