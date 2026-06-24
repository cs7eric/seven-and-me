import { Activity } from "lucide-react"

const PLACEHOLDER_CARDS: Array<{ title: string; description: string }> = [
  {
    title: "Index Snapshot",
    description: "三大指数实时涨跌、成交额、领涨/领跌板块概览(占位)。",
  },
  {
    title: "Sector Heatmap",
    description: "申万一级 / 同花顺行业板块的涨跌幅热力图(占位)。",
  },
  {
    title: "Limit Up / Down",
    description: "涨停 / 跌停家数、连板高度、炸板率(占位)。",
  },
  {
    title: "Northbound Flow",
    description: "北向资金净流入、十大活跃股(占位)。",
  },
  {
    title: "Volume Leaders",
    description: "成交额 / 换手率 Top 榜单(占位)。",
  },
  {
    title: "Anomaly Alerts",
    description: "异动提醒:快速拉升、急速跳水、量比突增(占位)。",
  },
]

/**
 * Market Pulse 占位卡 grid
 *
 * 用途: Market Pulse 页面底部 6 张 "待接入" 占位卡. 后续接入真实模块后
 *       整段删除即可.
 *
 * 来源: 之前是 market-pulse.tsx 主页内联 JSX (line ~725-742), 抽出来.
 */
export function MarketPlaceholderCards() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 lg:gap-4">
      {PLACEHOLDER_CARDS.map((item) => (
        <section
          key={item.title}
          className="rounded-2xl border border-slate-200 bg-white px-3 py-3 shadow-sm sm:px-5 sm:py-4"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 sm:text-base">
            <Activity className="size-4 shrink-0 text-slate-400" />
            <span className="min-w-0 truncate">{item.title}</span>
          </div>
          <div className="mt-1 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
            Mock · 待接入
          </div>
          <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500 sm:mt-3 sm:text-sm sm:leading-6">{item.description}</p>
        </section>
      ))}
    </div>
  )
}
