import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Play, RefreshCw, ShieldAlert, Sparkles, Target } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  fetchAuctionAiAnalysisSnapshot,
  fetchStockAuction,
  runAuctionAiAnalysis,
  triggerAuctionAiAnalysisScheduler,
  type AuctionAiAnalysisResponse,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { AuctionPanel } from "../../stock-chart/components/auction-panel"
import type {
  StockAdjust,
  StockAuctionSnapshot,
  StockTargetType,
} from "../../stock-chart/lib/types"
import { fmt, safeRecord, safeString, textList, toNumber } from "../lib/format"
import { notification } from "@/components/ui/notification"

export interface AuctionTabProps {
  targetType: StockTargetType
  symbol: string
  name: string
  adjust?: StockAdjust
}

const SCORE_TONE = {
  strong: "border-red-200 bg-red-50 text-red-700",
  mild: "border-amber-200 bg-amber-50 text-amber-700",
  neutral: "border-slate-200 bg-slate-50 text-slate-700",
  weak: "border-emerald-200 bg-emerald-50 text-emerald-700",
}

function scoreTone(value: unknown) {
  const number = toNumber(value)
  if (number === null) return SCORE_TONE.neutral
  if (number >= 75) return SCORE_TONE.strong
  if (number >= 55) return SCORE_TONE.mild
  if (number <= 35) return SCORE_TONE.weak
  return SCORE_TONE.neutral
}

function biasTone(value: unknown) {
  const key = String(value || "").toLowerCase()
  if (key.includes("bullish")) return "border-red-200 bg-red-50 text-red-700"
  if (key.includes("bearish")) return "border-emerald-200 bg-emerald-50 text-emerald-700"
  return "border-slate-200 bg-slate-50 text-slate-700"
}

function riskTone(value: unknown) {
  const key = String(value || "").toLowerCase()
  if (key.includes("extreme") || key.includes("high")) return "border-red-200 bg-red-50 text-red-700"
  if (key.includes("medium")) return "border-amber-200 bg-amber-50 text-amber-700"
  if (key.includes("low")) return "border-emerald-200 bg-emerald-50 text-emerald-700"
  return "border-slate-200 bg-slate-50 text-slate-700"
}

function MetricPill({ label, value, tone }: { label: string; value: unknown; tone?: string }) {
  return (
    <div className={cn("min-w-0 rounded-xl border px-3 py-2", tone || "border-slate-200 bg-white")}>
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="mt-0.5 break-words text-sm font-semibold sm:truncate">{fmt(value)}</div>
    </div>
  )
}

function SectionList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
      <div className="text-[11px] font-medium text-slate-500">{title}</div>
      <div className="mt-2 grid gap-1.5 text-xs leading-5 text-slate-700">
        {items.slice(0, 8).map((item, index) => (
          <div key={`${title}-${index}`} className="break-words rounded-lg bg-white px-2 py-1 shadow-[0_1px_3px_rgba(15,23,42,0.04)]">
            {item}
          </div>
        ))}
      </div>
    </div>
  )
}

function StyleViewCard({
  title,
  icon,
  data,
  risk,
}: {
  title: string
  icon: ReactNode
  data: Record<string, unknown>
  risk?: boolean
}) {
  const state = fmt(data.state || data.risk_level)
  const score = data.score ?? data.risk_level_score
  const confidence = data.confidence
  const observation = safeString(data.observation) || safeString(data.watch_5min)
  const mainRisks = textList(data.main_risks)
  return (
    <div className="min-w-0 rounded-2xl border border-slate-200 bg-white p-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
          {icon}
          {title}
        </div>
        <Badge variant="outline" className={cn("rounded-full px-2 py-0 text-[10px]", risk ? riskTone(data.risk_level) : scoreTone(score))}>
          {fmt(score)}
        </Badge>
      </div>
      <div className="mt-2 break-words text-sm font-semibold text-slate-900">{state}</div>
      <div className="mt-1 text-[11px] text-slate-500">置信 {fmt(confidence)}</div>
      {observation ? <div className="mt-2 break-words text-xs leading-5 text-slate-600">{observation}</div> : null}
      {mainRisks.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {mainRisks.slice(0, 4).map((item) => (
            <Badge key={item} variant="outline" className="border-red-200 bg-red-50 px-2 py-0 text-[10px] text-red-700">
              {item}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function AuctionAiPanel({
  response,
  loading,
  error,
  onRefresh,
  onRunNow,
  onTriggerJob,
  actionLoading,
  actionMessage,
}: {
  response: AuctionAiAnalysisResponse | null
  loading: boolean
  error: string
  onRefresh: () => void
  onRunNow: () => void
  onTriggerJob: () => void
  actionLoading: boolean
  actionMessage: string
}) {
  const analysis = safeRecord(response?.analysis_result)
  const conclusion = safeRecord(analysis.conclusion)
  const dataQuality = safeRecord(analysis.data_quality)
  const auctionAssessment = safeRecord(analysis.auction_assessment)
  const openingSignal = safeRecord(safeRecord(auctionAssessment.opening_signal))
  const technicalContext = safeRecord(analysis.technical_context)
  const marketAndSector = safeRecord(analysis.market_and_sector)
  const fundamentalRisk = safeRecord(analysis.fundamental_risk)
  const styleViews = safeRecord(analysis.style_views)
  const quantScore = safeRecord(safeRecord(styleViews.quant_score))
  const riskWarning = safeRecord(styleViews.risk_warning)
  const intraday = safeRecord(styleViews.intraday)
  const scenario = safeRecord(analysis.scenario_observation)
  const warnings = textList(dataQuality.warnings)
  const evidence = textList(analysis.key_evidence)
  const limitations = textList(analysis.limitations)

  const hasResult = Boolean(response?.analysis_result)

  return (
    <Card className="min-w-0 border-white/70 bg-white/85 shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="size-4 text-slate-500" />
              竞价 AI 解读
            </CardTitle>
            <div className="mt-1 text-xs text-slate-500">集合竞价、技术位置、行业市场、财务风险的压缩摘要分析</div>
          </div>
          <Button size="sm" onClick={onRefresh} disabled={loading} className="w-full gap-2 sm:w-auto">
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
            {loading ? "读取中" : "刷新结果"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] text-slate-600 sm:grid-cols-5">
          <div><span className="font-medium text-slate-900">0-20</span> 极弱/高风险</div>
          <div><span className="font-medium text-slate-900">21-40</span> 偏弱</div>
          <div><span className="font-medium text-slate-900">41-60</span> 中性/分歧</div>
          <div><span className="font-medium text-slate-900">61-80</span> 偏强</div>
          <div><span className="font-medium text-slate-900">81-100</span> 强势</div>
        </div>

        {error ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            {error}
          </div>
        ) : null}

        {actionMessage ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
            {actionMessage}
          </div>
        ) : null}

        {!hasResult ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
            <div>今日暂无持久化竞价 AI 解读。调度器会在工作日 09:26 后生成，盘中读取默认不会再次调用 AI。</div>
            <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
              <Button size="sm" onClick={onRunNow} disabled={actionLoading} className="w-full gap-2 sm:w-auto">
                <Play className="size-4" />
                {actionLoading ? "处理中" : "立即生成当前标的"}
              </Button>
              <Button size="sm" variant="outline" onClick={onTriggerJob} disabled={actionLoading} className="w-full gap-2 sm:w-auto">
                <RefreshCw className={cn("size-4", actionLoading && "animate-spin")} />
                触发今日批量任务
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
              <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={cn("rounded-full px-2 py-0", biasTone(conclusion.bias))}>
                    {fmt(conclusion.bias)}
                  </Badge>
                  <Badge variant="outline" className="rounded-full border-slate-200 bg-white px-2 py-0 text-slate-700">
                    {fmt(conclusion.auction_state)}
                  </Badge>
                  <Badge variant="outline" className={cn("rounded-full px-2 py-0", scoreTone(conclusion.confidence))}>
                    置信 {fmt(conclusion.confidence)}
                  </Badge>
                </div>
                <div className="mt-3 break-words text-base font-semibold leading-6 text-slate-900">
                  {safeString(conclusion.summary) || "—"}
                </div>
                <div className="mt-2 break-words text-sm leading-6 text-slate-600">
                  {safeString(conclusion.key_reason) || "—"}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MetricPill label="总分" value={quantScore.total_score} tone={scoreTone(quantScore.total_score)} />
                <MetricPill label="风险惩罚" value={quantScore.risk_penalty} tone={riskTone(riskWarning.risk_level)} />
                <MetricPill label="竞价强度" value={openingSignal.strength_score} tone={scoreTone(openingSignal.strength_score)} />
                <MetricPill label="资金活跃" value={openingSignal.fund_activity_score} tone={scoreTone(openingSignal.fund_activity_score)} />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StyleViewCard title="超短" icon={<Sparkles className="size-3" />} data={safeRecord(styleViews.ultra_short)} />
              <StyleViewCard title="日内" icon={<Target className="size-3" />} data={intraday} />
              <StyleViewCard title="波段" icon={<Target className="size-3" />} data={safeRecord(styleViews.swing)} />
              <StyleViewCard title="风险" icon={<ShieldAlert className="size-3" />} data={riskWarning} risk />
            </div>

            <div className="grid gap-3 lg:grid-cols-3">
              <MetricPill label="日线位置" value={technicalContext.daily_position} />
              <MetricPill label="量价匹配" value={technicalContext.volume_price_match} />
              <MetricPill label="市场宽度确认" value={marketAndSector.breadth_confirmation} />
              <MetricPill label="行业确认" value={marketAndSector.sector_confirmation} />
              <MetricPill label="题材热度" value={marketAndSector.theme_heat} />
              <MetricPill label="基本面风险" value={fundamentalRisk.risk_level} tone={riskTone(fundamentalRisk.risk_level)} />
            </div>

            <div className="grid gap-3 xl:grid-cols-3">
              {["bullish_case", "base_case", "bearish_case"].map((key) => {
                const item = safeRecord(scenario[key])
                return (
                  <div key={key} className="rounded-xl border border-slate-200 bg-white p-3">
                    <div className="text-[11px] font-medium text-slate-500">
                      {key === "bullish_case" ? "偏强情景" : key === "base_case" ? "基准情景" : "偏弱情景"}
                    </div>
                    <div className="mt-2 break-words text-xs leading-5 text-slate-700">{safeString(item.condition) || "—"}</div>
                    <div className="mt-1 break-words text-xs leading-5 text-slate-500">{safeString(item.meaning) || "—"}</div>
                    <Badge variant="outline" className={cn("mt-2 rounded-full px-2 py-0 text-[10px]", scoreTone(item.confidence))}>
                      置信 {fmt(item.confidence)}
                    </Badge>
                  </div>
                )
              })}
            </div>

            {intraday.watch_15min || intraday.watch_30min ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-[11px] font-medium text-slate-500">日内观察</div>
                <div className="mt-2 grid gap-2 text-xs leading-5 text-slate-700 md:grid-cols-3">
                  <div className="rounded-lg bg-white p-2">5 分钟：{fmt(intraday.watch_5min)}</div>
                  <div className="rounded-lg bg-white p-2">15 分钟：{fmt(intraday.watch_15min)}</div>
                  <div className="rounded-lg bg-white p-2">30 分钟：{fmt(intraday.watch_30min)}</div>
                </div>
              </div>
            ) : null}

            <div className="grid gap-3 xl:grid-cols-3">
              <SectionList title="关键证据" items={evidence} />
              <SectionList title="数据限制" items={limitations} />
              <SectionList title="数据质量提示" items={warnings} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function AuctionTab({
  targetType,
  symbol,
  name,
  adjust = "qfq",
}: AuctionTabProps) {
  const [auction, setAuction] = useState<StockAuctionSnapshot | null>(null)
  const [error, setError] = useState<string>("")
  const [aiResponse, setAiResponse] = useState<AuctionAiAnalysisResponse | null>(null)
  const [aiError, setAiError] = useState("")
  const [aiLoading, setAiLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionMessage, setActionMessage] = useState("")

  useEffect(() => {
    let active = true

    void (async () => {
      try {
        if (!active) return
        setError("")
        const auctionResult = await fetchStockAuction(symbol)
        if (!active) return
        setAuction(auctionResult)
      } catch (err) {
        if (!active) return
        const msg = err instanceof Error ? err.message : "加载集合竞价失败"
        setAuction(null)
        setError(msg)
        notification.danger({ title: "加载集合竞价失败", description: msg })
      }
    })()

    return () => {
      active = false
    }
  }, [symbol, name])

  useEffect(() => {
    setAiResponse(null)
    setAiError("")
    setActionMessage("")
  }, [targetType, symbol, name, adjust])

  const canRunAi = useMemo(() => Boolean(symbol && name), [symbol, name])

  const handleRefreshAiSnapshot = async () => {
    if (!canRunAi) return
    try {
      setAiLoading(true)
      setAiError("")
      const response = await fetchAuctionAiAnalysisSnapshot({
        targetType,
        symbol,
      })
      setAiResponse(response)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "读取竞价 AI 分析结果失败"
      setAiResponse(null)
      setAiError(msg)
      notification.danger({ title: "读取竞价 AI 分析结果失败", description: msg })
    } finally {
      setAiLoading(false)
    }
  }

  const handleRunNow = async () => {
    if (!canRunAi) return
    try {
      setActionLoading(true)
      setActionMessage("")
      setAiError("")
      const response = await runAuctionAiAnalysis({
        targetType,
        symbol,
        name,
        adjust,
        maxChars: 1000000,
      })
      setAiResponse(response)
      setActionMessage("已立即生成当前标的的竞价 AI 分析，并写入当日持久化结果。")
      notification.success({
        title: "竞价 AI 分析已生成",
        description: `${name} · ${symbol}`,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : "立即生成竞价 AI 分析失败"
      setAiError(msg)
      notification.danger({ title: "立即生成竞价 AI 分析失败", description: msg })
    } finally {
      setActionLoading(false)
    }
  }

  const handleTriggerJob = async () => {
    try {
      setActionLoading(true)
      setActionMessage("")
      setAiError("")
      const result = await triggerAuctionAiAnalysisScheduler()
      if (result.error) {
        throw new Error(result.error)
      }
      setActionMessage(`已触发今日批量任务：成功 ${result.succeeded ?? 0}，失败 ${result.failed ?? 0}。正在读取当前标的结果。`)
      notification.info({
        title: "已触发今日批量任务",
        description: `成功 ${result.succeeded ?? 0}，失败 ${result.failed ?? 0}`,
      })
      await handleRefreshAiSnapshot()
    } catch (err) {
      const msg = err instanceof Error ? err.message : "触发今日批量任务失败"
      setAiError(msg)
      notification.danger({ title: "触发今日批量任务失败", description: msg })
    } finally {
      setActionLoading(false)
    }
  }

  useEffect(() => {
    void handleRefreshAiSnapshot()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType, symbol])

  return (
    <div className="min-w-0 space-y-4">
      <AuctionAiPanel
        response={aiResponse}
        loading={aiLoading}
        error={aiError}
        onRefresh={() => void handleRefreshAiSnapshot()}
        onRunNow={() => void handleRunNow()}
        onTriggerJob={() => void handleTriggerJob()}
        actionLoading={actionLoading}
        actionMessage={actionMessage}
      />

      {error ? (
        <div className="rounded-xl border border-dashed border-red-300 bg-red-50/70 p-6 text-sm text-red-600">
          加载集合竞价失败：{error}
        </div>
      ) : (
        <div className="max-w-full overflow-x-auto">
          <AuctionPanel auction={auction} />
        </div>
      )}
    </div>
  )
}
