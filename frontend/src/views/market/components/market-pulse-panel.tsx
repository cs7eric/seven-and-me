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
 * 选中联动: 父组件把 selectedPoint 传进来, panel 算 selectedIndex 给 chart 高亮.
 *   hover 不再联动 K 线 (避免抖动); K 线只在 click 后才切.
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
  /** 点击某一天 (toggle 选中 / 取消, 父组件决定) */
  onPointClick?: (idx: number, point: MarketHistoryPoint) => void
  /** 鼠标 hover 某一天 (瞬时, 父组件用来切换 overview 卡片) */
  onPointHover?: (point: MarketHistoryPoint | null) => void
  /** 父组件当前选中的 point; panel 算出 selectedIndex 喂给 chart 高亮 */
  selectedPoint?: MarketHistoryPoint | null
  /** 父组件当前 hover 的 point; panel 算出 hoveredIndex 喂给 chart 高亮 (蓝色) */
  hoveredPoint?: MarketHistoryPoint | null
  /** 透传给 PulseStats: 宽基指数 N 日收益 (后端 duckdb) */
  indexReturns?: import("@/lib/api").IndexReturnItem[] | null
  /** 透传给 PulseStats: 宽基指数收益历史 (sparkline 用) */
  indexReturnsHistory?: import("@/lib/api").IndexReturnsHistoryItem[] | null
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

/**
 * 是否周末 (周六=6, 周日=0). 后端 archive 是按文件名 glob 拉最近 N 个,
 * scheduler 偶尔在节假日 / 周末误触发就会留下非交易日数据, 趋势图不该展示.
 * 节假日先不专门识别 (用户原话 "最起码 周末"), 后面若需要可扩展节假日表.
 */
function isWeekend(dateStr: string): boolean {
  const d = new Date(dateStr + "T00:00:00")
  const day = d.getDay()
  return day === 0 || day === 6
}

export function MarketPulsePanel({
  defaultView = "flow",
  onPointClick,
  onPointHover,
  selectedPoint = null,
  hoveredPoint = null,
  indexReturns = null,
  indexReturnsHistory = null,
}: Props) {
  const [view, setView] = useState<PulseView>(defaultView)
  const [range, setRange] = useState<PulseRange>("60d")
  const [items, setItems] = useState<MarketHistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  // 父组件传进来的 selectedPoint → dataIndex (chart 用来高亮)
  const selectedIndex = useMemo(() => {
    if (!selectedPoint) return null
    const i = items.findIndex((it) => it.date === selectedPoint.date)
    return i >= 0 ? i : null
  }, [selectedPoint, items])

  // 父组件传进来的 hoveredPoint → dataIndex (chart 用来瞬时高亮 + tip, 蓝色)
  const hoveredIndex = useMemo(() => {
    if (!hoveredPoint) return null
    const i = items.findIndex((it) => it.date === hoveredPoint.date)
    return i >= 0 ? i : null
  }, [hoveredPoint, items])

  const load = async (r: PulseRange) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchMarketPulseHistory(r)
      // 过滤周末: 让 Market Pulse 趋势图只展示交易日.
      setItems((res.items || []).filter((it) => !isWeekend(it.date)))
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
    <div>
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
          variant="secondary"
          size="sm"
          onClick={() => load(range)}
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          <span className="ml-1">Refresh</span>
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
            selectedIndex={selectedIndex}
            hoveredIndex={hoveredIndex}
            onPointClick={onPointClick}
            onPointHover={onPointHover}
          />
        )}
      </div>

      {/* 底部洞察小指标 */}
      {hasData && (
        <PulseStats
          data={items}
          indexReturns={indexReturns}
          indexReturnsHistory={indexReturnsHistory}
        />
      )}
    </div>
  )
}