/**
 * 行业 / 概念 指数 技术指标面板.
 *
 * 数据源: backend ``industry_application_service._compute_indicators`` (本地计算, 不调 LLM).
 * 走 ``fetchIndustryApplicationKline`` 拿 ``payload.indicators``, 直接渲染.
 *
 * 显示 4 块:
 *   1) 实时数据 (最新收盘 + 涨跌幅 + 时间)
 *   2) 均线状态 (MA20/60/120/250 + 站上/跌破 + 距 MA 的 % + 连续天数)
 *   3) 20 日区间位置 (range_pos_20 进度条 0-1)
 *   4) 累计收益 (5d / 20d / 60d)
 *   5) K 线缩略统计 (bar_count + first/last close)
 *
 * 设计原则: 不复用 stock-chart 的 ``TechnicalIndicatorPanel``,
 * 那个面板的算法 (analyzeTrend / 形态分 / 风险分) 阈值是按个股股价区间 (5-100元)
 * + 个股成交量 + 市场宽度校准的, 套到行业指数 (2000-5000 价位) 一定会跑偏.
 */
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Calendar,
  CheckCircle2,
  Clock,
  Crosshair,
  TrendingDown,
  TrendingUp,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"

import type {
  IndustryApplicationIndexBar,
  IndustryApplicationIndicators,
} from "../lib/types"

// ---------------------------------------------------------------------------
// 格式化工具
// ---------------------------------------------------------------------------

function formatNum(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined) return "—"
  return value.toFixed(decimals)
}

function formatPct(value: number | null | undefined, decimals = 2, withSign = true): string {
  if (value === null || value === undefined) return "—"
  const sign = withSign && value > 0 ? "+" : ""
  return `${sign}${value.toFixed(decimals)}%`
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—"
  // 后端 eltdx 返回 YYYYMMDD / YYYY-MM-DD / ISO 都可能, 统一抽 yyyy-mm-dd
  const compact = value.replace(/[^0-9]/g, "")
  if (compact.length >= 8) {
    return `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}`
  }
  return value
}

function formatTimeShort(value: string | null | undefined): string {
  if (!value) return "—"
  const compact = value.replace(/[^0-9]/g, "")
  if (compact.length >= 8) {
    return `${compact.slice(4, 6)}/${compact.slice(6, 8)}`
  }
  return value
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

function MetricRow({
  label,
  value,
  tone = "default",
  hint,
}: {
  label: string
  value: string
  tone?: "default" | "up" | "down" | "muted"
  hint?: string
}) {
  const colorClass =
    tone === "up"
      ? "text-red-600"
      : tone === "down"
        ? "text-emerald-600"
        : tone === "muted"
          ? "text-slate-400"
          : "text-slate-700"
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
      <div className="flex flex-col">
        <span className="text-slate-500">{label}</span>
        {hint ? <span className="text-[10px] text-slate-400">{hint}</span> : null}
      </div>
      <span className={`font-semibold tabular-nums ${colorClass}`}>{value}</span>
    </div>
  )
}

function MaRow({
  label,
  value,
  above,
  pct,
}: {
  label: string
  value: number | null | undefined
  above: boolean | null | undefined
  pct: number | null | undefined
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
      <div className="flex w-16 shrink-0 items-center gap-1.5 text-slate-600">
        <span className="font-mono text-[10px] text-slate-500">{label}</span>
      </div>
      <div className="flex-1">
        <div className="font-semibold tabular-nums text-slate-800">
          {value === null || value === undefined ? "—" : value.toFixed(2)}
        </div>
      </div>
      {above === true ? (
        <Badge className="border-red-200 bg-red-50 text-red-700" variant="outline">
          <ArrowUpRight className="mr-0.5 size-3" />
          站上 {pct !== null && pct !== undefined ? `(${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)` : ""}
        </Badge>
      ) : above === false ? (
        <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700" variant="outline">
          <ArrowDownRight className="mr-0.5 size-3" />
          跌破 {pct !== null && pct !== undefined ? `(${pct.toFixed(2)}%)` : ""}
        </Badge>
      ) : (
        <Badge className="border-slate-200 bg-slate-50 text-slate-500" variant="outline">
          <span className="mr-0.5 text-slate-400">·</span>
          数据不足
        </Badge>
      )}
    </div>
  )
}

function RangePositionBar({
  rangePos,
  high,
  low,
  current,
}: {
  rangePos: number | null | undefined
  high: number | null | undefined
  low: number | null | undefined
  current: number | null | undefined
}) {
  const pct = rangePos === null || rangePos === undefined ? null : Math.max(0, Math.min(1, rangePos)) * 100
  const tone =
    rangePos === null || rangePos === undefined
      ? "muted"
      : rangePos >= 0.8
        ? "down"
        : rangePos <= 0.2
          ? "up"
          : "default"
  const label =
    rangePos === null || rangePos === undefined
      ? "—"
      : rangePos >= 0.8
        ? "高位 (警惕回踩)"
        : rangePos <= 0.2
          ? "低位 (关注支撑)"
          : "中位 (区间震荡)"

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-500">20 日区间位置</span>
        <span
          className={`font-semibold tabular-nums ${
            tone === "down" ? "text-emerald-600" : tone === "up" ? "text-red-600" : "text-slate-700"
          }`}
        >
          {pct === null ? "—" : pct.toFixed(0) + "%"} · {label}
        </span>
      </div>
      <Progress
        value={pct ?? 0}
        className={`h-2 ${
          tone === "down" ? "[&>div]:bg-emerald-500" : tone === "up" ? "[&>div]:bg-red-500" : ""
        }`}
      />
      <div className="flex items-center justify-between text-[10px] text-slate-400">
        <span>
          低 {low === null || low === undefined ? "—" : low.toFixed(2)}
        </span>
        <span>
          收 {current === null || current === undefined ? "—" : current.toFixed(2)}
        </span>
        <span>
          高 {high === null || high === undefined ? "—" : high.toFixed(2)}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export interface IndustryTechnicalIndicatorPanelProps {
  name: string
  code: string
  indicators: IndustryApplicationIndicators | null
  bars: IndustryApplicationIndexBar[]
}

export function IndustryTechnicalIndicatorPanel({
  name,
  code,
  indicators,
  bars,
}: IndustryTechnicalIndicatorPanelProps) {
  if (!indicators) {
    return (
      <Card className="rounded-none border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl">
        <CardContent className="p-6 text-center text-sm text-slate-400">
          暂无技术指标数据, 请先点击「立即刷新」拉取 K 线。
        </CardContent>
      </Card>
    )
  }
  const ind = indicators
  const lastPctUp = (ind.latest_pct ?? 0) > 0
  const lastPctDown = (ind.latest_pct ?? 0) < 0
  const streak = ind.above_ma20_streak ?? 0

  return (
    <div className="grid gap-0 sm:gap-3 lg:grid-cols-2">
      {/* ========== 1) 实时数据 ========== */}
      <Card className="rounded-none border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="size-4 text-slate-600" />
                {name}
              </CardTitle>
              <CardDescription className="font-mono text-[11px]">{code}</CardDescription>
            </div>
            <Badge
              className={
                lastPctUp
                  ? "border-red-200 bg-red-50 text-red-700"
                  : lastPctDown
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-slate-50 text-slate-600"
              }
              variant="outline"
            >
              {lastPctUp ? (
                <TrendingUp className="mr-0.5 size-3" />
              ) : lastPctDown ? (
                <TrendingDown className="mr-0.5 size-3" />
              ) : null}
              {formatPct(ind.latest_pct)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-baseline gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex-1">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">最新收盘</div>
              <div
                className={`mt-0.5 font-mono text-2xl font-bold tabular-nums ${
                  lastPctUp ? "text-red-600" : lastPctDown ? "text-emerald-600" : "text-slate-800"
                }`}
              >
                {formatNum(ind.latest_close)}
              </div>
            </div>
            <div className="text-right text-[10px] text-slate-500">
              <div className="flex items-center gap-1">
                <Calendar className="size-3" /> {formatTime(ind.latest_time)}
              </div>
              <div className="mt-1 flex items-center justify-end gap-1">
                <BarChart3 className="size-3" /> {ind.bar_count ?? 0} 根 K 线
              </div>
            </div>
          </div>
          {streak > 0 ? (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50/60 px-3 py-1.5 text-xs text-red-700">
              <CheckCircle2 className="size-3.5" />
              已连续 <span className="font-semibold tabular-nums">{streak}</span> 个交易日站上 MA20
            </div>
          ) : streak < 0 ? (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-1.5 text-xs text-emerald-700">
              <TrendingDown className="size-3.5" />
              已连续 <span className="font-semibold tabular-nums">{Math.abs(streak)}</span> 个交易日跌破 MA20
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ========== 2) 累计收益 ========== */}
      <Card className="rounded-none border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="size-4 text-slate-600" />
            累计收益
          </CardTitle>
          <CardDescription>基于日线收盘计算</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-3 gap-2">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-center">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">5 日</div>
            <div
              className={`mt-1 font-mono text-lg font-bold tabular-nums ${
                (ind.return_5d ?? 0) > 0
                  ? "text-red-600"
                  : (ind.return_5d ?? 0) < 0
                    ? "text-emerald-600"
                    : "text-slate-500"
              }`}
            >
              {formatPct(ind.return_5d)}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-center">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">20 日</div>
            <div
              className={`mt-1 font-mono text-lg font-bold tabular-nums ${
                (ind.return_20d ?? 0) > 0
                  ? "text-red-600"
                  : (ind.return_20d ?? 0) < 0
                    ? "text-emerald-600"
                    : "text-slate-500"
              }`}
            >
              {formatPct(ind.return_20d)}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-center">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">60 日</div>
            <div
              className={`mt-1 font-mono text-lg font-bold tabular-nums ${
                (ind.return_60d ?? 0) > 0
                  ? "text-red-600"
                  : (ind.return_60d ?? 0) < 0
                    ? "text-emerald-600"
                    : "text-slate-500"
              }`}
            >
              {formatPct(ind.return_60d)}
            </div>
          </div>
          <div className="col-span-3 rounded-lg bg-slate-50/50 px-2 py-1.5 text-[10px] text-slate-500">
            注: 行业 / 概念指数以 0 为参考, 红涨绿跌; 长期收益参考 20/60 日, 短期波动看 5 日.
          </div>
        </CardContent>
      </Card>

      {/* ========== 3) 均线状态 ========== */}
      <Card className="rounded-none border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="size-4 text-slate-600" />
            均线状态
          </CardTitle>
          <CardDescription>MA20 / 60 / 120 / 250 站上跌破 + 偏离度</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <MaRow label="MA20" value={ind.ma20} above={ind.above_ma20} pct={ind.above_ma20_pct} />
          <MaRow label="MA60" value={ind.ma60} above={ind.above_ma60} pct={ind.above_ma60_pct} />
          <MaRow label="MA120" value={ind.ma120} above={null} pct={null} />
          <MaRow label="MA250" value={ind.ma250} above={null} pct={null} />
        </CardContent>
      </Card>

      {/* ========== 4) 20 日区间位置 ========== */}
      <Card className="rounded-none border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Crosshair className="size-4 text-slate-600" />
            20 日区间位置
          </CardTitle>
          <CardDescription>当前价在 20 日 high-low 区间里的位置 (0-100%)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <RangePositionBar
            rangePos={ind.range_pos_20}
            high={ind.high_20}
            low={ind.low_20}
            current={ind.latest_close}
          />
          <Separator className="my-1" />
          <div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500">
            <div>
              <div className="uppercase tracking-wider text-slate-400">K 线</div>
              <div className="mt-0.5 font-mono tabular-nums text-slate-700">
                {bars.length} 根
              </div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-slate-400">首根</div>
              <div className="mt-0.5 font-mono tabular-nums text-slate-700">
                {bars[0] ? formatTimeShort(bars[0].time) : "—"}
              </div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-slate-400">末根</div>
              <div className="mt-0.5 font-mono tabular-nums text-slate-700">
                {bars[bars.length - 1] ? formatTimeShort(bars[bars.length - 1].time) : "—"}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ========== 5) 综合说明 ========== */}
      <Card className="rounded-none border-slate-200 bg-slate-50 shadow-[0_16px_46px_rgba(15,23,42,0.06)] sm:rounded-3xl lg:col-span-2">
        <CardContent className="p-4 text-xs leading-relaxed text-slate-600">
          <div className="mb-1 font-semibold text-slate-700">说明</div>
          <ul className="ml-4 list-disc space-y-0.5">
            <li>
              <span className="font-mono text-[11px] text-slate-500">MA20/60/120/250</span>{" "}
              是基于日线收盘的简单移动平均, 站上 = 短线趋势偏多, 跌破 = 偏空.
            </li>
            <li>
              <span className="font-mono text-[11px] text-slate-500">区间位置</span>{" "}
              越接近 100% 越接近 20 日高点 (警惕回踩), 越接近 0% 越接近 20 日低点 (关注支撑).
            </li>
            <li>
              <span className="font-mono text-[11px] text-slate-500">累计收益</span>{" "}
              5 日反映短线情绪, 20 日反映中期, 60 日反映中期趋势.
            </li>
            <li>
              行业 / 概念 指数不显示个股形态分 / 风险分 (那些阈值对行业指数不适用).
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

// 显式 re-export 给上层 import 引用 (避免 tree-shake 警告)
export { MetricRow }
