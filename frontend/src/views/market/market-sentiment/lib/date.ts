/**
 * ISO 日期工具 (本地时区).
 * 避免 +8 时区下 toISOString 回退一天.
 */
import { toLocalIso } from "@/lib/date-utils"

export function isoDateNDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return toLocalIso(d)
}

export function shiftIsoDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map((s) => parseInt(s, 10))
  // 本地 00:00, setDate 用本地方法避免跨月/跨年漂移
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + n)
  return toLocalIso(dt)
}