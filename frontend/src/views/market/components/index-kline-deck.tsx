/**
 * 三大指数分时图 · 容器 (3 卡 + replay 状态条)
 *
 * 输入: tradingDate (今日默认, hover 历史日时切到该日)
 *       replay / pinned 状态 (用于顶部 pill 文案)
 *
 * 内部用 intraday 接口拿 3 个指数的分时图数据，
 * 再用 batch 接口补一份昨收，便于顶部涨跌幅显示。
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { RefreshCw, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { fetchIndexKlineBatch, fetchStockIntraday } from "@/lib/api"

import { IndexKlineCard, type IndexTimeshareItem } from "./index-kline-card"

interface Props {
  /** 交易日 YYYY-MM-DD (或 null = 今日) */
  tradingDate: string | null
  /** 是否处于"回放某历史日"模式 */
  replay: boolean
  /** 是否被 pinned (区别 hover vs click 锁定) */
  pinned: boolean
  /** 点击 "返回今日" 回调 */
  onClearPinned: () => void
  /** 是否处于 A 股交易时段 (9:30-11:30 / 13:00-15:00 工作日).
   *  非交易时段 → 顶部 pill 显示 "上次收盘 {date}" 而非 "今日实时 1m",
   *  因为此时数据实际是上一交易日的归档 (后端在非交易时段读 archive). */
  isTradeTime?: boolean
}

const INDEX_CODES = ["000001", "399001", "399006"] as const
const INDEX_NAMES: Record<string, string> = {
  "000001": "上证指数",
  "399001": "深证成指",
  "399006": "创业板指",
}

function directionTone(item: IndexTimeshareItem): "up" | "down" | "flat" {
  const last = item.timeshare[item.timeshare.length - 1]?.price ?? null
  const prev = item.previousClose ?? item.timeshare[0]?.price ?? null
  if (last == null || prev == null || prev <= 0) return "flat"
  if (last > prev) return "up"
  if (last < prev) return "down"
  return "flat"
}

export function IndexKlineDeck({ tradingDate, replay, pinned, onClearPinned, isTradeTime = true }: Props) {
  const [items, setItems] = useState<IndexTimeshareItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  // 简单内存 cache: key=date → items, 切日期不重新拉 (后端也会 cache)
  const cacheRef = useRef<Map<string, IndexTimeshareItem[]>>(new Map())

  const load = async (date: string | null) => {
    const key = date ?? "__today__"
    if (cacheRef.current.has(key)) {
      setItems(cacheRef.current.get(key) || [])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const requestDate = date ?? new Date().toISOString().slice(0, 10)
      const previousCloseRes = await fetchIndexKlineBatch({
        codes: [...INDEX_CODES],
        date: requestDate,
      }).catch(() => null)
      const previousCloseMap = new Map(
        (previousCloseRes?.items || []).map((item) => [item.code, item.previousClose ?? null]),
      )
      const normalized = await Promise.all(
        INDEX_CODES.map(async (code) => {
          try {
            const intraday = await fetchStockIntraday({
              targetType: "index",
              symbol: code,
              name: INDEX_NAMES[code] ?? code,
              adjust: "none",
              tradeDate: requestDate,
              periods: ["1m"],
            })
            return {
              ok: true,
              code,
              name: intraday.name && intraday.name !== intraday.symbol ? intraday.name : INDEX_NAMES[code] ?? code,
              tradeDate: intraday.trade_date ?? requestDate,
              previousClose: previousCloseMap.get(code) ?? null,
              source: intraday.source,
              timeshare: intraday.timeshare || [],
              error: undefined,
            } satisfies IndexTimeshareItem
          } catch (e) {
            return {
              ok: false,
              code,
              name: INDEX_NAMES[code] ?? code,
              tradeDate: requestDate,
              previousClose: previousCloseMap.get(code) ?? null,
              source: undefined,
              timeshare: [],
              error: e instanceof Error ? e.message : String(e),
            } satisfies IndexTimeshareItem
          }
        }),
      )
      cacheRef.current.set(key, normalized)
      setItems(normalized)
      setFetchedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(tradingDate)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tradingDate])

  // 排序: 按 INDEX_CODES 顺序
  const sortedItems = useMemo(() => {
    return [...items].sort((a, b) => INDEX_CODES.indexOf(a.code as typeof INDEX_CODES[number]) - INDEX_CODES.indexOf(b.code as typeof INDEX_CODES[number]))
  }, [items])

  const replayLabel = tradingDate ? tradingDate : "今日"
  const dateText = tradingDate ?? "今日实时"

  return (
    <section className="space-y-3">
      {/* 头部: 标题 + replay/today pill + 刷新 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            三大指数分时图
          </h2>
          <p className="text-sm text-muted-foreground">
            上证指数 · 深证成指 · 创业板指
            {tradingDate
              ? isTradeTime
                ? ` · ${tradingDate}`
                : ` · ${tradingDate} (上次收盘)`
              : " · 今日实时"}
            {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
          </p>
        </div>

        {replay ? (
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
            <span>
              {pinned ? "已锁定回放" : "正在回放"} {replayLabel}
            </span>
            {pinned ? (
              <button
                type="button"
                onClick={onClearPinned}
                className="underline-offset-2 hover:underline"
              >
                返回今日
              </button>
            ) : (
              <span className="text-amber-600/70">离开图表返回今日</span>
            )}
          </div>
        ) : isTradeTime ? (
          <div className="rounded-full bg-slate-50 px-3 py-1 text-xs font-medium text-slate-500">
            今日实时 1m
          </div>
        ) : (
          // 非交易时段 (周末 / 节假日 / 午休 / 盘后): 后端返回的是上一交易日归档,
          // tradingDate 已经是上次收盘日, 这里把 pill 改成 "上次收盘 {date}"
          // 避免和左下角 "今日实时" 互相打架
          <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-500">
            <span>上次收盘</span>
            {tradingDate ? (
              <span className="font-mono tabular-nums text-slate-700">
                {tradingDate.slice(5).replace("-", "/")}
              </span>
            ) : null}
            <span className="text-slate-400">·</span>
            <span>1m</span>
          </div>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            // 强制刷新: 清掉这个 date 的 cache
            if (tradingDate) cacheRef.current.delete(tradingDate)
            else cacheRef.current.delete("__today__")
            void load(tradingDate)
          }}
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

      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          拉取失败: {error}
        </div>
      ) : null}

      {/* 3 张分时卡 */}
      <div className="grid gap-3 lg:grid-cols-3">
        {sortedItems.length > 0 ? (
          sortedItems.map((item) => (
            <IndexKlineCard
              key={item.code}
              item={item}
              loading={loading}
              directionTone={directionTone(item)}
            />
          ))
        ) : loading ? (
          INDEX_CODES.map((code) => (
            <div key={code} className="flex h-full flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold text-slate-900">
                  {INDEX_NAMES[code] ?? code}
                </span>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                  {dateText}
                </span>
              </div>
              <div className="flex h-[460px] w-full items-center justify-center bg-white text-xs text-slate-400">
                <Loader2 className="mr-1 size-3.5 animate-spin" />
                加载 {INDEX_NAMES[code]} 分时…
              </div>
            </div>
          ))
        ) : (
          <div className="col-span-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 p-6 text-center text-sm text-slate-500">
            暂无指数分时数据
          </div>
        )}
      </div>
    </section>
  )
}
