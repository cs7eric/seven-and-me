/** 本地时区日期工具 (避免 +8 时区下 toISOString / Date.UTC 回退一天).
 *
 * 业务约束:
 *   - A 股交易日期是 "日历日" (无时区), 用户在本地时区点选.
 *   - react-day-picker v10 默认 timezone=local, 选中的 Date 已经是本地 00:00.
 *   - 我们全程用本地时区方法 (getFullYear / getMonth / getDate), 不用 UTC, 避免
 *     选 6/18 落到 6/17 (北京时间 6/18 00:00 = UTC 6/17 16:00, 用 UTC 方法取日 → 17).
 *
 * 跟 backend trading_calendar 的 date 类型对齐: 都是日历日, 无时区信息.
 */

/** 把 YYYY-MM-DD 串 / Date 解析为本地 00:00 的 Date 对象. */
export function toLocalDate(v: string | Date | null | undefined): Date | undefined {
  if (v == null) return undefined
  if (v instanceof Date) {
    return Number.isNaN(v.getTime()) ? undefined : v
  }
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v)
  if (m) {
    // 本地 00:00 (不用 Date.UTC, 否则 +8 时区下回退一天)
    const d = new Date(+m[1], +m[2] - 1, +m[3])
    return Number.isNaN(d.getTime()) ? undefined : d
  }
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? undefined : d
}

/** Date (本地 00:00) -> "YYYY-MM-DD" 串 (本地年月日). */
export function toLocalIso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

/** "今天" (本地 00:00), 不用 new Date() (会带时分秒影响 disabled 比较). */
export function todayLocal(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}
