import { useState } from "react"
import { ChevronDown, ChevronRight, Compass, MapPin, RefreshCw, Sparkles, Target } from "lucide-react"

import type { ApplicationAnalysisRecent30FullItem } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

import { CollapsibleCard } from "@/components/collapsible-card"
import { BIAS_TONE } from "../lib/constants"
import { fmt, fmtPercent, safeRecord, safeString, textList, toNumber } from "../lib/format"

function biasTone(bias: unknown) {
  const key = typeof bias === "string" ? bias.toLowerCase() : ""
  return BIAS_TONE[key] || BIAS_TONE.unclear
}

function DirectionDetails({
  trend,
  situation,
}: {
  trend: Record<string, unknown>
  situation: Record<string, unknown>
}) {
  const stateLabel = fmt(trend.state)
  const bias = biasTone(trend.bias)
  const horizon = fmt(trend.horizon)
  const score = fmt(trend.score)
  const confidence = fmt(trend.confidence)
  const momentum = safeRecord(trend.momentum)
  const maPosition = safeRecord(trend.ma_position)
  const pricePosition = safeRecord(trend.price_position)
  const scenario = safeRecord(trend.scenario_analysis)
  const evidence = textList(trend.key_evidence)
  const invalidList = textList(trend.invalid_conditions)

  const position = fmt(situation.position)
  const spaceStructure = fmt(situation.space_structure)
  const positionScore = fmt(situation.position_score)
  const situationConfidence = fmt(situation.confidence)
  const statusTags = textList(situation.status_tags)
  const situationEvidence = textList(situation.key_evidence)
  const situationNote = safeString(situation.note)

  return (
    <div className="min-w-0 space-y-2 border-t border-slate-100 px-3 py-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
            <Sparkles className="size-3" />短期趋势
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <div className="min-w-0 break-words text-sm font-semibold text-slate-900 sm:truncate">{stateLabel || "—"}</div>
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
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <div className="min-w-0 break-words text-sm font-semibold text-slate-900 sm:truncate">{position || "—"}</div>
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

      {(statusTags.length || situationNote) ? (
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
          {situationNote ? <div className="mt-2 break-words text-[11px] leading-5 text-slate-600">{situationNote}</div> : null}
        </div>
      ) : null}

      <div className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-slate-500">
          <Sparkles className="size-3" />动量 / 均线
        </div>
        <div className="mt-1.5 grid grid-cols-1 gap-x-3 gap-y-1 text-[11px] text-slate-600 sm:grid-cols-3">
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
            <span className="text-slate-700">{fmt(maPosition.structure) || "—"}</span>
          </div>
          <div>
            <span className="text-slate-400">价格位置</span>{" "}
            <span className="text-slate-700">{fmt(pricePosition.label) || "—"}</span>
          </div>
        </div>
      </div>

      {Object.keys(scenario).length ? (
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
                <div key={key} className={`rounded-2xl border p-2 ${tone}`}>
                  <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">
                    {key === "upside" ? "乐观" : key === "downside" ? "悲观" : "基准"}
                  </div>
                  <div className="mt-1 space-y-1 text-[11px] text-slate-700">
                    {fmt(block.trigger) ? <div className="break-words">触发：{fmt(block.trigger)}</div> : null}
                    {fmt(block.target) ? <div className="break-words">目标：{fmt(block.target)}</div> : null}
                    {fmt(block.range) ? <div className="break-words">区间：{fmt(block.range)}</div> : null}
                  </div>
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
              <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">趋势关键证据</div>
              <ul className="mt-1 list-disc pl-4 text-[11px] leading-5 text-slate-600">
                {evidence.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {situationEvidence.length ? (
            <div className="mt-2">
              <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500">位置关键证据</div>
              <ul className="mt-1 list-disc pl-4 text-[11px] leading-5 text-slate-600">
                {situationEvidence.map((line) => (
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
        </div>
      ) : null}
    </div>
  )
}

function DateItem({
  item,
  defaultExpanded,
}: {
  item: ApplicationAnalysisRecent30FullItem
  defaultExpanded: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const trend = safeRecord(item.snapshot?.short_term_trend)
  const situation = safeRecord(item.snapshot?.current_situation)
  const hasData = Object.keys(trend).length > 0 || Object.keys(situation).length > 0
  const stateLabel = fmt(trend.state)
  const bias = biasTone(trend.bias)
  const position = fmt(situation.position)
  const phase = fmt(situation.phase)
  const updatedAtText = item.updated_at
    ? new Date(item.updated_at).toLocaleString("zh-CN", { hour12: false })
    : ""

  return (
    <div className="min-w-0 rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_4px_16px_rgba(15,23,42,0.04)]">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-col gap-2 px-3 py-3 text-left transition hover:bg-slate-50/40 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
      >
        <div className="flex min-w-0 items-start gap-2.5 sm:items-center">
          {expanded ? <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-slate-500 sm:mt-0" /> : <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-slate-500 sm:mt-0" />}
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <span className="font-mono">{item.date}</span>
              {defaultExpanded ? (
                <Badge className="rounded-full border-slate-900 bg-slate-900 px-1.5 py-0 text-[10px] text-white" variant="outline">最新</Badge>
              ) : null}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
              {hasData ? (
                <>
                  <span>{stateLabel || "—"}</span>
                  <Badge className={`rounded-full border px-1.5 py-0 text-[10px] ${bias.cls}`} variant="outline">{bias.label}</Badge>
                  <span className="text-slate-300">·</span>
                  <span>{position || "—"}</span>
                  {phase ? (
                    <>
                      <span className="text-slate-300">·</span>
                      <span>{phase}</span>
                    </>
                  ) : null}
                </>
              ) : (
                <span className="text-slate-400">该日期暂无 AI 整体判断数据</span>
              )}
            </div>
          </div>
        </div>
        <div className="shrink-0 text-left text-[10px] text-slate-400 sm:text-right">
          {updatedAtText ? <>更新 {updatedAtText}</> : null}
        </div>
      </button>
      {expanded ? <DirectionDetails trend={trend} situation={situation} /> : null}
    </div>
  )
}

export function AIDirectionCard({
  collapsed,
  onToggle,
  dailySnapshotsFull,
  dailySnapshotsLoading,
  dailyRefreshing,
  dailyLastRefreshAt,
  onRefreshDaily,
}: {
  collapsed: boolean
  onToggle: () => void
  dailySnapshotsFull: ApplicationAnalysisRecent30FullItem[]
  dailySnapshotsLoading: boolean
  dailyRefreshing: boolean
  dailyLastRefreshAt: string | null
  onRefreshDaily: () => void
}) {
  const lastRefreshText = dailyLastRefreshAt
    ? new Date(dailyLastRefreshAt).toLocaleString("zh-CN", { hour12: false })
    : "尚未手动触发"

  const latestDate = dailySnapshotsFull[0]?.date

  return (
    <CollapsibleCard
      title="AI Direction"
      description={`按日持久化 · 倒序展示 · 共 ${dailySnapshotsFull.length} 条`}
      icon={Compass}
      collapsed={collapsed}
      onToggle={onToggle}
    >
      <div className="space-y-3">
        <div className="flex flex-col gap-2 rounded-2xl border border-slate-200/80 bg-slate-50/60 px-3 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div className="min-w-0 break-words text-[11px] text-slate-500">
            AI 整体判断按日写入 <span className="font-mono">reference/application-analysis/snapshots/</span>，服务默认从此处读取
          </div>
          <div className="grid grid-cols-1 gap-2 sm:flex sm:items-center">
            <span className="text-[10px] text-slate-400">上次刷新 {lastRefreshText}</span>
            <Button
              size="sm"
              variant="default"
              className="h-8 w-full rounded-lg bg-slate-950 px-2.5 text-[11px] text-white hover:bg-slate-800 sm:h-7 sm:w-auto"
              onClick={onRefreshDaily}
              disabled={dailyRefreshing}
            >
              <RefreshCw className={`mr-1 size-3 ${dailyRefreshing ? "animate-spin" : ""}`} />
              {dailyRefreshing ? "生成中" : "重新生成当日判断"}
            </Button>
          </div>
        </div>

        {dailySnapshotsFull.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-[11px] text-slate-500">
            {dailySnapshotsLoading ? "加载中..." : "还没有 AI 整体判断数据。点击上方「重新生成当日判断」触发一次，或等待每天 16:00 的定时任务。"}
          </div>
        ) : (
          <div className="space-y-2">
            {dailySnapshotsFull.map((item) => (
              <DateItem
                key={item.date}
                item={item}
                defaultExpanded={item.date === latestDate}
              />
            ))}
          </div>
        )}
      </div>
    </CollapsibleCard>
  )
}
