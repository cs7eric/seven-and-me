/**
 * 市场脉搏 · 底部洞察小指标
 *
 * 5 个小卡片 (3 前端算 + 1 宽基 + 1 数据源):
 *   1. 20日均成交额       (前端从 MarketHistoryPoint[] 算)
 *   2. 主力连续流入天数   (前端从 MarketHistoryPoint[] 算)
 *   3. 20日上涨占比均值   (前端从 MarketHistoryPoint[] 算)
 *   4. 宽基 5日收益        (后端 duckdb.index_returns_daily 持久化, sparkline 用 history)
 *   5. 数据源             (固定文案)
 *
 * 注: MA 计数 / 5日上涨 / 60日新低 / 252日新高 这 4 张市场宽度卡已迁到
 *   /market/sentiment 页面 (Market Sentiment), 不在 market-pulse 链路里.
 *
 * 颜色逻辑:
 *   - 20日均成交额: 中性色 (slate)
 *   - 主力连续流入天数: 红 (流入方向, A股习惯)
 *   - 20日上涨占比均值: 50% 上下红/绿
 *   - 宽基 5日: 涨红跌绿
 *   - 数据源: 中性
 */
import type {
  IndexReturnItem,
  IndexReturnsHistoryItem,
  MarketHistoryPoint,
} from "@/lib/api"

interface PulseStatsLocal {
  avgAmount: number | null      // 亿元
  flowStreak: number            // 日 (>= 0)
  avgUpRatio: number | null     // 0-1
}

function calcPulseStats(data: MarketHistoryPoint[]): PulseStatsLocal {
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

/** 把涨跌幅数字格式化成 "+1.23%" / "-0.45%" / "—", 同时给出红绿色 */
function pctTone(v: number | null): { text: string; tone: string } {
  if (v == null) return { text: "—", tone: "text-slate-500" }
  const sign = v > 0 ? "+" : ""
  const tone = v > 0 ? "text-red-600" : v < 0 ? "text-emerald-600" : "text-slate-700"
  return { text: `${sign}${v.toFixed(2)}%`, tone }
}

/**
 * 微型 sparkline (inline SVG, 无依赖). 给百分比序列画一条线 + 起点终点圆点.
 * - 颜色按末值正负着色 (涨红跌绿)
 * - 自适应 Y 轴 (min/max)
 * - 高度 16px, 宽度按父容器 (use 100% via viewBox)
 */
function Sparkline({ values, strokeWidth = 1.2 }: { values: number[]; strokeWidth?: number }) {
  if (!values || values.length < 2) {
    return <span className="text-[10px] text-slate-300">—</span>
  }
  const w = 80
  const h = 18
  const pad = 2
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const stepX = (w - pad * 2) / (values.length - 1)
  const points = values
    .map((v, i) => {
      const x = pad + i * stepX
      const y = h - pad - ((v - min) / span) * (h - pad * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const last = values[values.length - 1]
  const first = values[0]
  const lastColor = last > first ? "#dc2626" : last < first ? "#059669" : "#64748b"
  const lastX = pad + (values.length - 1) * stepX
  const lastY = h - pad - ((last - min) / span) * (h - pad * 2)
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="shrink-0"
      aria-label="趋势"
    >
      <polyline
        fill="none"
        stroke={lastColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
      <circle cx={lastX} cy={lastY} r={1.6} fill={lastColor} />
    </svg>
  )
}

interface Props {
  data: MarketHistoryPoint[]
  /** 后端 /api/stock-chart/market-pulse/index-returns 结果 */
  indexReturns?: IndexReturnItem[] | null
  /** 宽基指数 N 日收益历史序列 (后端 index-returns/history, sparkline 用) */
  indexReturnsHistory?: IndexReturnsHistoryItem[] | null
}

export function PulseStats({
  data, indexReturns, indexReturnsHistory,
}: Props) {
  const stats = calcPulseStats(data)
  const upRatioPct = stats.avgUpRatio == null ? null : stats.avgUpRatio * 100
  const upRatioTone =
    upRatioPct == null
      ? "text-slate-700"
      : upRatioPct >= 50
        ? "text-red-600"
        : "text-emerald-600"

  // 宽基 5 日: 沪深300 (大盘基准) + 中证1000 并列
  const hs300 = indexReturns?.find((x) => x.code === "000300")
  const hs300Tone = pctTone(hs300?.returnPct ?? null)
  const zz1000 = indexReturns?.find((x) => x.code === "000852")
  const zz1000Tone = pctTone(zz1000?.returnPct ?? null)

  // 沪深300 收益序列: 同一日多条取最近的 (currentDate = tradeDate)
  // indexReturnsHistory 已按 trade_date ASC, 一日一条 (或两条 = 沪深300 + 中证1000),
  // 我们只画 沪深300
  const hs300Spark: number[] = (indexReturnsHistory ?? [])
    .filter((it) => it.code === "000300")
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
    .map((it) => it.returnPct ?? 0)

  return (
    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {/* 20日均成交额 */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="text-[11px] text-slate-500">20日均成交额</div>
        <div className="mt-1 text-sm font-semibold tabular-nums text-slate-900">
          {toWanYi(stats.avgAmount)}
        </div>
      </div>

      {/* 主力连续流入 */}
      <div className="rounded-2xl bg-red-50/70 px-3 py-2">
        <div className="text-[11px] text-slate-500">主力连续流入</div>
        <div className="mt-1 text-sm font-semibold tabular-nums text-red-600">
          {stats.flowStreak} 日
        </div>
      </div>

      {/* 20日上涨占比 */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="text-[11px] text-slate-500">20日上涨占比</div>
        <div className={`mt-1 text-sm font-semibold tabular-nums ${upRatioTone}`}>
          {upRatioPct == null ? "—" : `${upRatioPct.toFixed(1)}%`}
        </div>
      </div>

      {/* 宽基 5日: 沪深300 + 中证1000 并列 (duckdb.index_daily_raw) */}
      <div className="rounded-2xl bg-slate-50 px-3 py-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] text-slate-500">宽基 5日</div>
          {hs300Spark.length >= 2 && <Sparkline values={hs300Spark} />}
        </div>
        <div className="mt-1 flex flex-col gap-0.5">
          <div className="flex items-baseline gap-1">
            <span className="text-[10px] text-slate-500">HS300</span>
            <span className={`text-sm font-semibold tabular-nums ${hs300Tone.tone}`}>
              {hs300Tone.text}
            </span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-[10px] text-slate-500">ZZ1000</span>
            <span className={`text-sm font-semibold tabular-nums ${zz1000Tone.tone}`}>
              {zz1000Tone.text}
            </span>
          </div>
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
