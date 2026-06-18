/**
 * Sparkline 数据规整: 排序 + 过滤周末 + 截尾 N 天.
 */
export interface SparkPoint { date: string; value: number }

export function toSparkData<T extends { tradeDate: string }>(
  history: T[] | null | undefined,
  pick: (it: T) => number | null | undefined,
  recentDays: number = 60
): SparkPoint[] {
  if (!history) return []
  // Sparkline 只渲染最近 recentDays 个交易日, 避免 700+ 点挤一起看不清
  const sorted = history
    .slice()
    .filter((it) => {
      // 防御: 过滤周末 (A 股没交易, history API 理论上不会返回, 但保险起见)
      // tradeDate 格式 YYYY-MM-DD, 走 Date.UTC 解析避免时区偏移
      const d = new Date(it.tradeDate + "T00:00:00Z")
      const dow = d.getUTCDay() // 0=Sun, 6=Sat
      return dow !== 0 && dow !== 6
    })
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
  const tail = sorted.length > recentDays ? sorted.slice(-recentDays) : sorted
  return tail.map((it) => ({ date: it.tradeDate.slice(5), value: pick(it) ?? 0 }))
}