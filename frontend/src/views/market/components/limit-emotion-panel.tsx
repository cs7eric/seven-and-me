/**
 * 市场脉搏 · 涨跌停情绪 (limitEmotion) 面板
 *
 * 在 IndustryHeatmap (行业板块热力图) 下面挂载, 不修改其他任何模块.
 *
 * 4 个核心指标 + 连板情绪文案 + 简版连板梯队:
 *   涨停 (count / 红)
 *   跌停 (count / 绿)
 *   连板高度 (maxHeight 板, 含 leaders 领头股)
 *   炸板率 (rate%, status=unavailable → --)
 *
 * 数据源: fetchMarketPulseLimitEmotion()
 * 持久化: 后端 reference/market-pulse/latest.json + snapshots/.
 * 刷新策略: 交易时间内每 5 分钟轮询, 非交易时间每 30 分钟; 也可手动刷新.
 */
import { useCallback, useEffect, useState } from "react"
import {
  Activity,
  Flame,
  Loader2,
  RefreshCw,
  Snowflake,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { notification } from "@/components/ui/notification"
import { StockDetailDialog } from "@/components/stock-detail-dialog"
import {
  fetchMarketPulseLimitEmotion,
  refreshMarketPulseLimitEmotion,
  type LimitEmotionPayload,
  type LimitEmotionStreakSentimentLevel,
} from "@/lib/api"

type SentimentTone = {
  bg: string
  border: string
  text: string
  iconBg: string
  label: string
}

const SENTIMENT_TONE: Record<LimitEmotionStreakSentimentLevel, SentimentTone> = {
  ice: {
    bg: "bg-slate-50/70",
    border: "border-slate-200",
    text: "text-slate-700",
    iconBg: "bg-slate-200 text-slate-600",
    label: "冰点",
  },
  weak: {
    bg: "bg-sky-50/70",
    border: "border-sky-200",
    text: "text-sky-700",
    iconBg: "bg-sky-200 text-sky-700",
    label: "偏弱",
  },
  normal: {
    bg: "bg-slate-50/70",
    border: "border-slate-200",
    text: "text-slate-700",
    iconBg: "bg-slate-200 text-slate-700",
    label: "正常",
  },
  active: {
    bg: "bg-rose-50/70",
    border: "border-rose-200",
    text: "text-rose-700",
    iconBg: "bg-rose-200 text-rose-700",
    label: "活跃",
  },
  hot: {
    bg: "bg-red-50/70",
    border: "border-red-200",
    text: "text-red-700",
    iconBg: "bg-red-200 text-red-700",
    label: "高热",
  },
}

function formatCount(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toLocaleString("zh-CN")
}

function formatRate(v: number | null | undefined): string {
  if (v == null) return "—"
  return `${(v * 100).toFixed(1)}%`
}

function formatStreakHeight(v: number | null | undefined): string {
  if (v == null || v <= 0) return "—"
  return `${v}板`
}

function isTradeTimeClient(): boolean {
  const d = new Date()
  if (d.getDay() === 0 || d.getDay() === 6) return false
  const hm = d.getHours() * 60 + d.getMinutes()
  const morning = 9 * 60 + 30 <= hm && hm <= 11 * 60 + 30
  const afternoon = 13 * 60 <= hm && hm <= 15 * 60
  return morning || afternoon
}

function marketStatusLabel(s: string | null | undefined): string {
  switch (s) {
    case "pre_open":
      return "开盘前"
    case "trading":
      return "交易中"
    case "closed":
      return "已收盘"
    default:
      return "未知"
  }
}

function dataStatusLabel(s: string | null | undefined): string {
  switch (s) {
    case "normal":
      return "数据正常"
    case "partial":
      return "部分数据缺失"
    case "stale":
      return "数据可能延迟"
    case "empty":
      return "暂无数据"
    default:
      return "数据未知"
  }
}

export function LimitEmotionPanel() {
  const [data, setData] = useState<LimitEmotionPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  const load = useCallback(async (withLoading = true) => {
    if (withLoading) setLoading(true)
    setError(null)
    try {
      const payload = await fetchMarketPulseLimitEmotion()
      setData(payload)
      setFetchedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (withLoading) setLoading(false)
    }
  }, [])

  const onRefresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const payload = await refreshMarketPulseLimitEmotion()
      setData(payload)
      setFetchedAt(new Date().toLocaleTimeString())
      notification.success({ title: "已刷新涨跌停情绪" })
    } catch (e) {
      notification.danger({
        title: "刷新失败",
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void load(true)
  }, [load])

  // 5 / 30 分钟轮询
  useEffect(() => {
    const ms = isTradeTimeClient() ? 5 * 60_000 : 30 * 60_000
    const id = window.setInterval(() => void load(false), ms)
    return () => window.clearInterval(id)
  }, [load])

  const isEmpty = data?.dataStatus === "empty"
  const sentimentLevel: LimitEmotionStreakSentimentLevel =
    data?.streak?.sentiment?.level ?? "normal"
  const sentimentTone = SENTIMENT_TONE[sentimentLevel]
  const SentimentIcon =
    sentimentLevel === "ice"
      ? Snowflake
      : sentimentLevel === "weak"
        ? TrendingDown
        : sentimentLevel === "active"
          ? Flame
          : sentimentLevel === "hot"
            ? Sparkles
            : Activity

  // 哪个核心指标卡被展开 (limitUp / limitDown / breakBoard)
  const [expandedMetric, setExpandedMetric] = useState<
    "limitUp" | "limitDown" | "breakBoard" | null
  >(null)
  // hover tooltip 状态: 哪只股 + 行 rect
  const [hoveredStock, setHoveredStock] = useState<
    | { stock: LimitEmotionStock; tone: StockTone; rect: DOMRect }
    | null
  >(null)
  // 个股详情 dialog 状态
  const [detailOpen, setDetailOpen] = useState(false)
  const [selectedStock, setSelectedStock] = useState<LimitEmotionStock | null>(null)
  const openDetail = useCallback((stock: LimitEmotionStock) => {
    setSelectedStock(stock)
    setDetailOpen(true)
  }, [])
  const closeDetail = useCallback(() => {
    setDetailOpen(false)
    setSelectedStock(null)
  }, [])
  const expandedMetricLabel: Record<string, string> = {
    limitUp: "涨停股",
    limitDown: "跌停股",
    breakBoard: "炸板股",
  }
  const expandedMetricStocks: Array<{ code: string; name: string }> =
    expandedMetric === "limitUp"
      ? (data?.limitUp?.stocks ?? [])
      : expandedMetric === "limitDown"
        ? (data?.limitDown?.stocks ?? [])
        : expandedMetric === "breakBoard"
          ? (data?.breakBoard?.brokenStocks ?? [])
          : []

  return (
    <div className="space-y-3">
      {/* hover 浮动 tooltip, fixed 定位不随滚动跳 */}
      {hoveredStock ? <StockTooltip data={hoveredStock} /> : null}

      {/* 点击行 → 弹出个股详情 dialog */}
      <StockDetailDialog
        open={detailOpen}
        onOpenChange={(o) => {
          setDetailOpen(o)
          if (!o) setSelectedStock(null)
        }}
        stockCode={selectedStock?.code ?? null}
        stockName={selectedStock?.name ?? null}
        industryName={selectedStock?.industry ?? null}
      />
      {/* 头部 */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            涨跌停情绪
          </h2>
          <p className="text-sm text-muted-foreground">
            涨停 / 跌停 / 触板 / 炸板 / 连板梯队
            {data?.marketStatus ? ` · ${marketStatusLabel(data.marketStatus)}` : ""}
            {data?.dataStatus ? ` · ${dataStatusLabel(data.dataStatus)}` : ""}
            {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
            {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={onRefresh}
          disabled={refreshing || loading}
          title="强制重算 + 落盘"
        >
          {refreshing ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          <span className="ml-1">Refresh</span>
        </Button>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          拉取失败: {error}
        </div>
      )}

      {/* 4 大核心指标 + 情绪文案 */}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="grid gap-px bg-slate-200 lg:grid-cols-4">
          <Cell
            label="涨停"
            value={formatCount(data?.limitUp?.count)}
            tone="up"
            sub={
              expandedMetric === "limitUp"
                ? "点击收起"
                : data?.limitUp?.stocks && data.limitUp.stocks.length > 0
                  ? `点击查看 ${data.limitUp.stocks.length} 只`
                  : null
            }
            active={expandedMetric === "limitUp"}
            onClick={() =>
              setExpandedMetric(expandedMetric === "limitUp" ? null : "limitUp")
            }
          />
          <Cell
            label="跌停"
            value={formatCount(data?.limitDown?.count)}
            tone="down"
            sub={
              expandedMetric === "limitDown"
                ? "点击收起"
                : data?.limitDown?.stocks && data.limitDown.stocks.length > 0
                  ? `点击查看 ${data.limitDown.stocks.length} 只`
                  : null
            }
            active={expandedMetric === "limitDown"}
            onClick={() =>
              setExpandedMetric(
                expandedMetric === "limitDown" ? null : "limitDown"
              )
            }
          />
          <Cell
            label="连板高度"
            value={formatStreakHeight(data?.streak?.maxHeight)}
            tone="neutral"
            sub={
              data?.streak?.leaders && data.streak.leaders.length > 0
                ? `领头 ${data.streak.leaders[0]?.name ?? ""}`
                : null
            }
          />
          <Cell
            label="炸板率"
            value={
              data?.breakBoard?.status === "ready"
                ? formatRate(data.breakBoard.rate)
                : "—"
            }
            tone={
              data?.breakBoard?.status === "ready"
                ? (data.breakBoard.rate ?? 0) >= 0.4
                  ? "down"
                  : "up"
                : "neutral"
            }
            sub={
              expandedMetric === "breakBoard"
                ? "点击收起"
                : data?.breakBoard?.status === "ready"
                  ? `触板 ${formatCount(data.breakBoard.touchedCount)} / 炸 ${formatCount(data.breakBoard.brokenCount)}`
                  : "暂无触板数据"
            }
            active={expandedMetric === "breakBoard"}
            onClick={() =>
              data?.breakBoard?.brokenStocks &&
              data.breakBoard.brokenStocks.length > 0 &&
              setExpandedMetric(
                expandedMetric === "breakBoard" ? null : "breakBoard"
              )
            }
          />
        </div>

        {expandedMetric && (
          <div className="border-t border-slate-200 px-4 py-2.5">
            <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500">
              <span>
                <span className="font-semibold text-slate-700">
                  {expandedMetricLabel[expandedMetric]}
                </span>
                <span className="ml-2 tabular-nums">
                  {expandedMetricStocks.length} 只
                </span>
              </span>
              <button
                type="button"
                onClick={() => setExpandedMetric(null)}
                className="hover:text-slate-700"
              >
                收起
              </button>
            </div>
            {expandedMetricStocks.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-200 bg-white px-3 py-4 text-center text-xs text-slate-400">
                (空)
              </div>
            ) : (
              <div
                className={`grid grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3 ${
                  expandedMetricStocks.length > 24 ? "max-h-[28rem] overflow-y-auto pr-1" : ""
                }`}
              >
                {expandedMetricStocks.map((s) => (
                  <StockRow
                    key={s.code}
                    stock={s}
                    tone={
                      expandedMetric === "limitUp"
                        ? "up"
                        : expandedMetric === "limitDown"
                          ? "down"
                          : "broken"
                    }
                    onHover={(stock, rect) =>
                      setHoveredStock({
                        stock,
                        tone:
                          expandedMetric === "limitUp"
                            ? "up"
                            : expandedMetric === "limitDown"
                              ? "down"
                              : "broken",
                        rect,
                      })
                    }
                    onLeave={() => setHoveredStock(null)}
                    onClick={openDetail}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* 连板情绪判断条 */}
        <div
          className={`flex flex-wrap items-center gap-3 border-t border-slate-200 px-4 py-3 ${sentimentTone.bg}`}
        >
          <div
            className={`inline-flex size-8 items-center justify-center rounded-full ${sentimentTone.iconBg}`}
          >
            <SentimentIcon className="size-4" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${sentimentTone.border} ${sentimentTone.text}`}
              >
                连板情绪 · {sentimentTone.label}
              </span>
              <span className="text-[10px] text-slate-500">
                最高 {formatStreakHeight(data?.streak?.maxHeight)}
                {data?.streak?.promotion?.overallRate != null
                  ? ` · 整体晋级率 ${formatRate(data.streak.promotion.overallRate)}`
                  : ""}
                {data?.streak?.broken && data.streak.broken.count > 0
                  ? ` · 断板 ${data.streak.broken.count} 只 (高位 ${data.streak.broken.highStreakBrokenCount})`
                  : ""}
              </span>
            </div>
            <div className={`mt-1 text-sm leading-6 ${sentimentTone.text}`}>
              {data?.streak?.sentiment?.text ?? "暂无情绪判断。"}
            </div>
          </div>
        </div>
      </section>

      {/* 简版连板梯队 */}
      <DistributionStrip
        rows={data?.streak?.distribution ?? []}
        isEmpty={isEmpty}
        loading={loading && !data}
        onClickStock={openDetail}
      />

      {/* 晋级率 + 断板反馈 (双列) */}
      <div className="grid gap-3 lg:grid-cols-2">
        <PromotionTable
          promotion={data?.streak?.promotion ?? null}
          isEmpty={isEmpty}
        />
        <BrokenList
          broken={data?.streak?.broken ?? null}
          isEmpty={isEmpty}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hover 浮动 tooltip: 显示股票详细 (涨跌 / 行业 / 概念 / 价格)
// ---------------------------------------------------------------------------
const TOOLTIP_OFFSET = 10
function StockTooltip({
  data,
}: {
  data: { stock: LimitEmotionStock; tone: StockTone; rect: DOMRect }
}) {
  const { stock, tone, rect } = data
  const TONE_BORDER: Record<StockTone, string> = {
    up: "border-red-200",
    down: "border-emerald-200",
    broken: "border-amber-200",
    neutral: "border-slate-200",
  }
  const TONE_CHANGE: Record<StockTone, string> = {
    up: "text-red-600",
    down: "text-emerald-600",
    broken: "text-amber-600",
    neutral: "text-slate-700",
  }
  const TONE_HERO_BG: Record<StockTone, string> = {
    up: "from-red-50/80",
    down: "from-emerald-50/80",
    broken: "from-amber-50/80",
    neutral: "from-slate-50/80",
  }
  const TONE_LABEL: Record<StockTone, string> = {
    up: "涨停",
    down: "跌停",
    broken: "炸板",
    neutral: "—",
  }
  const cp =
    typeof stock.changePct === "number" && Number.isFinite(stock.changePct)
      ? stock.changePct
      : null
  const tooltipW = 288
  const tooltipH = 200
  const wouldOverflowRight = rect.right + TOOLTIP_OFFSET + tooltipW > window.innerWidth
  const left = wouldOverflowRight
    ? Math.max(8, rect.left - TOOLTIP_OFFSET - tooltipW)
    : rect.right + TOOLTIP_OFFSET
  const top = Math.max(
    8,
    Math.min(
      window.innerHeight - tooltipH - 8,
      rect.top + rect.height / 2 - tooltipH / 2
    )
  )
  return (
    <div
      className={`pointer-events-none fixed z-50 w-72 overflow-hidden rounded-lg border bg-white shadow-2xl ${TONE_BORDER[tone]}`}
      style={{ left, top }}
    >
      {/* Hero: 涨跌% 大字 + name/code */}
      <div
        className={`bg-gradient-to-b ${TONE_HERO_BG[tone]} to-white px-3 py-2.5`}
      >
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-900">
              {stock.name || "—"}
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] tabular-nums text-slate-400">
              {stock.code}
            </div>
          </div>
          {cp != null ? (
            <div className="shrink-0 text-right">
              <div
                className={`tabular-nums text-lg font-bold leading-none ${TONE_CHANGE[tone]}`}
              >
                {cp >= 0 ? "+" : ""}
                {cp.toFixed(2)}%
              </div>
              <div className="mt-0.5 text-[10px] text-slate-500">
                {TONE_LABEL[tone]}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* Body: 行业 / 概念 key-value 两栏 (容器永远 render, 行按数据条件) */}
      <div className="space-y-1.5 px-3 py-2.5 text-xs">
        {stock.industry ? (
          <div className="flex items-baseline gap-3">
            <span className="w-8 shrink-0 text-[10px] text-slate-400">行业</span>
            <span className="min-w-0 flex-1 text-slate-700">{stock.industry}</span>
          </div>
        ) : (
          <div className="flex items-baseline gap-3">
            <span className="w-8 shrink-0 text-[10px] text-slate-400">行业</span>
            <span className="text-slate-300">—</span>
          </div>
        )}
        {stock.concepts && stock.concepts.length > 0 ? (
          <div className="flex items-baseline gap-3">
            <span className="w-8 shrink-0 text-[10px] text-slate-400">概念</span>
            <span className="min-w-0 flex-1 text-slate-700">
              {stock.concepts.join(" · ")}
            </span>
          </div>
        ) : (
          <div className="flex items-baseline gap-3">
            <span className="w-8 shrink-0 text-[10px] text-slate-400">概念</span>
            <span className="text-slate-300">—</span>
          </div>
        )}
      </div>

      {/* Footer: 涨停 / 跌停 价 (永远 render, 没数据填 —) */}
      <div className="flex items-center divide-x divide-slate-100 border-t border-slate-100 bg-slate-50/40 text-[11px] tabular-nums">
        <div className="flex-1 px-3 py-1.5 text-center">
          <div className="text-[10px] text-slate-400">涨停</div>
          <div className="mt-0.5 text-slate-700">
            {stock.limitUpPrice != null
              ? Number(stock.limitUpPrice).toFixed(4)
              : "—"}
          </div>
        </div>
        <div className="flex-1 px-3 py-1.5 text-center">
          <div className="text-[10px] text-slate-400">跌停</div>
          <div className="mt-0.5 text-slate-700">
            {stock.limitDownPrice != null
              ? Number(stock.limitDownPrice).toFixed(4)
              : "—"}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------
function Cell({
  label,
  value,
  sub,
  tone,
  active,
  onClick,
}: {
  label: string
  value: string
  sub: string | null
  tone: "up" | "down" | "neutral"
  active?: boolean
  onClick?: () => void
}) {
  const ink =
    tone === "up"
      ? "text-red-600"
      : tone === "down"
        ? "text-emerald-600"
        : "text-slate-900"
  const interactive = !!onClick
  return (
    <div
      onClick={onClick}
      className={`bg-white px-4 py-3 transition-colors ${
        interactive ? "cursor-pointer hover:bg-slate-50" : ""
      } ${active ? "ring-2 ring-inset ring-sky-300" : ""}`}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
        {tone === "up" ? (
          <TrendingUp className="size-3.5" />
        ) : tone === "down" ? (
          <TrendingDown className="size-3.5" />
        ) : (
          <Activity className="size-3.5" />
        )}
        <span>{label}</span>
      </div>
      <div className={`mt-1 text-2xl font-bold tracking-tight tabular-nums ${ink}`}>
        {value}
      </div>
      {sub ? (
        <div
          className={`mt-0.5 text-[10px] ${
            active ? "font-semibold text-sky-600" : "text-slate-400"
          }`}
        >
          {sub}
        </div>
      ) : null}
    </div>
  )
}

function DistributionStrip({
  rows,
  isEmpty,
  loading,
  onClickStock,
}: {
  rows: NonNullable<LimitEmotionPayload["streak"]>["distribution"]
  isEmpty: boolean
  loading: boolean
  onClickStock: (stock: LimitEmotionStock) => void
}) {
  const [expandedStreak, setExpandedStreak] = useState<number | null>(null)
  const expandedRow =
    expandedStreak !== null ? rows.find((r) => r.streak === expandedStreak) : null

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-900">连板梯队</div>
        <div className="text-[11px] text-slate-500">
          从高到低 · 点击梯队展开具体股票
        </div>
      </div>
      {loading ? (
        <div className="h-10 w-full animate-pulse rounded-xl bg-slate-100" />
      ) : isEmpty ? (
        <div className="flex h-10 items-center justify-center text-xs text-slate-400">
          暂无连板梯队数据
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-10 items-center justify-center text-xs text-slate-400">
          当前无连板股 (首板 0 / 接力未打开)
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {rows.map((row) => {
              const maxCount = Math.max(...rows.map((r) => r.count), 1)
              const w = Math.max(28, Math.round((row.count / maxCount) * 120))
              const isTop = row.streak === Math.max(...rows.map((r) => r.streak))
              const isOpen = expandedStreak === row.streak
              return (
                <button
                  type="button"
                  key={row.streak}
                  onClick={() =>
                    setExpandedStreak(isOpen ? null : row.streak)
                  }
                  className={`inline-flex cursor-pointer items-center gap-1.5 rounded-xl border px-2.5 py-1.5 transition-colors ${
                    isOpen
                      ? "border-sky-300 bg-sky-50"
                      : isTop
                        ? "border-rose-200 bg-rose-50/60 hover:bg-rose-50"
                        : "border-slate-200 bg-slate-50/60 hover:bg-slate-50"
                  }`}
                  style={{ minWidth: w }}
                  title={
                    row.stocks.length > 0
                      ? row.stocks
                          .slice(0, 5)
                          .map((s) => `${s.code} ${s.name}`)
                          .join("、")
                      : `${row.streak}板 ${row.count} 只`
                  }
                >
                  <span
                    className={`text-sm font-bold tabular-nums ${
                      isOpen
                        ? "text-sky-700"
                        : isTop
                          ? "text-rose-700"
                          : "text-slate-700"
                    }`}
                  >
                    {row.streak}板
                  </span>
                  <span
                    className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${
                      isOpen
                        ? "bg-sky-200/80 text-sky-800"
                        : isTop
                          ? "bg-rose-200/80 text-rose-800"
                          : "bg-slate-200 text-slate-700"
                    }`}
                  >
                    ×{row.count}
                  </span>
                </button>
              )
            })}
          </div>

          {expandedRow && (
            <TierStockList
              streak={expandedRow.streak}
              count={expandedRow.count}
              stocks={expandedRow.stocks || []}
              onClose={() => setExpandedStreak(null)}
              onHoverStock={(stock, tone, rect) =>
                setHoveredStock({ stock, tone, rect })
              }
              onLeaveStock={() => setHoveredStock(null)}
              onClickStock={onClickStock}
            />
          )}
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// 展开后: 单个梯队的完整 stock list
// ---------------------------------------------------------------------------
function TierStockList({
  streak,
  count,
  stocks,
  onClose,
  onHoverStock,
  onLeaveStock,
  onClickStock,
}: {
  streak: number
  count: number
  stocks: LimitEmotionStock[]
  onClose: () => void
  onHoverStock: (stock: LimitEmotionStock, tone: StockTone, rect: DOMRect) => void
  onLeaveStock: () => void
  onClickStock: (stock: LimitEmotionStock) => void
}) {
  return (
    <div className="mt-3 border-t border-slate-200 pt-2.5">
      <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500">
        <span>
          <span className="font-semibold text-slate-700">{streak}板</span>
          <span className="ml-2 tabular-nums">{count} 只</span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="hover:text-slate-700"
        >
          收起
        </button>
      </div>
      <div className="grid grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {stocks.map((s) => {
          const tone: StockTone = streak >= 5 ? "up" : "neutral"
          return (
            <StockRow
              key={s.code}
              stock={s}
              tone={tone}
              onHover={(stock, rect) => onHoverStock(stock, tone, rect)}
              onLeave={onLeaveStock}
              onClick={onClickStock}
            />
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 单只股 row: 三行
//   name              14px medium
//   code + 涨跌%      11px (涨跌按 tone 上色)
//   行业 · 概念1, 概念2  10px 浅灰
// tone: 浅色底 (无边框无阴影) + hover 加深 + 涨跌幅字色
// ---------------------------------------------------------------------------
type StockTone = "up" | "down" | "broken" | "neutral"
function StockRow({
  stock,
  tone,
  onHover,
  onLeave,
  onClick,
}: {
  stock: LimitEmotionStock
  tone: StockTone
  onHover?: (stock: LimitEmotionStock, rect: DOMRect) => void
  onLeave?: () => void
  onClick?: (stock: LimitEmotionStock) => void
}) {
  const { code, name, changePct, industry, concepts } = stock
  const TONE: Record<
    StockTone,
    { bg: string; hover: string; change: string }
  > = {
    up: {
      bg: "bg-red-50/70",
      hover: "hover:bg-red-100/80",
      change: "text-red-600",
    },
    down: {
      bg: "bg-emerald-50/70",
      hover: "hover:bg-emerald-100/80",
      change: "text-emerald-600",
    },
    broken: {
      bg: "bg-amber-50/70",
      hover: "hover:bg-amber-100/80",
      change: "text-amber-600",
    },
    neutral: {
      bg: "bg-slate-50",
      hover: "hover:bg-slate-100",
      change: "text-slate-500",
    },
  }
  const t = TONE[tone]
  const cp =
    typeof changePct === "number" && Number.isFinite(changePct)
      ? changePct
      : null
  const conceptLine =
    concepts && concepts.length > 0
      ? concepts.slice(0, 3).join(" · ")
      : ""
  const cs = concepts ?? []
  const showConcepts = cs.slice(0, 3)
  const overflow = Math.max(0, cs.length - showConcepts.length)
  return (
    <div
      onMouseEnter={
        onHover
          ? (e) => onHover(stock, e.currentTarget.getBoundingClientRect())
          : undefined
      }
      onMouseLeave={onLeave}
      onClick={onClick ? () => onClick(stock) : undefined}
      className={`min-w-0 rounded-md px-2 py-1.5 transition-colors ${t.bg} ${t.hover} ${
        onClick ? "cursor-pointer" : ""
      }`}
      title={`${code} ${name}${industry ? " · " + industry : ""}${
        cs.length > 0 ? " · " + cs.join(" · ") : ""
      }`}
    >
      <div className="truncate text-sm font-medium text-slate-800">
        {name}
      </div>
      <div className="mt-0.5 flex items-baseline gap-1 truncate text-[11px]">
        <span className="font-mono tabular-nums text-slate-400">{code}</span>
        {cp != null ? (
          <>
            <span className="text-slate-300">·</span>
            <span className={`tabular-nums font-semibold ${t.change}`}>
              {cp >= 0 ? "+" : ""}
              {cp.toFixed(2)}%
            </span>
          </>
        ) : null}
      </div>
      {industry || cs.length > 0 ? (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {industry ? (
            <span
              className="inline-flex max-w-full items-center truncate rounded bg-slate-100 px-1.5 py-px text-[10px] font-medium text-slate-600"
              title={industry}
            >
              {industry}
            </span>
          ) : null}
          {showConcepts.map((c, i) => (
            <span
              key={i}
              className="inline-flex max-w-[10rem] items-center truncate rounded-full border border-slate-200 bg-white px-1.5 py-px text-[10px] text-slate-500"
              title={c}
            >
              {c}
            </span>
          ))}
          {overflow > 0 ? (
            <span className="text-[10px] tabular-nums text-slate-400">
              +{overflow}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function PromotionTable({
  promotion,
  isEmpty,
}: {
  promotion: NonNullable<LimitEmotionPayload["streak"]>["promotion"] | null
  isEmpty: boolean
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">连板晋级率</div>
          <div className="text-[11px] text-slate-500">
            N 板 → N+1 板 · 越高越健康
            {promotion?.overallRate != null
              ? ` · 整体 ${formatRate(promotion.overallRate)}`
              : ""}
          </div>
        </div>
      </div>
      <div className="px-4 py-3">
        {isEmpty ? (
          <div className="flex h-16 items-center justify-center text-xs text-slate-400">
            暂无晋级率数据
          </div>
        ) : !promotion || promotion.levels.length === 0 ? (
          <div className="flex h-16 items-center justify-center text-xs text-slate-400">
            昨日无连板股, 无晋级口径
          </div>
        ) : (
          <div className="space-y-2">
            {promotion.levels.map((lv) => {
              const rate = lv.rate
              const ink =
                rate == null
                  ? "text-slate-400"
                  : rate >= 0.5
                    ? "text-red-600"
                    : rate >= 0.3
                      ? "text-amber-600"
                      : "text-emerald-600"
              const barW = rate == null ? 0 : Math.max(4, Math.round(rate * 100))
              return (
                <div key={lv.from} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-700 tabular-nums">
                      {lv.from}进{lv.to}
                    </span>
                    <span className="text-slate-500 tabular-nums">
                      {lv.todayPromotedCount} / {lv.yesterdayCount}
                    </span>
                    <span className={`text-sm font-semibold tabular-nums ${ink}`}>
                      {formatRate(rate)}
                    </span>
                  </div>
                  <div className="relative h-1.5 rounded-full bg-slate-100">
                    <div
                      className={`absolute left-0 top-0 h-1.5 rounded-full ${
                        rate != null && rate >= 0.5
                          ? "bg-red-500"
                          : rate != null && rate >= 0.3
                            ? "bg-amber-500"
                            : "bg-emerald-500"
                      }`}
                      style={{ width: `${barW}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}

function BrokenList({
  broken,
  isEmpty,
}: {
  broken: NonNullable<LimitEmotionPayload["streak"]>["broken"] | null
  isEmpty: boolean
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">断板反馈</div>
          <div className="text-[11px] text-slate-500">
            昨日连板 · 今日未涨停 (高位 ≥ 3 板重点关注)
            {broken && broken.count > 0
              ? ` · 共 ${broken.count} 只 (高位 ${broken.highStreakBrokenCount})`
              : ""}
          </div>
        </div>
      </div>
      <div className="px-4 py-3">
        {isEmpty ? (
          <div className="flex h-16 items-center justify-center text-xs text-slate-400">
            暂无断板数据
          </div>
        ) : !broken || broken.stocks.length === 0 ? (
          <div className="flex h-16 items-center justify-center text-xs text-slate-400">
            昨日无连板股, 今日无断板
          </div>
        ) : (
          <div className="max-h-56 overflow-y-auto pr-1">
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="py-1 text-left font-semibold">代码</th>
                  <th className="py-1 text-left font-semibold">名称</th>
                  <th className="py-1 text-right font-semibold">昨日连板</th>
                  <th className="py-1 text-right font-semibold">今日涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                {broken.stocks.slice(0, 30).map((s) => {
                  const cp = s.changePct
                  const cpTone =
                    cp == null
                      ? "text-slate-400"
                      : cp >= 0
                        ? "text-red-600"
                        : "text-emerald-600"
                  const isHigh = s.previousStreak >= 3
                  return (
                    <tr
                      key={`${s.code}-${s.previousStreak}`}
                      className="border-t border-slate-100"
                    >
                      <td className="py-1 text-slate-500 tabular-nums">{s.code}</td>
                      <td className="py-1 text-slate-800">
                        {s.name}
                        {isHigh ? (
                          <span className="ml-1 rounded bg-rose-100 px-1 text-[9px] font-semibold text-rose-700">
                            高位
                          </span>
                        ) : null}
                      </td>
                      <td className="py-1 text-right font-semibold text-slate-700 tabular-nums">
                        {s.previousStreak}板
                      </td>
                      <td className={`py-1 text-right tabular-nums ${cpTone}`}>
                        {cp == null ? "—" : `${cp >= 0 ? "+" : ""}${cp.toFixed(2)}%`}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

export default LimitEmotionPanel
