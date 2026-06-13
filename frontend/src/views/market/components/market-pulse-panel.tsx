/**
 * 市场脉搏 · 主面板
 *
 * 包含:
 *   - 标题 + 时间范围 tabs (20d / 60d / 120d / 1y)
 *   - 视图 tabs (成交趋势 / 涨跌温度 / 资金潮汐 / 资金结构)
 *   - ECharts 复合图 (MarketPulseEChart)
 *   - 底部洞察小指标 (PulseStats)
 *
 * 数据源: fetchMarketPulseHistory(range)
 * hover 联动: 通过 onPointHover 把当前 hover 的 point 推给父组件,
 *   父组件可以据此让顶部两个快照卡临时切换到该日数据.
 */
import { useEffect, useMemo, useState } from "react"
import { Loader2, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  fetchMarketPulseHistory,
  type MarketHistoryPoint,
  type PulseRange,
} from "@/lib/api"

import { MarketPulseEChart, type PulseView } from "./market-pulse-chart"
import { PulseStats } from "./market-pulse-stats"

interface Props {
  /** 初始 view (默认 flow) */
  defaultView?: PulseView
  /** hover 联动回调 */
  onPointHover?: (idx: number | null, point: MarketHistoryPoint | null) => void
  /** 初始 hover 状态 (从外面驱动, 默认 null) */
  hoverIndex?: number | null
}

const VIEW_TABS: Array<{ key: PulseView; label: string }> = [
  { key: "flow", label: "资金潮汐" },
  { key: "turnover", label: "成交趋势" },
  { key: "breadth", label: "涨跌温度" },
  { key: "structure", label: "资金结构" },
]

const RANGE_TABS: Array<{ key: PulseRange; label: string }> = [
  { key: "20d", label: "20日" },
  { key: "60d", label: "60日" },
  { key: "120d", label: "120日" },
  { key: "1y", label: "1年" },
]

export function MarketPulsePanel({
  defaultView = "flow",
  onPointHover,
  hoverIndex = null,
}: Props) {
  const [view, setView] = useState<PulseView>(defaultView)
  const [range, setRange] = useState<PulseRange>("60d")
  const [items, setItems] = useState<MarketHistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  const load = async (r: PulseRange) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchMarketPulseHistory(r)
      setItems(res.items || [])
      setFetchedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(range)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range])

  const hasData = items.length > 0

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      {/* 头部 */}
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-slate-900">市场脉搏</div>
          <div className="mt-0.5 text-xs text-slate-500">
            成交额 · 涨跌温度 · 资金潮汐 · 资金结构
            {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
          </div>
        </div>

        {/* range tabs */}
        <div className="flex items-center gap-1 rounded-full bg-slate-50 p-1">
          {RANGE_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setRange(tab.key)}
              className={[
                "rounded-full px-3 py-1 text-xs transition",
                range === tab.key
                  ? "bg-white font-semibold text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-900",
              ].join(" ")}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* view tabs + 刷新 */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setView(tab.key)}
              className={[
                "rounded-full px-3 py-1.5 text-xs font-medium transition",
                view === tab.key
                  ? "bg-slate-900 text-white shadow-sm"
                  : "bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-900",
              ].join(" ")}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => load(range)}
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          <span className="ml-1">刷新</span>
        </Button>
      </div>

      {error && (
        <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          拉取失败: {error}
        </div>
      )}

      {/* chart 容器: 固定 h-[360px] 让 ECharts 有稳定高度 */}
      <div className="h-[360px] rounded-2xl border border-slate-100 bg-white">
        {loading && !hasData ? (
          <div className="flex h-full w-full animate-pulse items-center justify-center text-xs text-slate-400">
            加载历史数据…
          </div>
        ) : !hasData ? (
          <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
            暂无历史数据
          </div>
        ) : (
          <MarketPulseEChart
            data={items}
            view={view}
            hoverIndex={hoverIndex}
            onPointHover={onPointHover}
          />
        )}
      </div>

      {/* 底部洞察小指标 */}
      {hasData && <PulseStats data={items} />}
    </section>
  )
}