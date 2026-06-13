/**
 * 市场脉搏 · 底部洞察小指标
 *
 * 4 个小卡片: 20日均成交额 / 主力连续流入天数 / 20日上涨占比均值 / 数据源
 * 全部前端从 MarketHistoryPoint[] 计算, 不打额外 API.
 *
 * 颜色逻辑:
 *   - 20日均成交额: 中性色 (slate)
 *   - 主力连续流入天数: 红 (流入方向, A股习惯)
 *   - 20日上涨占比均值: 50% 上下红/绿
 *   - 数据源: 中性 (固定文案)
 */
import type { MarketHistoryPoint } from "@/lib/api"

interface PulseStats {
  avgAmount: number | null      // 亿元
  flowStreak: number            // 日 (>= 0)
  avgUpRatio: number | null     // 0-1
}

function calcPulseStats(data: MarketHistoryPoint[]): PulseStats {
  const last20 = data.slice(-20)
  const amountSum = last20.reduce((s, x) => s + (x.totalAmount ?? 0), 0)
  const amountCount = last20.filter((x) => x.totalAmount != null).length
  const avgAmount = amountCount > 0 ? amountSum / amountCount : null

  let flowStreak = 0
  for (let i = data.length - 1; i >= 0; i--) {
    const v = data[i].mainNetInflow
    if (v != null && v > 0) flowStreak += 1
    else break
  }

  const ratios = last20
    .map((x) => {
      const up = x.risingCount ?? 0
      const down = x.fallingCount ?? 0
      const flat = x.flatCount ?? 0
      const total = up + down + flat
      return total > 0 ? up / total : null
    })
    .filter((x): x is number => x != null)
  const avgUpRatio = ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : null

  return { avgAmount, flowStreak, avgUpRatio }
}

/** 亿元 -> 万亿元 (1万亿 = 10000亿) */
function toWanYi(v: number | null): string {
  if (v == null) return "—"
  return `${(v / 10000).toFixed(2)}万亿`
}

export function PulseStats({ data }: { data: MarketHistoryPoint[] }) {
  const stats = calcPulseStats(data)
  const upRatioPct = stats.avgUpRatio == null ? null : stats.avgUpRatio * 100
  const upRatioTone =
    upRatioPct == null
      ? "text-slate-700"
      : upRatioPct >= 50
        ? "text-red-600"
        : "text-emerald-600"

  return (
    <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
      {/* 20日均成交额 */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="text-[11px] text-slate-500">20日均成交额</div>
        <div className="mt-1 text-sm font-semibold tabular-nums text-slate-900">
          {toWanYi(stats.avgAmount)}
        </div>
      </div>

      {/* 主力连续流入天数 */}
      <div className="rounded-2xl bg-red-50/70 px-3 py-2">
        <div className="text-[11px] text-slate-500">主力连续流入</div>
        <div className="mt-1 text-sm font-semibold tabular-nums text-red-600">
          {stats.flowStreak} 日
        </div>
      </div>

      {/* 20日上涨占比均值 */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="text-[11px] text-slate-500">20日上涨占比</div>
        <div className={`mt-1 text-sm font-semibold tabular-nums ${upRatioTone}`}>
          {upRatioPct == null ? "—" : `${upRatioPct.toFixed(1)}%`}
        </div>
      </div>

      {/* 数据源 */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="text-[11px] text-slate-500">数据源</div>
        <div className="mt-1 text-sm font-semibold text-slate-900">东方财富</div>
      </div>
    </div>
  )
}