/** 自选股 view 本地常量。 */

/** 分类可选颜色（key 是写入后端的 value，value 是 tailwind class 片段）。 */
export const GROUP_COLOR_OPTIONS = [
  { key: "blue", label: "Blue", dot: "bg-blue-500" },
  { key: "emerald", label: "Emerald", dot: "bg-emerald-500" },
  { key: "rose", label: "Rose", dot: "bg-rose-500" },
  { key: "amber", label: "Amber", dot: "bg-amber-500" },
  { key: "violet", label: "Violet", dot: "bg-violet-500" },
  { key: "cyan", label: "Cyan", dot: "bg-cyan-500" },
  { key: "pink", label: "Pink", dot: "bg-pink-500" },
  { key: "teal", label: "Teal", dot: "bg-teal-500" },
] as const

export type GroupColorKey = (typeof GROUP_COLOR_OPTIONS)[number]["key"]

/** 根据 color key 返回对应的 tailwind 文本 + 边框 + 背景组合。 */
export function getGroupColorClasses(color?: string | null): {
  text: string
  bg: string
  border: string
} {
  switch (color) {
    case "emerald":
      return { text: "text-emerald-600", bg: "bg-emerald-500/10", border: "border-emerald-500/30" }
    case "rose":
      return { text: "text-rose-600", bg: "bg-rose-500/10", border: "border-rose-500/30" }
    case "amber":
      return { text: "text-amber-600", bg: "bg-amber-500/10", border: "border-amber-500/30" }
    case "violet":
      return { text: "text-violet-600", bg: "bg-violet-500/10", border: "border-violet-500/30" }
    case "cyan":
      return { text: "text-cyan-600", bg: "bg-cyan-500/10", border: "border-cyan-500/30" }
    case "pink":
      return { text: "text-pink-600", bg: "bg-pink-500/10", border: "border-pink-500/30" }
    case "teal":
      return { text: "text-teal-600", bg: "bg-teal-500/10", border: "border-teal-500/30" }
    case "blue":
    default:
      return { text: "text-blue-600", bg: "bg-blue-500/10", border: "border-blue-500/30" }
  }
}

/** 市场徽章颜色。 */
export function getMarketClasses(market?: string | null): string {
  switch ((market || "").toUpperCase()) {
    case "SH":
      return "bg-rose-500/10 text-rose-600 border-rose-500/30"
    case "SZ":
      return "bg-emerald-500/10 text-emerald-600 border-emerald-500/30"
    case "HK":
      return "bg-amber-500/10 text-amber-600 border-amber-500/30"
    default:
      return "bg-muted text-muted-foreground border-border/30"
  }
}

/** 根据 symbol 前缀自动推断市场（用于搜索结果选中后自动填 market）。 */
export function inferMarketFromSymbol(symbol: string | undefined | null): "SH" | "SZ" | "HK" | "" {
  if (!symbol) return ""
  if (/^(60|68|69)\d{4}$/.test(symbol)) return "SH"
  if (/^(00|30)\d{4}$/.test(symbol)) return "SZ"
  // 港股：5 位数字，可能带前导 0（如 00700）
  if (/^0?\d{4,5}$/.test(symbol)) return "HK"
  return ""
}

/** target_type 中文标签（用于搜索结果徽章）。 */
export const TARGET_TYPE_LABEL: Record<string, string> = {
  stock: "个股",
  index: "指数",
  sector: "板块",
}
