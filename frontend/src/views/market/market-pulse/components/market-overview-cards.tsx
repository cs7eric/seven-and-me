import { ArrowDownRight, ArrowUpRight, Loader2, Pencil, RefreshCw, Wallet, Waves } from "lucide-react"

import { Button } from "@/components/ui/button"
import { CountUp } from "@/components/ui/count-up"
import { diffBadgeTone, formatCount, formatYi, moneyTone } from "../lib/format"
import type { ManualFundFlow, MarketHistoryPoint, MarketOverview, MarketOverviewEltdx } from "@/lib/api"

interface MarketOverviewCardsProps {
  overview: MarketOverview | null
  overviewError: string | null
  overviewLoading: boolean
  overviewFetchedAt: string | null
  overviewCounts: MarketOverviewEltdx | null
  activePoint: MarketHistoryPoint | null
  /** 当前显示的交易日期（前端用 getMostRecentTradingDayClient 计算，9:30 前为昨日）*/
  activeTradingDate: string
  /** 当前显示日期的"上一交易日" history 点 (从 market-pulse 用 history 算出来).
   *  较昨日 diff 优先用这个, 不用 overview.prevDayFlow (stale). */
  prevDayPoint?: MarketHistoryPoint | null
  onRefresh: () => void
  onClearReplay: () => void
  /** 手动粘贴的资金流数据 (有值时覆盖 overview 相应字段) */
  manualFundFlow?: ManualFundFlow | null
  /** 打开手动添加 dialog 的回调 */
  onOpenManualDialog?: () => void
}

/**
 * 大盘成交额 / 主力净流入 · 6 列 grid + 超大/大/中/小单 4 列
 *
 * 用途: Market Pulse 主页第一区块. 含历史日 (activePoint) ↔ 今日 overview 的
 *       三级 fallback (hover > click > overview). 点击历史柱子后此处的
 *       数值会瞬时跟手 (K 线不动, 只有这里变).
 *
 * 来源: 之前是 market-pulse.tsx 主页 IIFE 渲染 (line ~433-635), 抽出来.
 */
export function MarketOverviewCards({
  overview,
  overviewError,
  overviewLoading,
  overviewFetchedAt,
  overviewCounts,
  activePoint,
  activeTradingDate,
  prevDayPoint,
  onRefresh,
  onClearReplay,
  manualFundFlow,
  onOpenManualDialog,
}: MarketOverviewCardsProps) {
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            大盘成交额 / 主力净流入
          </h2>
          <p className="text-sm leading-6 text-muted-foreground">
            全 A 实时成交 + 东方财富主力资金口径
            {/* 交易日 + (缓存) 标记: 上游 akshare 失败, latest.json 走归档 fallback
                (source === "archived") 时显示, 提示数据不是当日新拉.
                用 activeTradingDate 而不是 overview.tradingDate: 9:30 前显示昨日. */}
            {` · 交易日 ${activeTradingDate}${overview?.source === "archived" ? " (缓存)" : ""}`}
            {/* 数据滞后指示: 跟 (缓存) 同一条件, 但用更显眼的琥珀色 pill 强调. */}
            {overview?.source === "archived" && (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                数据滞后
              </span>
            )}
            {/* 手动数据指示: manualFundFlow 存在时, 主力净流入 / 4 单数据来自用户粘贴.
                数据源在落盘后由 "akshare (failed) → manual" 切换. */}
            {manualFundFlow && (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
                手动
              </span>
            )}
            {overviewFetchedAt ? ` · ${overviewFetchedAt} 拉取` : ""}
            {overview?.source && overview.source !== "akshare" ? ` · 来源 ${overview.source}` : ""}
            {overviewCounts?.tradingDate && overview?.tradingDate !== overviewCounts.tradingDate
              ? ` · eltdx ${overviewCounts.tradingDate}`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          {onOpenManualDialog && (
            <Button
              variant={manualFundFlow ? "secondary" : "outline"}
              size="sm"
              onClick={onOpenManualDialog}
              title="手动粘贴资金流数据 (东方财富), 落盘后覆盖 overview 主力净流入 / 4 单"
            >
              <Pencil className="size-3.5" />
              <span className="ml-1">manual add</span>
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={onRefresh}
            disabled={overviewLoading}
            title="刷新资金流向 + 市场概况 (eltdx)"
          >
            {overviewLoading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            <span className="ml-1">Refresh</span>
          </Button>
        </div>
      </div>

      {overviewError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          拉取失败: {overviewError}
        </div>
      )}

      {/* === 统一显示数据: hover/click 历史日 → 用 activePoint; 否则用今日 overview/overviewCounts === */}
      {(() => {
        const display = activePoint
          ? {
              source: "history" as const,
              tradingDate: activePoint.date,
              prevDayTradingDate: null as string | null,
              prevDayFlow: null as Record<string, unknown> | null,
              totalAmount: activePoint.totalAmount,
              stockCount: null as number | null,
              risingCount: activePoint.risingCount,
              fallingCount: activePoint.fallingCount,
              flatCount: activePoint.flatCount,
              limitUpCount: activePoint.limitUpCount,
              limitDownCount: activePoint.limitDownCount,
              mainNetInflow: activePoint.mainNetInflow,
              superLargeNetInflow: activePoint.superLargeNetInflow,
              largeNetInflow: activePoint.largeNetInflow,
              mediumNetInflow: activePoint.mediumNetInflow,
              smallNetInflow: activePoint.smallNetInflow,
            }
          : {
              source: "today" as const,
              tradingDate: overview?.tradingDate ?? null,
              prevDayTradingDate: overview?.prevDayTradingDate ?? null,
              prevDayFlow: (overview?.prevDayFlow as Record<string, unknown> | null) ?? null,
              totalAmount: overviewCounts?.totalAmount ?? overview?.totalAmount ?? null,
              stockCount: overviewCounts?.stockCount ?? overview?.stockCount ?? null,
              risingCount: overviewCounts?.risingCount ?? overview?.risingCount ?? null,
              fallingCount: overviewCounts?.fallingCount ?? overview?.fallingCount ?? null,
              flatCount: overviewCounts?.flatCount ?? overview?.flatCount ?? null,
              limitUpCount: overviewCounts?.limitUpCount ?? overview?.limitUpCount ?? null,
              limitDownCount:
                overviewCounts?.limitDownCount ?? overview?.limitDownCount ?? null,
              // 主力净流入 / 4 单: manual 优先, 否则用 overview (akshare). manual 不含
              // prevDay 数据, diff badge 仍走 overview.prevDayFlow, 数字可能跟 manual
              // 不完全匹配 — 接受这个小不一致, 换 manual 数据有值可看的收益.
              mainNetInflow: manualFundFlow?.mainNetInflow ?? overview?.mainNetInflow ?? null,
              superLargeNetInflow:
                manualFundFlow?.superLargeNetInflow ?? overview?.superLargeNetInflow ?? null,
              largeNetInflow: manualFundFlow?.largeNetInflow ?? overview?.largeNetInflow ?? null,
              mediumNetInflow:
                manualFundFlow?.mediumNetInflow ?? overview?.mediumNetInflow ?? null,
              smallNetInflow: manualFundFlow?.smallNetInflow ?? overview?.smallNetInflow ?? null,
            }

        // 大盘成交额 较昨日差额.
        // 关键: prevDayAmount 跟 display.totalAmount **必须同源** —
        //   - totalAmount 来自 eltdx → prevDay 走 eltdx 的 prevDayTotalAmount
        //   - totalAmount 来自 akshare → prevDay 走 overview.prevDayFlow.totalAmount
        // 否则 akshare 失败时 (overview.prevDayFlow.totalAmount=null) 算不出 diff.
        // history 视图 prevDayFlow=null 且 totalAmount 来自 history, 走不到任何源, 留 null.
        const totalAmountFromEltdx =
          !activePoint && overviewCounts?.totalAmount != null
        // 较昨日 diff 的 prev 数据源优先级:
        //   1. prevDayPoint (从 history 查到的"上一交易日", 跟当前显示日期匹配, 永远准)
        //   2. overview.prevDayFlow (latest.json 里 stale 的, 仅作 fallback)
        //   3. overviewCounts.prevDayTotalAmount (仅 totalAmount, 跟 totalAmountFromEltdx 配套)
        // 当 user 切到 replay (activePoint != null) 时, 也用 prevDayPoint (它是 activePoint.date 的上一交易日).
        const prevFromHistory = prevDayPoint
        const prevFromOverviewFlow = (display.prevDayFlow as
          | {
              mainNetInflow: number | null
              superLargeNetInflow: number | null
              largeNetInflow: number | null
              mediumNetInflow: number | null
              smallNetInflow: number | null
              totalAmount: number | null
            }
          | null)
        const prevDayAmount = activePoint
          ? (prevFromHistory?.totalAmount ?? prevFromOverviewFlow?.totalAmount ?? null)
          : totalAmountFromEltdx
            ? (prevFromHistory?.totalAmount ?? overviewCounts?.prevDayTotalAmount ?? null)
            : (prevFromHistory?.totalAmount ?? prevFromOverviewFlow?.totalAmount ?? null)
        const amountDiff =
          display.totalAmount != null && prevDayAmount != null
            ? display.totalAmount - prevDayAmount
            : null

        const prevMainFlow = activePoint
          ? (prevFromHistory?.mainNetInflow ?? prevFromOverviewFlow?.mainNetInflow ?? null)
          : (prevFromHistory?.mainNetInflow ?? prevFromOverviewFlow?.mainNetInflow ?? null)
        const prevSuperLarge = prevFromHistory?.superLargeNetInflow ?? prevFromOverviewFlow?.superLargeNetInflow ?? null
        const prevLarge = prevFromHistory?.largeNetInflow ?? prevFromOverviewFlow?.largeNetInflow ?? null
        const prevMedium = prevFromHistory?.mediumNetInflow ?? prevFromOverviewFlow?.mediumNetInflow ?? null
        const prevSmall = prevFromHistory?.smallNetInflow ?? prevFromOverviewFlow?.smallNetInflow ?? null
        const mainDiff =
          display.mainNetInflow != null && prevMainFlow != null
            ? display.mainNetInflow - prevMainFlow
            : null
        const superLargeDiff =
          display.superLargeNetInflow != null && prevSuperLarge != null
            ? display.superLargeNetInflow - prevSuperLarge
            : null
        const largeDiff =
          display.largeNetInflow != null && prevLarge != null
            ? display.largeNetInflow - prevLarge
            : null
        const mediumDiff =
          display.mediumNetInflow != null && prevMedium != null
            ? display.mediumNetInflow - prevMedium
            : null
        const smallDiff =
          display.smallNetInflow != null && prevSmall != null
            ? display.smallNetInflow - prevSmall
            : null

        return (
          <div className="space-y-3">
            {display.source === "history" && display.tradingDate && (
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
                <span>已选中 {display.tradingDate} 历史快照</span>
                <button
                  type="button"
                  className="ml-1 text-amber-700 underline-offset-2 hover:underline"
                  onClick={onClearReplay}
                >
                  返回今日
                </button>
              </div>
            )}

            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
              <div className="grid grid-cols-4 gap-px bg-slate-200 md:grid-cols-4 lg:grid-cols-[1.15fr_1.15fr_0.7fr_0.7fr_0.7fr_0.7fr]">
                <div className="col-span-2 bg-gradient-to-br from-slate-50 via-white to-slate-50 px-3 py-3 sm:px-4 md:col-span-2 lg:col-span-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-slate-500">
                      <Waves className="size-3.5 shrink-0" />
                      <span className="truncate">大盘成交额</span>
                    </div>
                    <div className={`inline-flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold leading-none tabular-nums sm:gap-1 sm:px-2 sm:py-1 sm:text-[11px] ${diffBadgeTone(amountDiff)}`}>
                      <span className="hidden sm:inline">较昨日</span>
                      <span className="sm:hidden">较昨</span>
                      {amountDiff != null && amountDiff > 0 ? (
                        <ArrowUpRight className="size-3 sm:size-3.5" />
                      ) : amountDiff != null && amountDiff < 0 ? (
                        <ArrowDownRight className="size-3 sm:size-3.5" />
                      ) : null}
                      <span className="whitespace-nowrap">{amountDiff == null ? "—" : formatYi(amountDiff)}</span>
                    </div>
                  </div>
                  <div className="mt-2 whitespace-nowrap text-[22px] font-bold leading-none tracking-tight tabular-nums text-slate-900 sm:text-2xl">
                    {display.totalAmount != null ? (
                      // 不传 key → 组件实例不卸载, spring 从上一次渲染结束的位置 ease 到新 to,
                      // 实现"接着上一次的值 count up". 首次 mount 时 spring 从 0 ease 到初始 to.
                      <>
                        <CountUp
                          to={display.totalAmount}
                          duration={1.2}
                          separator=","
                        />
                        <span>亿</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </div>
                </div>

                <div className="col-span-2 bg-gradient-to-br from-slate-50 via-white to-slate-50 px-3 py-3 sm:px-4 md:col-span-2 lg:col-span-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-slate-500">
                      <Wallet className="size-3.5 shrink-0" />
                      <span className="truncate">主力净流入</span>
                    </div>
                    <div className={`inline-flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold leading-none tabular-nums sm:gap-1 sm:px-2 sm:py-1 sm:text-[11px] ${diffBadgeTone(mainDiff)}`}>
                      <span className="hidden sm:inline">较昨日</span>
                      <span className="sm:hidden">较昨</span>
                      {mainDiff != null && mainDiff > 0 ? (
                        <ArrowUpRight className="size-3 sm:size-3.5" />
                      ) : mainDiff != null && mainDiff < 0 ? (
                        <ArrowDownRight className="size-3 sm:size-3.5" />
                      ) : null}
                      <span className="whitespace-nowrap">{mainDiff == null ? "—" : formatYi(mainDiff)}</span>
                    </div>
                  </div>
                  <div className={`mt-2 whitespace-nowrap text-[22px] font-bold leading-none tracking-tight tabular-nums sm:text-2xl ${moneyTone(display.mainNetInflow).text}`}>
                    {display.mainNetInflow != null ? (
                      <>
                        {display.mainNetInflow > 0 ? "+" : ""}
                        <CountUp
                          to={Math.abs(display.mainNetInflow)}
                          duration={1.2}
                          separator=","
                        />
                        <span>亿</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </div>
                </div>

                <div className="bg-white px-2 py-3 sm:px-4">
                  <div className="text-[10px] font-medium text-slate-500 sm:text-[11px]">上涨</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-red-600 sm:text-xl">
                    {display.risingCount != null ? (
                      <CountUp
                        to={display.risingCount}
                        duration={1.0}
                        separator=","
                      />
                    ) : (
                      "—"
                    )}
                  </div>
                </div>

                <div className="bg-white px-2 py-3 sm:px-4">
                  <div className="text-[10px] font-medium text-slate-500 sm:text-[11px]">下跌</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-emerald-600 sm:text-xl">
                    {display.fallingCount != null ? (
                      <CountUp
                        to={display.fallingCount}
                        duration={1.0}
                        separator=","
                      />
                    ) : (
                      "—"
                    )}
                  </div>
                </div>

                <div className="bg-white px-2 py-3 sm:px-4">
                  <div className="text-[10px] font-medium text-slate-500 sm:text-[11px]">涨停</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-red-600 sm:text-xl">
                    {display.limitUpCount != null ? (
                      <CountUp
                        to={display.limitUpCount}
                        duration={1.0}
                        separator=","
                      />
                    ) : (
                      "—"
                    )}
                  </div>
                </div>

                <div className="bg-white px-2 py-3 sm:px-4">
                  <div className="text-[10px] font-medium text-slate-500 sm:text-[11px]">跌停</div>
                  <div className="mt-1 text-lg font-bold tabular-nums text-emerald-600 sm:text-xl">
                    {display.limitDownCount != null ? (
                      <CountUp
                        to={display.limitDownCount}
                        duration={1.0}
                        separator=","
                      />
                    ) : (
                      "—"
                    )}
                  </div>
                  <div className="mt-1 text-[9px] text-slate-400 sm:text-[10px]">
                    平盘 {formatCount(display.flatCount)}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-px border-t border-slate-200 bg-slate-200 sm:grid-cols-4">
                {[
                  { label: "超大单", value: display.superLargeNetInflow, diff: superLargeDiff },
                  { label: "大单", value: display.largeNetInflow, diff: largeDiff },
                  { label: "中单", value: display.mediumNetInflow, diff: mediumDiff },
                  { label: "小单", value: display.smallNetInflow, diff: smallDiff },
                ].map((item) => {
                  const tone = moneyTone(item.value)
                  return (
                    <div key={item.label} className="bg-white px-4 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-medium text-slate-500">{item.label}</span>
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold tabular-nums ${diffBadgeTone(item.diff)}`}>
                          <span>较昨</span>
                          {item.diff != null && item.diff > 0 ? (
                            <ArrowUpRight className="size-3" />
                          ) : item.diff != null && item.diff < 0 ? (
                            <ArrowDownRight className="size-3" />
                          ) : null}
                          <span>{item.diff == null ? "—" : `${item.diff >= 0 ? "+" : ""}${item.diff.toFixed(2)}亿`}</span>
                        </span>
                      </div>
                      <div className={`mt-1 text-base font-bold tabular-nums ${tone.text}`}>
                        {formatYi(item.value)}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          </div>
        )
      })()}
    </div>
  )
}
