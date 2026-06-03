import { Compass, LineChart, MapPin, RefreshCw, Sparkles, Target } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { ApplicationAnalysisDailySnapshotFile } from "@/lib/api"

import { CollapsibleCard } from "./collapsible-card"
import { BIAS_TONE } from "../lib/constants"
import { fmt, fmtPercent, safeRecord, safeString, textList, toNumber } from "../lib/format"
import type { ApplicationAnalysisDailySnapshot } from "../lib/types"

function biasTone(bias: unknown) {
  const key = typeof bias === "string" ? bias.toLowerCase() : ""
  return BIAS_TONE[key] || BIAS_TONE.unclear
}

export function AIDirectionCard({
  shortTermTrend,
  currentSituation,
  collapsed,
  onToggle,
  dailySnapshots,
  dailySnapshotsLoading,
  dailyRefreshing,
  dailyLastRefreshAt,
  onRefreshDaily,
  dailySelectedDate,
  onSelectDailyDate,
  dailySelectedSnapshot,
}: {
  shortTermTrend: Record<string, unknown>
  currentSituation: Record<string, unknown>
  collapsed: boolean
  onToggle: () => void
  dailySnapshots: ApplicationAnalysisDailySnapshotFile[]
  dailySnapshotsLoading: boolean
  dailyRefreshing: boolean
  dailyLastRefreshAt: string | null
  onRefreshDaily: () => void
  dailySelectedDate: string | null
  onSelectDailyDate: (date: string) => void
  dailySelectedSnapshot: ApplicationAnalysisDailySnapshot | null
}) {
  const trend = safeRecord(shortTermTrend)
  const situation = safeRecord(currentSituation)

  // 历史快照：仅当所选日期已读到带数据的对象时，才切换为历史视图
  const historicalTrendRecord =
    dailySelectedSnapshot && dailySelectedSnapshot.short_term_trend
      ? safeRecord(dailySelectedSnapshot.short_term_trend)
      : null
  const historicalSituationRecord =
    dailySelectedSnapshot && dailySelectedSnapshot.current_situation
      ? safeRecord(dailySelectedSnapshot.current_situation)
      : null
  const useHistorical = Boolean(dailySelectedDate && (historicalTrendRecord || historicalSituationRecord))
  const activeTrend = useHistorical && historicalTrendRecord ? historicalTrendRecord : trend
  const activeSituation = useHistorical && historicalSituationRecord ? historicalSituationRecord : situation
  const hasActiveTrend = Object.keys(activeTrend).length > 0
  const hasActiveSituation = Object.keys(activeSituation).length > 0

  const stateLabel = fmt(activeTrend.state)
  const bias = biasTone(activeTrend.bias)
  const horizon = fmt(activeTrend.horizon)
  const score = fmt(activeTrend.score)
  const confidence = fmt(activeTrend.confidence)
  const momentum = safeRecord(activeTrend.momentum)
  const maPosition = safeRecord(activeTrend.ma_position)
  const pricePosition = safeRecord(activeTrend.price_position)
  const scenario = safeRecord(activeTrend.scenario_analysis)
  const evidence = textList(activeTrend.key_evidence)
  const invalidList = textList(activeTrend.invalid_conditions)

  const position = fmt(activeSituation.position)
  const spaceStructure = fmt(activeSituation.space_structure)
  const positionScore = fmt(activeSituation.position_score)
  const situationConfidence = fmt(activeSituation.confidence)
  const statusTags = textList(activeSituation.status_tags)
  const situationEvidence = textList(activeSituation.key_evidence)
  const situationNote = safeString(activeSituation.note)

  const lastRefreshText = dailyLastRefreshAt
    ? new Date(dailyLastRefreshAt).toLocaleString("zh-CN", { hour12: false })
    : "尚未手动触发"

  return (
    <CollapsibleCard
      title="AI 整体判断"
      description="短期趋势与当前位置的结构化结论，按日持久化、倒序展示"
      icon={Compass}
      badge={dailySelectedDate || stateLabel || position}
      collapsed={collapsed}
      onToggle={onToggle}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200/80 bg-slate-50/60 px-3 py-2">
          <div className="text-[11px] text-slate-500">
            入口：最近 30 根日 K · 每天 16:00 定时刷新 · 持久化到 <span className="font-mono">reference/application-analysis/snapshots/</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-400">上次刷新 {lastRefreshText}</span>
            <Button
              size="sm"
              variant="default"
              className="h-7 rounded-lg bg-slate-950 px-2.5 text-[11px] text-white hover:bg-slate-800"
              onClick={onRefreshDaily}
              disabled={dailyRefreshing}
            >
              <RefreshCw className={`mr-1 size-3 ${dailyRefreshing ? "animate-spin" : ""}`} />
              {dailyRefreshing ? "生成中" : "重新生成当日判断"}
            </Button>
          </div>
        </div>

        {dailySnapshots.length ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <span>按日历史 · 倒序</span>
              <span className="text-slate-400">{dailySnapshotsLoading ? "加载中" : `${dailySnapshots.length} 条`}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {dailySnapshots.map((item) => {
                const isActive = item.date === dailySelectedDate
                return (
                  <button
                    type="button"
                    key={`${item.path}-${item.date}`}
                    onClick={() => onSelectDailyDate(item.date)}
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"
                    }`}
                  >
                    {item.date}
                  </button>
                )
              })}
            </div>
          </div>
        ) : null}

        {hasActiveTrend || hasActiveSituation ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
                <Sparkles className="size-3" />短期趋势
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="truncate text-sm font-semibold text-slate-900">{stateLabel || "—"}</div>
                <Badge className={`rounded-full border px-2 py-0 text-[10px] font-medium ${bias.cls}`} variant="outline">
                  {bias.label}
                </Badge>
              </div>
              <div className="mt-1.5 grid grid-cols-3 gap-1 text-[11px] text-slate-500">
                <div>
                  <div className="text-slate-400">周期</div>
                  <div className="font-mono text-slate-700">{horizon || "—"}</div>
                </div>
                <div>
                  <div className="text-slate-400">分</div>
                  <div className="font-mono text-slate-700">{score}</div>
                </div>
                <div>
                  <div className="text-slate-400">置信</div>
                  <div className="font-mono text-slate-700">{confidence}</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
                <MapPin className="size-3" />当前所处情况
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="truncate text-sm font-semibold text-slate-900">{position || "—"}</div>
                <Badge className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0 text-[10px] text-slate-600" variant="outline">
                  {spaceStructure || "—"}
                </Badge>
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-1 text-[11px] text-slate-500">
                <div>
                  <div className="text-slate-400">位置分</div>
                  <div className="font-mono text-slate-700">{positionScore}</div>
                </div>
                <div>
                  <div className="text-slate-400">置信</div>
                  <div className="font-mono text-slate-700">{situationConfidence}</div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-[11px] text-slate-500">
            还没有 AI 整体判断数据，点击上方 “重新生成当日判断” 按钮触发一次，或等待每天 16:00 的定时任务。
          </div>
        )}

        {hasActiveSituation && (statusTags.length || situationNote) ? (
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-3">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <Target className="size-3" />状态标签与备注
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {statusTags.length ? (
                statusTags.map((tag) => (
                  <Badge key={tag} className="rounded-full border-slate-200 bg-white px-2 py-0 text-[10px] text-slate-700" variant="outline">
                    {tag}
                  </Badge>
                ))
              ) : (
                <span className="text-[11px] text-slate-400">无标签</span>
              )}
            </div>
            {situationNote ? <div className="mt-2 text-[11px] leading-5 text-slate-600">{situationNote}</div> : null}
          </div>
        ) : null}

        {hasActiveTrend ? (
          <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <LineChart className="size-3" />动量 / 均线 / 位置
            </div>
            <div className="mt-1.5 grid gap-1 text-[11px] leading-5 text-slate-600 sm:grid-cols-2">
              <div>
                <span className="text-slate-400">3 日 / 5 日 / 10 日</span>{" "}
                <span className="font-mono text-slate-700">
                  {fmtPercent(toNumber(momentum.return_3d) ?? NaN)} · {fmtPercent(toNumber(momentum.return_5d) ?? NaN)} · {fmtPercent(toNumber(momentum.return_10d) ?? NaN)}
                </span>
              </div>
              <div>
                <span className="text-slate-400">5 日涨跌</span>{" "}
                <span className="font-mono text-slate-700">
                  {fmt(momentum.up_days_5d)} 阳 / {fmt(momentum.down_days_5d)} 阴
                </span>
              </div>
              <div>
                <span className="text-slate-400">距 20 日高 / 低</span>{" "}
                <span className="font-mono text-slate-700">
                  {fmtPercent(toNumber(momentum.near_20d_high_pct) ?? NaN)} · {fmtPercent(toNumber(momentum.near_20d_low_pct) ?? NaN)}
                </span>
              </div>
              <div>
                <span className="text-slate-400">短均线结构</span>{" "}
                <span className="text-slate-700">{fmt(maPosition.short_ma_structure)}</span>
              </div>
              <div>
                <span className="text-slate-400">价格位置</span>{" "}
                <span className="text-slate-700">{fmt(pricePosition.position_vs_range_20d)}</span>
              </div>
              <div>
                <span className="text-slate-400">量价 / 换手</span>{" "}
                <span className="text-slate-700">{fmt(activeTrend.volume_price_state)} · {fmt(activeTrend.turnover_state)}</span>
              </div>
            </div>
          </div>
        ) : null}

        {hasActiveTrend && Object.keys(scenario).length ? (
          <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              <Compass className="size-3" />情景分析
            </div>
            <div className="mt-1.5 grid gap-2 sm:grid-cols-3">
              {(["upside", "base", "downside"] as const).map((key) => {
                const block = safeRecord(scenario[key])
                if (!Object.keys(block).length) return null
                const tone =
                  key === "upside" ? "border-rose-200 bg-rose-50/60" : key === "downside" ? "border-emerald-200 bg-emerald-50/60" : "border-slate-200 bg-slate-50/60"
                return (
                  <div key={key} className={`rounded-xl border p-2.5 ${tone}`}>
                    <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.08em] text-slate-500">
                      <span>{key === "upside" ? "偏强情景" : key === "downside" ? "偏弱情景" : "中性情景"}</span>
                      <span className="font-mono text-slate-600">置信 {fmt(block.confidence)}</span>
                    </div>
                    {safeString(block.condition) ? (
                      <div className="mt-1 text-[11px] leading-5 text-slate-700">{safeString(block.condition)}</div>
                    ) : null}
                    {safeString(block.observation) ? (
                      <div className="mt-1 text-[11px] leading-5 text-slate-500">观察：{safeString(block.observation)}</div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}

        {evidence.length || invalidList.length || situationEvidence.length ? (
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-3">
            {evidence.length ? (
              <div>
                <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">关键证据</div>
                <ul className="mt-1 list-disc pl-4 text-[11px] leading-5 text-slate-600">
                  {evidence.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {invalidList.length ? (
              <div className="mt-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">失效条件</div>
                <ul className="mt-1 list-disc pl-4 text-[11px] leading-5 text-slate-600">
                  {invalidList.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {situationEvidence.length ? (
              <div className="mt-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">当前情况证据</div>
                <ul className="mt-1 list-disc pl-4 text-[11px] leading-5 text-slate-600">
                  {situationEvidence.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </CollapsibleCard>
  )
}
