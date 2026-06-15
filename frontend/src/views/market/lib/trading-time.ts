/**
 * 客户端 A 股交易日 / 交易时段判定 (只处理周末; 节假日由后端 overview.tradingDate 覆盖)
 *
 * **使用场景**: overview API 还没回来 / 失败时, 给 IndexKlineDeck 一个"非空"的兜底,
 * 避免 deck 顶部 pill 错误显示 "今日实时 1m" 并且把请求的 date 钉到"今天".
 * 真实节假日会让周末 fallback 给个非交易日日期, 此时后端 overview 一旦回来就会用
 * ``overview.tradingDate`` (上一个真正交易日) 覆盖.
 */

/** Date → 本地时区的 YYYY-MM-DD 字符串. 不用 toISOString() 因为它返回 UTC,
 *  在 UTC+8 等时区午夜后会偏移一天. */
function localDateString(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

/** 取最近一个交易日 (周末 → 上一个周五) */
export function getMostRecentTradingDayClient(now: Date = new Date()): string {
  const d = new Date(now.getTime())
  const day = d.getDay()
  if (day === 0) d.setDate(d.getDate() - 2) // 周日 → 周五
  else if (day === 6) d.setDate(d.getDate() - 1) // 周六 → 周五
  return localDateString(d)
}

/** 取指定日期的"上一交易日" (跳过周末). 节假日客户端不感知, 后端 overview 会覆盖. */
export function getPrevTradingDayClient(date: string | Date): string {
  let d: Date
  if (typeof date === "string") {
    // 'YYYY-MM-DD' 当作当地午夜的本地时间, 避免 UTC 偏移
    d = new Date(`${date}T12:00:00`)
  } else {
    d = new Date(date.getTime())
  }
  if (Number.isNaN(d.getTime())) return ""
  const day = d.getDay()
  if (day === 0) d.setDate(d.getDate() - 2)       // 周日 → 周五
  else if (day === 6) d.setDate(d.getDate() - 1)  // 周六 → 周五
  else if (day === 1) d.setDate(d.getDate() - 3)  // 周一 → 上周五
  else d.setDate(d.getDate() - 1)                 // 周二-周五 → 前一天
  return localDateString(d)
}

/** 当前是否处于交易时段 (9:30-11:30, 13:00-15:00, 排除周末) */
export function isTradeTimeClient(now: Date = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const hm = now.getHours() * 60 + now.getMinutes()
  const morning = 9 * 60 + 30 <= hm && hm <= 11 * 60 + 30
  const afternoon = 13 * 60 <= hm && hm <= 15 * 60
  return morning || afternoon
}
