/**
 * Market Sentiment 页面
 *
 * 4 张占位 + 3 张正式卡:
 *   1. Risk Appetite Spread    (跨资产, 替换原 Fear & Greed Index 占位)
 *   2. Market Breadth Grid     (4 张子卡: MA双多头 / 5日上涨 / 60日新低 / 252日新高, A股宽度)
 *   3. Limit Emotion Summary   (涨跌停情绪综合分, 替换原 News Sentiment 占位)
 *
 * 数据源:
 *   - 风险偏好:    duckdb.risk_appetite_daily  (cache-aside, /api/stock-chart/market-sentiment/risk-appetite)
 *   - 市场宽度:    duckdb.ma_count_daily       (cache-aside, /api/stock-chart/market-sentiment/ma-count)
 *   - 涨跌停情绪:  duckdb.limit_emotion_summary_daily (cache-aside, /market-sentiment/limit-emotion-summary)
 *
 * 后续接入: Bull-Bear Spread / Social Buzz / Margin & Leverage / Regime Tag 等。
 */
import { useEffect, useState } from "react"
import {
  Activity,
  Calendar,
  Flame,
  Heart,
  MessageSquareQuote,
  Smile,
  TrendingUp,
  Layers,
} from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  fetchMarketSentimentRiskAppetite,
  fetchMarketSentimentRiskAppetiteHistory,
  fetchMarketSentimentMaCount,
  fetchMarketSentimentMaCountHistory,
  fetchMarketSentimentLimitEmotionSummary,
  fetchMarketSentimentLimitEmotionSummaryHistory,
  type RiskAppetiteResponse,
  type RiskAppetiteHistoryItem,
  type MaCountResponse,
  type MaCountHistoryItem,
  type LimitEmotionSummary,
  type LimitEmotionSummaryHistoryItem,
  type LimitEmotionLevel,
} from "@/lib/api"

const PLACEHOLDER_CARDS = [
  {
    title: "Bull-Bear Spread",
    description: "多空比、融资融券余额变化、期权 PCR(占位)。",
  },
  {
    title: "Social Buzz",
    description: "雪球 / 东方财富吧 / X(推特)等社区讨论热度与情绪倾向(占位)。",
  },
  {
    title: "Margin & Leverage",
    description: "融资余额、场外杠杆、ETF 申赎信号(占位)。",
  },
  {
    title: "Regime Tag",
    description: "上行 / 震荡 / 下行 / 转折 的市场状态识别(占位)。",
  },
]

/**
 * 微型 sparkline (inline SVG, 无依赖). 跟 market-pulse-stats 里的实现等价,
 * 暂内联, 第 3 处出现时抽到 views/market/lib/sparkline.tsx
 * - 颜色按末值正负着色 (涨红跌绿)
 * - 自适应 Y 轴 (min/max)
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

/**
 * 市场宽度 4 张子卡 (MA 双多头 / 5日上涨 / 60日新低 / 252日新高)
 * - 走同一个 /api/stock-chart/market-sentiment/ma-count endpoint
 * - 历史用 /ma-count/history (近 30 天, sparkline 用)
 * - 4 张卡 grid 2x2, 跟原来 PulseStats 9 卡中的 4 张同名卡同数据, 仅换容器 (Card + shadcn)
 *
 * 颜色阈值 (跟原 PulseStats 保持一致, 避免观感漂移):
 *   - MA 双多头: ≥50% 红, 30-50% amber, <30% 绿
 *   - 5日上涨占比: ≥50% 红, 30-50% amber, <30% 绿
 *   - 60日新低占比: 越低越好 → 反向. ≥15% 红, 5-15% amber, <5% 绿
 *   - 252日新高占比: ≥20% 红, 5-20% amber, <5% 绿
 */
function MarketBreadthGrid({ date }: { date: string | null }) {
  const [data, setData] = useState<MaCountResponse | null>(null)
  const [history, setHistory] = useState<MaCountHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -30)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentMaCount(date ?? undefined),
          fetchMarketSentimentMaCountHistory(start, end),
        ])
        if (cancelled) return
        setData(snap)
        setHistory(hist.items ?? [])
      } catch {
        if (!cancelled) {
          setData(null)
          setHistory(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [date])

  // sparkline 序列 (按 tradeDate ASC, 限 30 天)
  const spark = (key: "pctAboveBoth" | "pctUp5d" | "pctNewLow60d" | "pctNewHigh252d"): number[] =>
    (history ?? [])
      .slice()
      .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
      .map((it) => it[key] ?? 0)

  // 4 张子卡定义 (数据 + 颜色阈值 + 副数)
  const total = data?.totalEligible ?? 0
  const cards: Array<{
    title: string
    pct: number | null
    num: number | null
    spark: number[]
    tone: string
  }> = [
    {
      title: "MA 双多头占比",
      pct: data?.pctAboveBoth ?? null,
      num: data?.aboveBoth ?? null,
      spark: spark("pctAboveBoth"),
      tone:
        data?.pctAboveBoth == null
          ? "text-slate-700"
          : data.pctAboveBoth >= 50
            ? "text-red-600"
            : data.pctAboveBoth >= 30
              ? "text-amber-600"
              : "text-emerald-600",
    },
    {
      title: "5日上涨占比",
      pct: data?.pctUp5d ?? null,
      num: data?.up5dCount ?? null,
      spark: spark("pctUp5d"),
      tone:
        data?.pctUp5d == null
          ? "text-slate-700"
          : data.pctUp5d >= 50
            ? "text-red-600"
            : data.pctUp5d >= 30
              ? "text-amber-600"
              : "text-emerald-600",
    },
    {
      title: "60日新低占比",
      pct: data?.pctNewLow60d ?? null,
      num: data?.newLow60dCount ?? null,
      spark: spark("pctNewLow60d"),
      tone:
        data?.pctNewLow60d == null
          ? "text-slate-700"
          : data.pctNewLow60d >= 15
            ? "text-red-600"
            : data.pctNewLow60d >= 5
              ? "text-amber-600"
              : "text-emerald-600",
    },
    {
      title: "252日新高占比",
      pct: data?.pctNewHigh252d ?? null,
      num: data?.newHigh252dCount ?? null,
      spark: spark("pctNewHigh252d"),
      tone:
        data?.pctNewHigh252d == null
          ? "text-slate-700"
          : data.pctNewHigh252d >= 20
            ? "text-red-600"
            : data.pctNewHigh252d >= 5
              ? "text-amber-600"
              : "text-emerald-600",
    },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-muted-foreground" />
          Market Breadth
        </CardTitle>
        <CardDescription>
          A股市场宽度: MA 双多头 / 5日上涨 / 60日新低 / 252日新高
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {cards.map((c) => (
              <div key={c.title} className="rounded-xl bg-muted/30 p-3">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] text-muted-foreground">{c.title}</div>
                  {c.spark.length >= 2 && <Sparkline values={c.spark} />}
                </div>
                <div className="mt-1 flex items-baseline gap-1.5">
                  <span className={`text-xl font-semibold tabular-nums ${c.tone}`}>
                    {c.pct == null ? "—" : `${c.pct.toFixed(1)}%`}
                  </span>
                  {total > 0 && c.num != null && (
                    <span className="text-[10px] tabular-nums text-muted-foreground">
                      {c.num}/{total}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * 风险偏好卡片
 * - 主显示: spread_weighted (沪深300 20日 - (511010+511090)/2 国债 ETF 20日)
 * - 副文: 511010 / 511090 两个分项 spread
 * - sparkline: 近 30 天 spread_weighted
 * - 颜色: spread > +0.5% 红, < -0.5% 绿, 中性 slate
 */
function RiskAppetiteSpreadCard({ date }: { date: string | null }) {
  const [data, setData] = useState<RiskAppetiteResponse | null>(null)
  const [history, setHistory] = useState<RiskAppetiteHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -30)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentRiskAppetite(date ?? undefined),
          fetchMarketSentimentRiskAppetiteHistory(start, end),
        ])
        if (cancelled) return
        setData(snap)
        setHistory(hist.items ?? [])
      } catch {
        if (!cancelled) {
          setData(null)
          setHistory(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [date])

  const spread = data?.spread?.weighted ?? null
  const tone =
    spread == null
      ? "text-slate-700"
      : spread > 0.5
        ? "text-red-600"
        : spread < -0.5
          ? "text-emerald-600"
          : "text-slate-700"
  const spread511010 = data?.spread?.["511010"] ?? null
  const spread511090 = data?.spread?.["511090"] ?? null

  // sparkline 序列 (按 tradeDate ASC, 限 30 天)
  const sparkValues: number[] = (history ?? [])
    .slice()
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
    .map((it) => it.spreadWeighted ?? 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingUp className="size-4 text-muted-foreground" />
          Risk Appetite Spread
        </CardTitle>
        <CardDescription>
          沪深300 20日收益 − (511010 + 511090) / 2 加权国债 ETF 20日收益
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-2xl font-semibold tabular-nums ${tone}`}>
                {spread == null ? "—" : `${spread > 0 ? "+" : ""}${spread.toFixed(2)}%`}
              </span>
              <span className="text-xs text-muted-foreground">主指标</span>
            </div>

            {(spread511010 != null || spread511090 != null) && (
              <div className="mt-2 flex gap-3 text-xs tabular-nums text-muted-foreground">
                {spread511010 != null && (
                  <span>
                    511010
                    <span className="ml-1 text-foreground">
                      {spread511010 > 0 ? "+" : ""}
                      {spread511010.toFixed(2)}%
                    </span>
                  </span>
                )}
                {spread511090 != null && (
                  <span>
                    511090
                    <span className="ml-1 text-foreground">
                      {spread511090 > 0 ? "+" : ""}
                      {spread511090.toFixed(2)}%
                    </span>
                  </span>
                )}
              </div>
            )}

            {sparkValues.length >= 2 && (
              <div className="mt-3">
                <Sparkline values={sparkValues} />
                <div className="mt-1 text-[10px] text-muted-foreground">近 30 日</div>
              </div>
            )}

            <div className="mt-3 text-[10px] leading-4 text-muted-foreground">
              阈值: ≥ +0.5% risk-on (红) · 中性 (slate) · ≤ -0.5% risk-off (绿)
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * 涨跌停情绪综合分 (短线情绪)
 * - 主显示: composite score (0-100) + level 标签 (hot/active/normal/weak/ice)
 * - 3 个 sub-metric (3 行小卡, 各带子得分):
 *     1) 涨跌停比      = limit_up / max(limit_down, 1)  (up_down_score, 0-100)
 *     2) 炸板率反向    = 100 - 100 × broken/touched     (break_board_score, 0-100, 越低越好)
 *     3) 昨日涨停收益  = AVG(今日 changePct) for codes where 昨日 isLimitUp (yesterday_return_score, 0-100)
 * - 综合分 = 0.4×涨跌停比 + 0.3×炸板率 + 0.3×昨日涨停收益
 * - sparkline: 近 30 天 composite
 * - level 颜色: hot 红 / active 橙 / normal slate / weak 蓝 / ice 灰
 */
const LEVEL_META: Record<LimitEmotionLevel, { label: string; tone: string; bg: string; chip: string }> = {
  hot:    { label: "火热",  tone: "text-red-600",    bg: "bg-red-50",    chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃",  tone: "text-orange-600", bg: "bg-orange-50", chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性",  tone: "text-slate-700",  bg: "bg-slate-50",  chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak:   { label: "弱势",  tone: "text-blue-600",   bg: "bg-blue-50",   chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice:    { label: "冰点",  tone: "text-slate-400",  bg: "bg-slate-100", chip: "border-slate-300 bg-slate-100 text-slate-500" },
}

function LimitEmotionCard({ date }: { date: string | null }) {
  const [data, setData] = useState<LimitEmotionSummary | null>(null)
  const [history, setHistory] = useState<LimitEmotionSummaryHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -30)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentLimitEmotionSummary(date ?? undefined),
          fetchMarketSentimentLimitEmotionSummaryHistory(start, end),
        ])
        if (cancelled) return
        setData(snap)
        setHistory(hist.items ?? [])
      } catch {
        if (!cancelled) {
          setData(null)
          setHistory(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [date])

  // sparkline 序列 (按 tradeDate ASC, 限 30 天)
  const sparkValues: number[] = (history ?? [])
    .slice()
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
    .map((it) => it.compositeScore ?? 0)

  const level = data?.level ?? "weak"
  const meta = LEVEL_META[level] ?? LEVEL_META.weak
  const composite = data?.compositeScore ?? null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="size-4 text-muted-foreground" />
          涨跌停情绪综合分
        </CardTitle>
        <CardDescription>
          短线情绪: 涨跌停比 + 炸板率 + 昨日涨停收益
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            {/* 主指标: composite + level chip */}
            <div className="flex items-baseline gap-2">
              <span className={`text-2xl font-semibold tabular-nums ${meta.tone}`}>
                {composite == null ? "—" : composite.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">综合分</span>
              <span className={`ml-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${meta.chip}`}>
                {meta.label}
              </span>
            </div>

            {/* 3 个 sub-metric 行 (指标值 + 子得分) */}
            <div className="mt-3 grid grid-cols-3 gap-2">
              <SubMetric
                title="涨跌停比"
                value={
                  data?.limitUpDownRatio == null
                    ? "—"
                    : `${data.limitUpCount}/${Math.max(data.limitDownCount, 1)}`
                }
                subValue={
                  data?.limitUpDownRatio == null
                    ? null
                    : `${data.limitUpDownRatio.toFixed(1)}:1`
                }
                score={data?.components?.upDownScore ?? null}
              />
              <SubMetric
                title="炸板率"
                value={
                  data?.breakBoardRate == null
                    ? "—"
                    : `${(data.breakBoardRate * 100).toFixed(1)}%`
                }
                subValue={
                  data == null
                    ? null
                    : `${data.brokenCount}/${data.touchedCount}`
                }
                score={data?.components?.breakBoardScore ?? null}
                invertTone
              />
              <SubMetric
                title="昨日涨停收益"
                value={
                  data?.yesterdayLimitUpAvgReturn == null
                    ? "—"
                    : `${data.yesterdayLimitUpAvgReturn > 0 ? "+" : ""}${data.yesterdayLimitUpAvgReturn.toFixed(2)}%`
                }
                subValue={
                  data == null
                    ? null
                    : `n=${data.yesterdayLimitUpCount}`
                }
                score={data?.components?.yesterdayReturnScore ?? null}
              />
            </div>

            {/* sparkline: 近 30 天 composite */}
            {sparkValues.length >= 2 && (
              <div className="mt-3">
                <Sparkline values={sparkValues} />
                <div className="mt-1 text-[10px] text-muted-foreground">近 30 日综合分</div>
              </div>
            )}

            <div className="mt-3 text-[10px] leading-4 text-muted-foreground">
              权重: 涨跌停比 40% · 炸板率 30% (反向) · 昨日涨停收益 30%
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * 1 个 sub-metric 小卡: 标题 + 主值 + 副值 (n=xx / ratio) + 子得分色块
 * - invertTone: 子得分反向 (炸板率高→得分低, 红色反而是"差", 跟其他两个相反)
 */
function SubMetric({
  title,
  value,
  subValue,
  score,
  invertTone = false,
}: {
  title: string
  value: string
  subValue: string | null
  score: number | null
  invertTone?: boolean
}) {
  // 跟 ma_count 卡同套色板:
  //   正向: ≥70 红 (好), 40-70 橙, <40 绿 (差)
  //   反向 (炸板率): 跟 ma_count "60 日新低" 一致, 越低越好 → 反向, ≥70 绿, 40-70 橙, <40 红
  const tone =
    score == null
      ? "text-slate-700"
      : invertTone
        ? score >= 70
          ? "text-emerald-600"
          : score >= 40
            ? "text-amber-600"
            : "text-red-600"
        : score >= 70
          ? "text-red-600"
          : score >= 40
            ? "text-amber-600"
            : "text-emerald-600"
  return (
    <div className="rounded-xl bg-muted/30 p-2.5">
      <div className="text-[10px] text-muted-foreground">{title}</div>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className={`text-sm font-semibold tabular-nums ${tone}`}>{value}</span>
        {subValue && (
          <span className="text-[10px] tabular-nums text-muted-foreground">{subValue}</span>
        )}
      </div>
      {score != null && (
        <div className="mt-0.5 text-[10px] tabular-nums text-muted-foreground">
          得分 {score.toFixed(0)}
        </div>
      )}
    </div>
  )
}

function isoDateNDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

/** 把 YYYY-MM-DD 字符串往前/后 shift n 天 (n 可负). 用 UTC 解析避免本地时区偏移. */
function shiftIsoDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map((s) => parseInt(s, 10))
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + n)
  return dt.toISOString().slice(0, 10)
}

export default function MarketSentimentPage() {
  // null = 后端默认行为 (上一交易日). 用 string 是为了把日期显式传到 3 张卡,
  // 它们的 useEffect 以 date 为依赖, 切换时自动重拉.
  const [date, setDate] = useState<string | null>(null)
  const reset = () => setDate(null)
  const effective = date ?? "今日 (默认上一交易日)"

  return (
    <WorkspaceShell sectionLabel="Market Sentiment" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Smile className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Market Sentiment
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            市场情绪:风险偏好 / 多空对比 / 舆情 / 融资杠杆等信号。
          </p>
        </div>
        {/* 日期选择: 切换 date 后 3 张正式卡 + history 一起重拉 */}
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-2 text-xs">
          <Calendar className="size-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">回看日期</span>
          <input
            type="date"
            value={date ?? ""}
            max={isoDateNDaysAgo(0)}
            onChange={(e) => setDate(e.target.value || null)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs tabular-nums text-foreground outline-none focus:ring-1 focus:ring-ring"
            aria-label="选择历史日期"
          />
          <span className="text-muted-foreground">·</span>
          <span className="font-medium text-foreground">{effective}</span>
          {date && (
            <button
              type="button"
              onClick={reset}
              className="ml-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              重置
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* 风险偏好 — 已落地 (替换原 Fear & Greed Index 占位) */}
        <RiskAppetiteSpreadCard date={date} />

        {/* 市场宽度 — 4 张子卡 (MA双多头 / 5日上涨 / 60日新低 / 252日新高) */}
        <MarketBreadthGrid date={date} />

        {/* 涨跌停情绪综合分 — 已落地 (替换原 News Sentiment 占位) */}
        <LimitEmotionCard date={date} />

        {/* 其余占位卡 (4 张) */}
        {PLACEHOLDER_CARDS.map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Heart className="size-4 text-muted-foreground" />
                {item.title}
              </CardTitle>
              <CardDescription>Mock · 待接入</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-5 text-sm text-muted-foreground">
        <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
          <MessageSquareQuote className="size-4" />
          路线
        </div>
        后续接入 backend/services/stock/market_overview/sentiment.py,以及情绪相关调度任务,提供分钟级 / 日级的情绪分位曲线。
      </div>
    </WorkspaceShell>
  )
}
