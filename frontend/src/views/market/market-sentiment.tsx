/**
 * Market Sentiment 页面
 *
 * 顶部 1 张 composite 大卡 + 9 张子卡 (md:grid-cols-3, 3 行):
 *   Top:   Market Sentiment Index (9 张卡加权, composite_score 0-100)
 *   Row 1: Risk Appetite | Market Breadth (合成) | 252 日新高
 *   Row 2: Sector Breadth | Turnover Activity | Limit Emotion
 *   Row 3: Volatility Sentiment | Style Risk Appetite | Profit Effect
 *
 * + 4 张占位卡 (规划中: Bull-Bear / Social Buzz / Margin / Regime)
 *
 * 数据源:
 *   - 合成指数:  duckdb.market_sentiment_index_daily    (cache-aside, 9 子卡加权)
 *   - 风险偏好:    duckdb.risk_appetite_daily           (cache-aside)
 *   - 市场广度:    duckdb.ma_count_daily                (cache-aside, 合成得分)
 *   - 252 日新高:  duckdb.ma_count_daily                (cache-aside, 价强)
 *   - 板块扩散:    duckdb.market_pulse_sector_breadth_daily (cache-aside)
 *   - 成交活跃度:  duckdb.turnover_activity_daily       (cache-aside)
 *   - 涨跌停情绪:  duckdb.limit_emotion_summary_daily   (cache-aside)
 *   - 波动率情绪:  duckdb.volatility_sentiment_daily    (cache-aside)
 *   - 风格风险偏好: duckdb.style_risk_appetite_daily    (cache-aside)
 *   - 赚钱效应:    duckdb.profit_effect_daily           (cache-aside, 分项④)
 *
 * Sparkline: Recharts AreaChart (40-60px 高 + hover tooltip).
 * 日期选择: shadcn DatePicker (Popover + Calendar).
 */
import { useEffect, useMemo, useRef, useState } from "react"
import {
  Activity,
  Calendar,
  Flame,
  Gauge,
  Heart,
  Layers,
  MessageSquareQuote,
  RotateCcw,
  Scale,
  Smile,
  TrendingUp,
} from "lucide-react"
import { Area, AreaChart, ResponsiveContainer, Tooltip, type TooltipContentProps } from "recharts"
import * as echarts from "echarts/core"
import { LineChart } from "echarts/charts"
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  DataZoomComponent,
  MarkLineComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"
import type { EChartsOption } from "echarts"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { DatePicker } from "@/components/ui/date-picker"
import { toLocalIso } from "@/lib/date-utils"
import { cn } from "@/lib/utils"
import {
  fetchMarketSentimentRiskAppetite,
  fetchMarketSentimentRiskAppetiteHistory,
  fetchMarketSentimentMaCount,
  fetchMarketSentimentMaCountHistory,
  fetchMarketSentimentLimitEmotionSummary,
  fetchMarketSentimentLimitEmotionSummaryHistory,
  fetchMarketSentimentSectorBreadth,
  fetchMarketSentimentSectorBreadthHistory,
  fetchMarketSentimentVolatilitySentiment,
  fetchMarketSentimentVolatilitySentimentHistory,
  fetchMarketSentimentTurnoverActivity,
  fetchMarketSentimentTurnoverActivityHistory,
  fetchMarketSentimentStyleRiskAppetite,
  fetchMarketSentimentStyleRiskAppetiteHistory,
  fetchMarketSentimentProfitEffect,
  fetchMarketSentimentProfitEffectHistory,
  fetchMarketSentimentIndex,
  fetchMarketSentimentIndexHistory,
  type RiskAppetiteResponse,
  type RiskAppetiteHistoryItem,
  type MaCountResponse,
  type MaCountHistoryItem,
  type LimitEmotionSummary,
  type LimitEmotionSummaryHistoryItem,
  type LimitEmotionLevel,
  type SectorBreadthItem,
  type VolatilitySentimentResponse,
  type VolatilitySentimentItem,
  type TurnoverActivityResponse,
  type TurnoverActivityHistoryItem,
  type StyleRiskAppetiteResponse,
  type StyleRiskAppetiteHistoryItem,
  type ProfitEffectResponse,
  type ProfitEffectHistoryItem,
  type MarketSentimentIndexResponse,
  type MarketSentimentIndexComponents,
  type MarketSentimentIndexHistoryItem,
} from "@/lib/api"

const PLACEHOLDER_CHIPS = [
  { title: "Bull-Bear Spread", desc: "多空比 / 融资融券 / 期权 PCR" },
  { title: "Social Buzz", desc: "雪球 / 股吧 / X 社区热度" },
  { title: "Margin & Leverage", desc: "融资余额 / 杠杆 / ETF 申赎" },
  { title: "Regime Tag", desc: "上行 / 震荡 / 下行 / 转折 状态" },
]

// ---------------------------------------------------------------------------
// Recharts 折线图 (替代内联 SVG sparkline, 60px 高 + hover tooltip)
// ---------------------------------------------------------------------------
interface SparkPoint { date: string; value: number }
interface SparklineProps {
  data: SparkPoint[]
  /** 线条颜色: 默认按末值 vs 首值 (涨红跌绿). 传 null 用中性. */
  color?: "auto" | "neutral" | "inverse"
  height?: number
  /** inverse: 末值越大越红 (适用 vol, score) */
  formatter?: (v: number) => string
}
function Sparkline({ data, color = "auto", height = 60, formatter }: SparklineProps) {
  if (!data || data.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-end text-[10px] text-slate-300"
      >
        —
      </div>
    )
  }
  const first = data[0].value
  const last = data[data.length - 1].value
  let stroke: string
  if (color === "neutral") {
    stroke = "#64748b"
  } else if (color === "inverse") {
    // 末值越大越红 (vol, risk score 这类)
    stroke = last > first ? "#dc2626" : last < first ? "#059669" : "#64748b"
  } else {
    // auto: 末值 vs 首值 (涨红跌绿)
    stroke = last > first ? "#dc2626" : last < first ? "#059669" : "#64748b"
  }
  return (
    <div style={{ height, width: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <defs>
            <linearGradient id={`spark-grad-${stroke.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Tooltip
            cursor={{ stroke: "#94a3b8", strokeDasharray: "2 2" }}
            content={((props: TooltipContentProps<number, string>) => {
              if (!props.active || !props.payload?.length) return null
              const p = props.payload[0].payload as unknown as SparkPoint
              return (
                <div className="rounded-md border border-border/50 bg-background px-2 py-1 text-[11px] shadow-md">
                  <div className="text-muted-foreground">{p.date}</div>
                  <div className="font-mono font-semibold tabular-nums text-foreground">
                    {formatter ? formatter(p.value) : p.value.toFixed(2)}
                  </div>
                </div>
              )
            }) as never}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.5}
            fill={`url(#spark-grad-${stroke.replace("#", "")})`}
            dot={false}
            activeDot={{ r: 3, fill: stroke, stroke: "#fff", strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function toSparkData<T extends { tradeDate: string }>(
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

// ---------------------------------------------------------------------------
// ECharts 情绪分趋势折线 (composite 大卡左侧专用)
// 视觉: smooth line + 双面积围绕 50 中性线 (上红橙扩张 / 下蓝绿收缩) +
//        50 markLine + hover tooltip + inside slider dataZoom.
// Y 轴固定 0-100, 主叙事 = 50 上是扩张 / 50 下是收缩.
// ---------------------------------------------------------------------------
echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  CanvasRenderer,
])

interface SentimentLinePoint { date: string; value: number; level?: string }
interface SentimentLineProps {
  data: SentimentLinePoint[]
  height?: number
  /** 用浅色主题 (默认 false, 大卡深底浅字) */
  light?: boolean
}

function SentimentLine({ data, height = 220, light = false }: SentimentLineProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((d) => d.date)
    const values = data.map((d) => d.value)

    const latestValue = values[values.length - 1] ?? 50
    const mainLineColor = latestValue >= 50 ? "#f97316" : "#38bdf8"

    const minValue = values.length ? Math.min(...values) : 0
    const maxValue = values.length ? Math.max(...values) : 100
    const valueRange = Math.max(1, maxValue - minValue)
    // Y 轴 padding 收紧到 10%, 让 18 分差距看起来更剧烈 (不再像 0-100 那么平)
    const padding = Math.max(3, valueRange * 0.10)

    // 默认 dataZoom 进入最近 ~63 个交易日 (≈ 3 个月); 用户可拖回全量
    // total=770 时 start≈91.8, total=60 时 start=0 (数据不够也铺满)
    const recentBars = 63
    const totalBars = values.length
    const zoomStart = totalBars > recentBars
      ? Math.max(0, 100 - (recentBars / totalBars) * 100)
      : 0

    /**
     * 动态缩放：
     * - 始终尽量包含 50 中性线；
     * - 不再固定 0-100；
     * - 但上下限仍限制在 0-100。
     */
    const yMin = Math.max(0, Math.floor(Math.min(minValue, 50) - padding))
    const yMax = Math.min(100, Math.ceil(Math.max(maxValue, 50) + padding))

    /**
     * 上下区域数据：
     * - bullData：只显示 50 以上区域；
     * - bearData：只显示 50 以下区域。
     */
    const bullData = values.map((v) => (v >= 50 ? v : 50))
    const bearData = values.map((v) => (v < 50 ? v : 50))

    const fg = light ? "#475569" : "#94a3b8"
    const fgStrong = light ? "#0f172a" : "#e2e8f0"
    const axisLine = light ? "rgba(15, 23, 42, 0.12)" : "rgba(148, 163, 184, 0.28)"
    const splitLine = light ? "rgba(15, 23, 42, 0.06)" : "rgba(148, 163, 184, 0.10)"

    return {
      backgroundColor: "transparent",

      grid: {
        left: 38,
        right: 18,
        top: 18,
        bottom: 44,
        containLabel: false,
      },

      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
          lineStyle: {
            color: "rgba(148, 163, 184, 0.45)",
            width: 1,
          },
        },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "rgba(148, 163, 184, 0.25)",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: {
          color: "#e5e7eb",
          fontSize: 12,
        },
        formatter: (params: unknown) => {
          const arr = params as Array<{
            axisValueLabel: string
            value: number
            dataIndex: number
            seriesName: string
          }>

          if (!arr || !arr.length) return ""

          const realPoint = arr.find((p) => p.seriesName === "市场情绪指数") ?? arr[0]
          const idx = realPoint.dataIndex
          const score = Number(values[idx] ?? realPoint.value)
          const diff = score - 50

          const moodLabel =
            score >= 70 ? "极热"
            : score >= 60 ? "偏热"
            : score >= 50 ? "偏多"
            : score >= 40 ? "偏弱"
            : score >= 30 ? "低迷"
            : "冰点"

          const moodColor =
            score >= 70 ? "#ef4444"
            : score >= 60 ? "#f97316"
            : score >= 50 ? "#f59e0b"
            : score >= 40 ? "#38bdf8"
            : score >= 30 ? "#60a5fa"
            : "#94a3b8"

          return `
            <div style="font-weight:600;margin-bottom:6px;">${realPoint.axisValueLabel}</div>
            <div>情绪分: <b style="color:${moodColor};font-size:14px;">${score.toFixed(1)}</b></div>
            <div style="margin-top:3px;">状态: <span style="color:${moodColor};">${moodLabel}</span></div>
            <div style="margin-top:3px;color:#94a3b8;">距离中性线: ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}</div>
          `
        },
      },

      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates,
        axisLine: {
          lineStyle: {
            color: axisLine,
          },
        },
        axisTick: {
          show: false,
        },
        axisLabel: {
          color: fg,
          fontSize: 10,
          margin: 10,
        },
      },

      yAxis: {
        type: "value",
        min: yMin,
        max: yMax,
        splitNumber: 4,
        axisLabel: {
          color: fg,
          fontSize: 10,
          formatter: "{value}",
        },
        splitLine: {
          lineStyle: {
            color: splitLine,
          },
        },
        axisLine: {
          show: false,
        },
        axisTick: {
          show: false,
        },
      },

      dataZoom: [
        {
          type: "inside",
          start: zoomStart,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
        {
          type: "slider",
          start: zoomStart,
          end: 100,
          height: 18,
          bottom: 6,
          borderColor: "transparent",
          backgroundColor: light ? "rgba(15,23,42,0.04)" : "rgba(148,163,184,0.08)",
          fillerColor: light ? "rgba(15,23,42,0.10)" : "rgba(148,163,184,0.18)",
          handleStyle: {
            color: light ? "#94a3b8" : "#64748b",
          },
          textStyle: {
            color: fg,
            fontSize: 10,
          },
        },
      ],

      series: [
        {
          name: "多头区域",
          type: "line",
          data: bullData,
          symbol: "none",
          smooth: 0.2,
          lineStyle: {
            width: 0,
            opacity: 0,
          },
          areaStyle: {
            origin: 50,
            opacity: 0.34,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(239, 68, 68, 0.42)" },
              { offset: 0.55, color: "rgba(249, 115, 22, 0.20)" },
              { offset: 1, color: "rgba(249, 115, 22, 0.02)" },
            ]),
          },
          emphasis: {
            disabled: true,
          },
          tooltip: {
            show: false,
          },
          z: 1,
        },

        {
          name: "空头区域",
          type: "line",
          data: bearData,
          symbol: "none",
          smooth: 0.2,
          lineStyle: {
            width: 0,
            opacity: 0,
          },
          areaStyle: {
            origin: 50,
            opacity: 0.32,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(14, 165, 233, 0.02)" },
              { offset: 0.45, color: "rgba(14, 165, 233, 0.18)" },
              { offset: 1, color: "rgba(37, 99, 235, 0.38)" },
            ]),
          },
          emphasis: {
            disabled: true,
          },
          tooltip: {
            show: false,
          },
          z: 1,
        },

        {
          name: "市场情绪指数",
          type: "line",
          data: values,
          smooth: 0.2,
          symbol: "circle",
          showSymbol: false,
          symbolSize: 6,
          sampling: "lttb",

          /**
           * 主线颜色：
           * - 最新值 >= 50：橙红；
           * - 最新值 < 50：蓝色。
           */
          lineStyle: {
            width: 2.8,
            color: mainLineColor,
            shadowBlur: 14,
            shadowColor:
              latestValue >= 50
                ? "rgba(249, 115, 22, 0.55)"
                : "rgba(56, 189, 248, 0.55)",
          },

          itemStyle: {
            color: mainLineColor,
            borderColor: light ? "#ffffff" : "#0f172a",
            borderWidth: 1,
          },

          emphasis: {
            focus: "series",
            scale: true,
            lineStyle: {
              width: 3.4,
            },
          },

          markLine: {
            symbol: "none",
            silent: true,
            label: {
              color: fgStrong,
              fontSize: 11,
              fontWeight: 600,
              formatter: "中性线 50",
              position: "insideEndTop",
              backgroundColor: light ? "rgba(15,23,42,0.04)" : "rgba(226,232,240,0.10)",
              padding: [2, 5],
              borderRadius: 3,
            },
            lineStyle: {
              type: "solid",
              color: light ? "rgba(15, 23, 42, 0.65)" : "rgba(226, 232, 240, 0.70)",
              width: 1.6,
            },
            data: [
              {
                yAxis: 50,
                name: "中性线",
              },
            ],
          },

          z: 3,
        },
      ],
    }
  }, [data, light])

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, { renderer: "canvas" })
    }
    chartRef.current.setOption(option, { notMerge: true })
    const onWinResize = () => chartRef.current?.resize()
    window.addEventListener("resize", onWinResize)
    // 监听容器尺寸变化 (grid/flex 调整父宽时也会触发)
    const ro = new ResizeObserver(() => chartRef.current?.resize())
    ro.observe(ref.current)
    return () => {
      window.removeEventListener("resize", onWinResize)
      ro.disconnect()
    }
  }, [option])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  if (!data || data.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-xs text-slate-300"
      >
        暂无趋势数据
      </div>
    )
  }

  return <div ref={ref} style={{ width: "100%", height }} />
}

// ---------------------------------------------------------------------------
// 工具: ISO 日期处理 (本地时区, 避免 +8 时区下 toISOString 回退一天)
// ---------------------------------------------------------------------------
function isoDateNDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return toLocalIso(d)
}
function shiftIsoDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map((s) => parseInt(s, 10))
  // 本地 00:00, setDate 用本地方法避免跨月/跨年漂移
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + n)
  return toLocalIso(dt)
}

// ---------------------------------------------------------------------------
// Card 1: Risk Appetite Spread
// ---------------------------------------------------------------------------
function RiskAppetiteCard({ date }: { date: string | null }) {
  const [data, setData] = useState<RiskAppetiteResponse | null>(null)
  const [history, setHistory] = useState<RiskAppetiteHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
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

  const score = data?.score ?? null
  const rawValue = data?.rawValue ?? null
  const spread511010 = data?.spread?.["511010"] ?? null
  const spread511090 = data?.spread?.["511090"] ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-emerald-600"
  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingUp className="size-4 text-muted-foreground" />
          Risk Appetite Spread
        </CardTitle>
        <CardDescription>
          沪深300 20日 − (511010 + 511090) / 2 国债 ETF 20日
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score == null ? "—" : score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                沪深300跑赢债券ETF {rawValue > 0 ? "+" : ""}{rawValue.toFixed(2)}%
                {score != null && <span> · 高于过去3年{score.toFixed(0)}%的时间</span>}
              </div>
            )}

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

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分 (历史分位)</div>
            </div>

            <div className="mt-2 text-[10px] leading-4 text-muted-foreground">
              阈值: ≥70 risk-on (红) · 中性 (slate) · &lt;40 risk-off (绿)
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card 2: Market Breadth (4 张子卡)
// ---------------------------------------------------------------------------
function MarketBreadthCard({ date }: { date: string | null }) {
  const [data, setData] = useState<MaCountResponse | null>(null)
  const [history, setHistory] = useState<MaCountHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
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
    return () => { cancelled = true }
  }, [date])

  const w1 = 0.40, w2 = 0.35, w3 = 0.25
  const adv = data?.pctAdvancing ?? 0
  const ma20 = data?.pctAboveMa20 ?? 0
  const ma60 = data?.pctAboveMa60 ?? 0
  const composite = w1 * adv + w2 * ma20 + w3 * ma60

  const tone =
    composite == null || data == null
      ? "text-slate-700"
      : composite >= 60
        ? "text-red-600"
        : composite >= 40
          ? "text-amber-600"
          : "text-emerald-600"
  const levelLabel =
    composite >= 60 ? "强势" : composite >= 40 ? "中性" : "弱势"
  const levelBadge =
    composite >= 60
      ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
      : composite >= 40
        ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"

  const sparkData = toSparkData(
    history,
    (it) => w1 * (it.pctAdvancing ?? 0) + w2 * (it.pctAboveMa20 ?? 0) + w3 * (it.pctAboveMa60 ?? 0),
  )

  const rows: Array<{ label: string; pct: number; weight: number }> = [
    { label: "上涨占比", pct: adv, weight: w1 * 100 },
    { label: "MA20 占比", pct: ma20, weight: w2 * 100 },
    { label: "MA60 占比", pct: ma60, weight: w3 * 100 },
  ]

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-muted-foreground" />
          Market Breadth
        </CardTitle>
        <CardDescription>
          加权合成: 40%上涨 + 35%MA20 + 25%MA60
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : data == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="space-y-3">
            {/* 综合得分 */}
            <div className="flex items-baseline gap-3">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {composite.toFixed(1)}
              </span>
              <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${levelBadge}`}>
                {levelLabel}
              </span>
            </div>

            {/* 子项 */}
            <div className="space-y-1.5">
              {rows.map((r) => (
                <div key={r.label} className="flex items-center gap-2 text-xs">
                  <span className="w-16 text-muted-foreground">{r.label}</span>
                  <div className="flex-1 h-2 rounded-full bg-muted/30 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-foreground/20 transition-all"
                      style={{ width: `${Math.min(r.pct, 100)}%` }}
                    />
                  </div>
                  <span className="w-12 text-right tabular-nums text-foreground/80">
                    {r.pct.toFixed(1)}%
                  </span>
                  <span className="w-8 text-right text-muted-foreground">{r.weight}%</span>
                </div>
              ))}
            </div>

            {/* Sparkline */}
            <div className="-mx-1">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => `${v.toFixed(1)}分`}
              />
            </div>

            {/* 等级说明 */}
            <div className="flex gap-3 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥60 强势</span>
              <span className="text-amber-600/70">40-60 中性</span>
              <span className="text-emerald-600/70">＜40 弱势</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card N: 252 日新高
// ---------------------------------------------------------------------------
function NewHigh252dCard({ date }: { date: string | null }) {
  const [data, setData] = useState<MaCountResponse | null>(null)
  const [history, setHistory] = useState<MaCountHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
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
    return () => { cancelled = true }
  }, [date])

  const total = data?.totalEligible ?? 0
  const pct = data?.pctNewHigh252d ?? null
  const cnt = data?.newHigh252dCount ?? null
  const score = data?.newHigh252dScore ?? null
  const rawValue = data?.newHigh252dRawValue ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-amber-600"
          : "text-slate-700"
  const sparkData = toSparkData(history, (it) => it.newHigh252dScore ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingUp className="size-4 text-muted-foreground" />
          252日新高
        </CardTitle>
        <CardDescription>
          创 252 日新高占比 · 历史分位
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>
            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                {cnt} / {total} 只 ({rawValue.toFixed(1)}%)
                <span> · 高于过去3年{score.toFixed(0)}%的时间</span>
              </div>
            )}
            {total > 0 && cnt != null && !rawValue && (
              <div className="mt-1 text-xs text-muted-foreground">
                {cnt} / {total} 只
              </div>
            )}
            <div className="-mx-1 mt-2">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
// ---------------------------------------------------------------------------
function SectorBreadthCard({ date }: { date: string | null }) {
  const [data, setData] = useState<SectorBreadthItem | null>(null)
  const [history, setHistory] = useState<SectorBreadthItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentSectorBreadth(date ?? undefined),
          fetchMarketSentimentSectorBreadthHistory(30, end),
        ])
        if (cancelled) return
        if (snap.ok && snap.total > 0) {
          setData({
            tradeDate: snap.tradeDate,
            advancing: snap.advancing,
            declining: snap.declining,
            flat: snap.flat,
            total: snap.total,
            advancePct: snap.advancePct,
            source: snap.source,
            elapsedMs: snap.elapsedMs,
            fromCache: snap.fromCache,
          })
        } else {
          setData(null)
        }
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

  const advPct = data ? data.advancePct * 100 : null
  // score 优先用后端返回的 0-100 (advancePct × 100), fallback 同样算法
  const score100 = data?.score ?? advPct
  const tone =
    score100 == null
      ? "text-slate-700"
      : score100 >= 50
        ? "text-red-600"
        : score100 >= 30
          ? "text-amber-600"
          : "text-emerald-600"
  const sparkData = toSparkData(
    history,
    (it) => it.score ?? it.advancePct * 100,
  )

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-muted-foreground" />
          Sector Breadth
        </CardTitle>
        <CardDescription>
          同花顺 90 行业 上涨数 / 总数
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {advPct == null ? "—" : `${advPct.toFixed(1)}%`}
              </span>
              {data && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {data.advancing}/{data.total}
                </span>
              )}
            </div>

            {data && (
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-muted-foreground">
                <span>
                  上涨 <span className="ml-1 text-red-600">{data.advancing}</span>
                </span>
                <span>
                  下跌 <span className="ml-1 text-emerald-600">{data.declining}</span>
                </span>
                {data.flat > 0 && (
                  <span>
                    平盘 <span className="ml-1 text-foreground">{data.flat}</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => `${v.toFixed(1)}%`} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日 advance_pct</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card 4: Limit Emotion Summary
// ---------------------------------------------------------------------------
const LEVEL_META: Record<
  LimitEmotionLevel,
  { label: string; tone: string; chip: string }
> = {
  hot: { label: "火热", tone: "text-red-600", chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃", tone: "text-orange-600", chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性", tone: "text-slate-700", chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak: { label: "弱势", tone: "text-blue-600", chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice: { label: "冰点", tone: "text-slate-400", chip: "border-slate-300 bg-slate-100 text-slate-500" },
}

function LimitEmotionCard({ date }: { date: string | null }) {
  const [data, setData] = useState<LimitEmotionSummary | null>(null)
  const [history, setHistory] = useState<LimitEmotionSummaryHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
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

  const sparkData = toSparkData(history, (it) => it.compositeScore)
  const level = data?.level ?? "weak"
  const meta = LEVEL_META[level] ?? LEVEL_META.weak
  const composite = data?.compositeScore ?? null

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="size-4 text-muted-foreground" />
          涨跌停情绪综合分
        </CardTitle>
        <CardDescription>
          涨跌停比 40% · 炸板率 30% (反向) · 昨日涨停收益 30%
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${meta.tone}`}>
                {composite == null ? "—" : composite.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">综合分</span>
              <span
                className={cn(
                  "ml-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  meta.chip
                )}
              >
                {meta.label}
              </span>
            </div>

            {data && (
              <div className="mt-3 grid grid-cols-3 gap-2">
                <SubMetric
                  title="涨跌停比"
                  value={`${data.limitUpCount}/${Math.max(data.limitDownCount, 1)}`}
                  subValue={
                    data.limitUpDownRatio == null ? null : `${data.limitUpDownRatio.toFixed(1)}:1`
                  }
                  score={data.components?.upDownScore ?? null}
                />
                <SubMetric
                  title="炸板率"
                  value={
                    data.breakBoardRate == null
                      ? "—"
                      : `${(data.breakBoardRate * 100).toFixed(1)}%`
                  }
                  subValue={`${data.brokenCount}/${data.touchedCount}`}
                  score={data.components?.breakBoardScore ?? null}
                  invertTone
                />
                <SubMetric
                  title="昨日涨停收益"
                  value={
                    data.yesterdayLimitUpAvgReturn == null
                      ? "—"
                      : `${data.yesterdayLimitUpAvgReturn > 0 ? "+" : ""}${data.yesterdayLimitUpAvgReturn.toFixed(2)}%`
                  }
                  subValue={`n=${data.yesterdayLimitUpCount}`}
                  score={data.components?.yesterdayReturnScore ?? null}
                />
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日综合分</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

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
        <span className={cn("text-sm font-semibold tabular-nums", tone)}>{value}</span>
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

// ---------------------------------------------------------------------------
// Card 5: Turnover Activity (成交活跃度)
// ---------------------------------------------------------------------------
function TurnoverActivityCard({ date }: { date: string | null }) {
  const [data, setData] = useState<TurnoverActivityResponse | null>(null)
  const [history, setHistory] = useState<TurnoverActivityHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentTurnoverActivity(date ?? undefined),
          fetchMarketSentimentTurnoverActivityHistory(start, end),
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

  const score = data?.score ?? null
  const rawValue = data?.rawValue ?? null
  const totalAmount = data?.totalAmount ?? null
  const avgAmount = data?.avg20dAmount ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-slate-500"
  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          成交活跃度
        </CardTitle>
        <CardDescription>
          今日成交额 / 过去 20 日平均成交额 · 历史分位
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score == null ? "—" : score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                成交额 {(rawValue * 100).toFixed(0)}% · 高于过去3年{score!.toFixed(0)}%的时间
              </div>
            )}

            {(totalAmount != null || avgAmount != null) && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                {totalAmount != null && (
                  <span>
                    今日
                    <span className="ml-1 text-foreground">{totalAmount.toFixed(0)}亿</span>
                  </span>
                )}
                {avgAmount != null && (
                  <span>
                    20日均
                    <span className="ml-1 text-foreground">{avgAmount.toFixed(0)}亿</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline data={sparkData} color="neutral" formatter={(v) => v.toFixed(1)} />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分 (历史分位)</div>
            </div>

            <div className="mt-2 text-[10px] leading-4 text-muted-foreground">
              阈值: ≥70 放量 (红) · 中性 (slate) · &lt;40 缩量
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card 6: Volatility Sentiment
// ---------------------------------------------------------------------------
function VolatilitySentimentCard({ date }: { date: string | null }) {
  const [data, setData] = useState<VolatilitySentimentResponse | null>(null)
  const [history, setHistory] = useState<VolatilitySentimentItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentVolatilitySentiment(date ?? undefined),
          fetchMarketSentimentVolatilitySentimentHistory(start, end),
        ])
        if (cancelled) return
        setData(snap.ok ? snap : null)
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

  const score = data?.sentimentScore ?? null
  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-emerald-600"
        : score >= 40
          ? "text-slate-700"
          : "text-red-600"
  const sparkData = toSparkData(history, (it) => it.sentimentScore)
  const vol = data?.realizedVol20d ?? null
  const pct = data?.percentile1y ?? null
  const dailyRet = data?.dailyReturnPct ?? null
  const dailyRetText =
    dailyRet == null ? null : `${dailyRet > 0 ? "+" : ""}${dailyRet.toFixed(2)}%`
  const dailyRetTone =
    dailyRet == null
      ? "text-foreground"
      : dailyRet > 0
        ? "text-red-600"
        : dailyRet < 0
          ? "text-emerald-600"
          : "text-foreground"

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          Volatility Sentiment
        </CardTitle>
        <CardDescription>
          沪深300 20 日年化波动率 → 1 年分位 → 反向得分 (高分=平静)
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score == null ? "—" : score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">情绪得分</span>
            </div>

            {(vol != null || pct != null || dailyRet != null) && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
                {vol != null && (
                  <span>
                    vol
                    <span className="ml-1 text-foreground">{vol.toFixed(2)}%</span>
                  </span>
                )}
                {pct != null && (
                  <span>
                    pct
                    <span className="ml-1 text-foreground">{(pct * 100).toFixed(0)}%</span>
                  </span>
                )}
                {dailyRetText && (
                  <span>
                    当日
                    <span className={cn("ml-1", dailyRetTone)}>{dailyRetText}</span>
                  </span>
                )}
              </div>
            )}

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                color="inverse"
                formatter={(v) => v.toFixed(1)}
              />
              <div className="mt-1 text-[10px] text-muted-foreground">近 30 日情绪得分</div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card 8: Style Risk Appetite (风格风险偏好)
// ---------------------------------------------------------------------------
// 风格强弱 = 中证1000 近5日收益率 - 沪深300 近5日收益率
// spread > 0: 小盘更强 (风险偏好积极), spread < 0: 大盘更强 (避险)
// ---------------------------------------------------------------------------
function StyleRiskAppetiteCard({ date }: { date: string | null }) {
  const [data, setData] = useState<StyleRiskAppetiteResponse | null>(null)
  const [history, setHistory] = useState<StyleRiskAppetiteHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentStyleRiskAppetite(date ?? undefined),
          fetchMarketSentimentStyleRiskAppetiteHistory(start, end),
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
    return () => { cancelled = true }
  }, [date])

  const score = data?.score ?? null
  const rawValue = data?.rawValue ?? null
  const hs300Return = data?.hs300?.returnPct ?? null
  const csi1000Return = data?.csi1000?.returnPct ?? null

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 40
          ? "text-slate-700"
          : "text-emerald-600"
  const directionLabel =
    score == null ? ""
      : score >= 70 ? "小盘强 ↑"
      : score <= 30 ? "大盘强 ↓"
      : "中性"

  const sparkData = toSparkData(history, (it) => it.score ?? 50)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Scale className="size-4 text-muted-foreground" />
          风格风险偏好
        </CardTitle>
        <CardDescription>
          中证1000 5日收益 - 沪深300 5日收益 · 历史分位
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <>
            <div className="flex items-baseline gap-3">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className="text-xs text-muted-foreground">/ 100 · 历史分位</span>
              {directionLabel && (
                <span className={`text-xs font-medium ${tone}`}>{directionLabel}</span>
              )}
            </div>

            {rawValue != null && (
              <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                中证1000 - 沪深300: {rawValue >= 0 ? "+" : ""}{rawValue.toFixed(2)}%
                <span> · 高于过去3年{score.toFixed(0)}%的时间</span>
              </div>
            )}

            <div className="mt-2 space-y-0.5 text-xs text-muted-foreground tabular-nums">
              <div>
                沪深300: {hs300Return != null ? `${hs300Return >= 0 ? "+" : ""}${hs300Return.toFixed(2)}%` : "—"}
              </div>
              <div>
                中证1000: {csi1000Return != null ? `${csi1000Return >= 0 ? "+" : ""}${csi1000Return.toFixed(2)}%` : "—"}
              </div>
            </div>

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>

            <div className="mt-1 flex gap-3 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥70 小盘强</span>
              <span className="text-slate-400">40-70 中性</span>
              <span className="text-emerald-600/70">≤30 大盘强</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Card 9: Profit Effect (赚钱效应) — 市场情绪指数分项④
// ---------------------------------------------------------------------------
// score = 60% × 近5日上涨占比 + 40% × (100 - 60日新低占比)
// score ≥ 60 → 赚钱面宽, score ≥ 40 → 中性, < 40 → 亏钱效应
// ---------------------------------------------------------------------------
function ProfitEffectCard({ date }: { date: string | null }) {
  const [data, setData] = useState<ProfitEffectResponse | null>(null)
  const [history, setHistory] = useState<ProfitEffectHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentProfitEffect(date ?? undefined),
          fetchMarketSentimentProfitEffectHistory(start, end),
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
    return () => { cancelled = true }
  }, [date])

  const score = data?.score ?? null
  const up5dPct = data?.up5dPct ?? null
  const newLow60dPct = data?.newLow60dPct ?? null

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 60
        ? "text-red-600"
        : score >= 40
          ? "text-amber-600"
          : "text-emerald-600"

  const levelLabel =
    score == null ? ""
      : score >= 60 ? "赚钱面宽"
      : score >= 40 ? "中性"
      : "亏钱效应"

  const sparkData = toSparkData(history, (it) => it.score)

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-muted-foreground" />
          市场情绪指数分项④：赚钱效应
        </CardTitle>
        <CardDescription>
          60%×近5日上涨 + 40%×(100-60日新低)
          {data?.tradeDate ? ` · ${data.tradeDate}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <>
            <div className="flex items-baseline gap-3">
              <span className={`text-3xl font-semibold tabular-nums ${tone}`}>
                {score.toFixed(1)}
              </span>
              <span className={`text-xs font-medium ${tone}`}>{levelLabel}</span>
            </div>

            <div className="mt-2 space-y-0.5 text-xs text-muted-foreground tabular-nums">
              <div>近5日上涨占比: {up5dPct != null ? `${up5dPct.toFixed(1)}%` : "—"}</div>
              <div>60日新低占比: {newLow60dPct != null ? `${newLow60dPct.toFixed(1)}%` : "—"}</div>
            </div>

            <div className="mt-3">
              <Sparkline
                data={sparkData}
                height={40}
                color="auto"
                formatter={(v) => v.toFixed(1)}
              />
            </div>

            <div className="mt-1 flex gap-3 text-[10px] text-muted-foreground">
              <span className="text-red-600/70">≥60 赚钱面宽</span>
              <span className="text-amber-600/70">40-60 中性</span>
              <span className="text-emerald-600/70">＜40 亏钱效应</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Top Card: Market Sentiment Index (composite, 9 张卡加权合成)
// ---------------------------------------------------------------------------
const MSI_LEVEL_META: Record<string, { label: string; tone: string; chip: string }> = {
  hot:    { label: "火热",   tone: "text-red-600",    chip: "border-red-200 bg-red-50 text-red-700" },
  active: { label: "活跃",   tone: "text-orange-600", chip: "border-orange-200 bg-orange-50 text-orange-700" },
  normal: { label: "中性",   tone: "text-slate-700",  chip: "border-slate-200 bg-slate-50 text-slate-700" },
  weak:   { label: "弱势",   tone: "text-blue-600",   chip: "border-blue-200 bg-blue-50 text-blue-700" },
  ice:    { label: "冰点",   tone: "text-slate-400",  chip: "border-slate-300 bg-slate-100 text-slate-500" },
}

// 单项 component 得分配色 (数字 + 进度条统一调子, 不跟总分)
function scoreTone(v: number | null | undefined) {
  if (v == null) return "text-slate-300"
  if (v >= 70) return "text-red-600"
  if (v >= 60) return "text-orange-600"
  if (v >= 50) return "text-amber-600"
  if (v >= 40) return "text-sky-500"
  if (v >= 30) return "text-blue-600"
  return "text-slate-400"
}

function scoreBar(v: number | null | undefined) {
  if (v == null) return "bg-slate-200"
  if (v >= 70) return "bg-red-500/70"
  if (v >= 60) return "bg-orange-500/70"
  if (v >= 50) return "bg-amber-500/70"
  if (v >= 40) return "bg-sky-500/70"
  if (v >= 30) return "bg-blue-500/70"
  return "bg-slate-400/60"
}

const MSI_COMPONENT_META: Array<{
  key: keyof MarketSentimentIndexComponents
  label: string
  weight: number
}> = [
  { key: "vol",            label: "波动率情绪",   weight: 0.15 },
  { key: "turnover",       label: "成交活跃度",   weight: 0.15 },
  { key: "breadth",        label: "市场广度",     weight: 0.15 },
  { key: "limit_emotion",  label: "涨跌停情绪",   weight: 0.15 },
  { key: "price_strength", label: "价格强度",     weight: 0.10 },
  { key: "risk_appetite",  label: "风险偏好",     weight: 0.10 },
  { key: "profit_effect",  label: "赚钱效应",     weight: 0.10 },
  { key: "sector_breadth", label: "板块扩散",     weight: 0.05 },
  { key: "style_risk",     label: "风格风险",     weight: 0.05 },
]

function MarketSentimentIndexCard({ date }: { date: string | null }) {
  const [data, setData] = useState<MarketSentimentIndexResponse | null>(null)
  const [history, setHistory] = useState<MarketSentimentIndexHistoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  // 后端 3 年数据已就绪 (limit_emotion / vol_sentiment / profit_effect / msi 全部 728+ 行)
  const USE_MOCK = false

  useEffect(() => {
    if (USE_MOCK) return
    let cancelled = false
    const end = date ?? isoDateNDaysAgo(0)
    const start = shiftIsoDays(end, -1095)
    void (async () => {
      try {
        const [snap, hist] = await Promise.all([
          fetchMarketSentimentIndex(date ?? undefined),
          fetchMarketSentimentIndexHistory(start, end),
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
    return () => { cancelled = true }
  }, [date])

  // Mock data — 90 个交易日的合成情绪分, 含均值回归 + 多周期 + 大噪声 + 偶发冲击
  // 目标覆盖 10-90 全档位, 让 50 中性线/红蓝分区都看得出变化
  useEffect(() => {
    if (!USE_MOCK) return
    const mockHistory: MarketSentimentIndexHistoryItem[] = []
    const today = new Date()
    let score = 55 // 从中性开始
    for (let i = 90; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(d.getDate() - i)
      if (d.getDay() === 0 || d.getDay() === 6) continue // 跳过周末
      // 弱均值回归 (loose pull back)
      const drift = (50 - score) * 0.02
      // 多周期叠加 (长周期 + 短周期)
      const cycle = Math.sin(i * 0.09) * 14 + Math.sin(i * 0.21) * 6
      // 大噪声 (±7)
      const noise = (Math.random() - 0.5) * 14
      // 偶发极端冲击 (~6% 概率)
      const shock = Math.random() < 0.06 ? (Math.random() < 0.5 ? -15 : 18) : 0
      score = Math.max(8, Math.min(92, score + drift + cycle * 0.10 + noise + shock))
      const level =
        score >= 70 ? "hot" as const
        : score >= 55 ? "active" as const
        : score >= 45 ? "normal" as const
        : score >= 30 ? "weak" as const
        : "ice" as const
      mockHistory.push({
        tradeDate: d.toISOString().slice(0, 10),
        compositeScore: Math.round(score * 10) / 10,
        level,
      } as unknown as MarketSentimentIndexHistoryItem)
    }
    const last = mockHistory[mockHistory.length - 1]
    const mockData: MarketSentimentIndexResponse = {
      ok: true,
      tradeDate: last.tradeDate,
      compositeScore: last.compositeScore,
      level: last.level,
      componentCount: 9,
      components: {
        vol: 72,
        turnover: 48,
        price_strength: 35,
        risk_appetite: 62,
        breadth: 55,
        limit_emotion: last.compositeScore,
        profit_effect: 58,
        sector_breadth: 44,
        style_risk: 37,
      },
      weights: {
        vol: 0.15, turnover: 0.15, price_strength: 0.10,
        risk_appetite: 0.10, breadth: 0.15, limit_emotion: 0.15,
        profit_effect: 0.10, sector_breadth: 0.05, style_risk: 0.05,
      },
    } as unknown as MarketSentimentIndexResponse

    setData(mockData)
    setHistory(mockHistory)
    setLoading(false)
  }, [USE_MOCK])

  const score = data?.compositeScore ?? null
  const level = data?.level ?? "normal"
  const meta = MSI_LEVEL_META[level] ?? MSI_LEVEL_META.normal
  const components: MarketSentimentIndexComponents = data?.components ?? {
    vol: null, turnover: null, price_strength: null, risk_appetite: null,
    breadth: null, limit_emotion: null, profit_effect: null,
    sector_breadth: null, style_risk: null,
  }

  const tone =
    score == null
      ? "text-slate-700"
      : score >= 70
        ? "text-red-600"
        : score >= 55
          ? "text-orange-600"
          : score >= 45
            ? "text-slate-700"
            : score >= 30
              ? "text-blue-600"
              : "text-slate-400"

  // ECharts 折线: 完整 ISO 日期 + value, visualMap 按 value 自动上色
  const sentimentPoints = (history ?? [])
    .slice()
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))
    .map((it) => ({
      date: it.tradeDate.slice(5),
      value: it.compositeScore ?? 50,
      level: it.level,
    }))

  return (
    <Card className="border-0 shadow-none bg-muted/50">
      <CardContent>
        {loading ? (
          <div className="animate-pulse text-sm text-muted-foreground">加载中…</div>
        ) : score == null ? (
          <div className="py-3 text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="grid gap-4 md:grid-cols-[3fr_1fr]">
            {/* 左侧: 合成得分 + ECharts 趋势折线 (含视觉分区 + 阈值线) */}
            <div className="space-y-2">
              <div className="flex items-baseline gap-3">
                <span className={`text-5xl font-semibold tabular-nums ${tone}`}>
                  {score.toFixed(1)}
                </span>
                <span className="text-xs text-muted-foreground">/ 100</span>
                <span
                  className={cn(
                    "ml-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                    meta.chip
                  )}
                >
                  {meta.label}
                </span>
                {data?.tradeDate && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {data.tradeDate}
                  </span>
                )}
              </div>
              <SentimentLine data={sentimentPoints} height={440} />
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                <span className="text-red-600/70">≥70 极热</span>
                <span className="text-orange-600/70">60-70 偏热</span>
                <span className="text-amber-600/70">50-60 偏多</span>
                <span className="text-sky-500/80">40-50 偏弱</span>
                <span className="text-blue-600/70">30-40 低迷</span>
                <span className="text-slate-400">＜30 冰点</span>
              </div>
            </div>

            {/* 右侧: 9 个 component 明细 (等距竖排, 字号可读) */}
            <div className="flex flex-1 flex-col justify-around text-xs">
              {data && (
                <div className="text-[10px] text-muted-foreground mb-2">
                  实际参与合成的 component: {data.componentCount} / 9
                  {data.componentCount < 9 && " (部分子卡尚未落盘, 缺失按 50 中性)"}
                </div>
              )}
              {MSI_COMPONENT_META.map((c) => {
                const v = components[c.key]
                return (
                  <div key={c.key} className="flex items-center gap-1.5">
                    <span className="w-12 shrink-0 truncate text-muted-foreground">{c.label}</span>
                    <span className={`w-7 shrink-0 text-right font-semibold tabular-nums ${scoreTone(v)}`}>
                      {v == null ? "—" : v.toFixed(0)}
                    </span>
                    <div className="flex-1 h-1.5 rounded-full bg-muted/40 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${scoreBar(v)}`}
                        style={{ width: `${v == null ? 0 : Math.min(v, 100)}%` }}
                      />
                    </div>
                    <span className="w-6 shrink-0 text-right text-muted-foreground/80">{(c.weight * 100).toFixed(0)}%</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MarketSentimentPage() {
  // null = 后端默认行为 (上一交易日). 切换时 5 张卡 + history 一起重拉.
  const [date, setDate] = useState<string | null>(null)
  const reset = () => setDate(null)
  // "今天" 本地 00:00 (calendar disabled 用, 避免当前时间让今天也被禁)
  const now = new Date()
  const maxDate = new Date(now.getFullYear(), now.getMonth(), now.getDate())

  return (
    <WorkspaceShell sectionLabel="Market Sentiment" pageTitle="Mock Workspace">
      <div className="space-y-4">
        {/* Header: chip + 标题 + 简介 + 日期选择器 (右对齐) */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
              <Smile className="size-3.5" />
              Mock Workspace
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              Market Sentiment
            </h1>
          </div>
          <div className="flex flex-col items-start gap-1.5 sm:items-end">
            <div className="flex items-center gap-2">
              <Calendar className="size-3.5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">回看日期</span>
              <DatePicker
                value={date}
                onChange={(d) => setDate(d ? toLocalIso(d) : null)}
                maxDate={maxDate}
                placeholder="选择日期"
                clearable
                aria-label="选择历史日期"
              />
              {date && (
                <button
                  type="button"
                  onClick={reset}
                  className="ml-1 inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <RotateCcw className="size-3" />
                  重置
                </button>
              )}
            </div>
            <div className="text-[10px] text-muted-foreground">
              {date ? `已选: ${date}` : "未选 (默认上一交易日)"}
            </div>
          </div>
        </div>

        {/* Section 1: 实时情绪指标 — 顶部 1 张 composite 大卡 + 9 张子卡 (3 行) */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Activity className="size-3.5" />
            <span>实时情绪指标</span>
            <span className="text-border">·</span>
            <span className="text-[10px]">顶部 1 张合成指数 + 9 张子卡 / duckdb 持久化 / 工作日自动更新</span>
          </div>
          <MarketSentimentIndexCard date={date} />
          <div className="grid gap-4 md:grid-cols-3">
            <RiskAppetiteCard date={date} />
            <MarketBreadthCard date={date} />
            <NewHigh252dCard date={date} />
            <SectorBreadthCard date={date} />
            <TurnoverActivityCard date={date} />
            <LimitEmotionCard date={date} />
            <VolatilitySentimentCard date={date} />
            <StyleRiskAppetiteCard date={date} />
            <ProfitEffectCard date={date} />
          </div>
        </div>

        {/* Section 2: 规划中 — 4 张占位卡折叠成 1 行 chip */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Heart className="size-3.5" />
            <span>规划中</span>
            <span className="text-border">·</span>
            <span className="text-[10px]">4 张占位 / 待接入</span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {PLACEHOLDER_CHIPS.map((c) => (
              <div
                key={c.title}
                className="rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-2.5"
              >
                <div className="text-xs font-medium text-foreground">{c.title}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">{c.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Roadmap note */}
        <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-5 text-sm text-muted-foreground">
          <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
            <MessageSquareQuote className="size-4" />
            路线
          </div>
          后续接入 backend/services/stock/market_overview/sentiment.py,以及情绪相关调度任务,提供分钟级 / 日级的情绪分位曲线。
        </div>
      </div>
    </WorkspaceShell>
  )
}
