import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, Bot, CheckCircle2, FileJson, LineChart, RefreshCw, ShieldAlert, Sparkles } from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fetchStockKlines, runApplicationAnalysis } from "@/lib/api"
import { ChartPanel } from "../stock-chart/components/chart-panel"
import { SymbolSearch } from "../stock-chart/components/symbol-search"
import type { ApplicationAnalysisResponse, StockAdjust, StockKlineBar, StockOverlayAnnotation, StockPeriod, StockSearchItem, StockTargetType } from "../stock-chart/lib/types"

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? "").trim()).filter(Boolean)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asOverlayAnnotations(value: unknown): StockOverlayAnnotation[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is StockOverlayAnnotation => Boolean(item && typeof item === "object" && Array.isArray((item as StockOverlayAnnotation).points)))
}

function fmt(value: unknown) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

function MetricCard({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Bot }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs text-slate-500"><Icon className="size-3.5" />{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-950">{value}</div>
    </div>
  )
}

function SummaryList({ title, items, tone }: { title: string; items: string[]; tone: "success" | "danger" | "neutral" }) {
  const toneClass = tone === "success" ? "border-l-emerald-500" : tone === "danger" ? "border-l-red-500" : "border-l-slate-500"
  return (
    <div className={`rounded-2xl border border-slate-200 border-l-4 bg-white p-4 ${toneClass}`}>
      <div className="mb-3 text-sm font-semibold text-slate-800">{title}</div>
      <div className="space-y-2">
        {items.length ? items.map((item) => <div key={item} className="rounded-xl bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">{item}</div>) : <div className="text-sm text-slate-400">暂无内容</div>}
      </div>
    </div>
  )
}

function TrendBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        <Badge className="rounded-full border-slate-200 bg-slate-50 text-slate-700" variant="outline">{fmt(data.state)}</Badge>
      </div>
      <div className="grid gap-2 text-sm text-slate-600">
        <div>趋势分：{fmt(data.score)} · 置信度：{fmt(data.confidence)}</div>
        <div>均线：{fmt(data.ma_structure)}</div>
        <div>价格结构：{fmt(data.price_structure)}</div>
        <div>量能：{fmt(data.volume_state)}</div>
        <div>换手：{fmt(data.turnover_state)}</div>
      </div>
    </div>
  )
}

function OverlayTable({ items }: { items: StockOverlayAnnotation[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700">AI 可渲染标注 · {items.length}</div>
      <div className="divide-y divide-slate-100">
        {items.length ? items.map((item, index) => (
          <div key={`${item.overlay_type}-${index}`} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[160px_1fr_120px]">
            <Badge className="w-fit rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{item.overlay_type}</Badge>
            <div className="text-slate-700">{item.text || "未命名标注"}</div>
            <div className="text-slate-400">{item.points.length} points</div>
          </div>
        )) : <div className="px-4 py-8 text-sm text-slate-400">AI 没有返回可渲染标注。</div>}
      </div>
    </div>
  )
}

export default function ApplicationAnalysisPage() {
  const [target, setTarget] = useState<StockSearchItem>({ target_type: "index", symbol: "000001", name: "上证指数" })
  const [adjust, setAdjust] = useState<StockAdjust>("qfq")
  const [bars, setBars] = useState<StockKlineBar[]>([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ApplicationAnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void fetchStockKlines({ targetType: target.target_type, symbol: target.symbol, name: target.name, period: "1d" as StockPeriod, adjust }).then((data) => {
      if (active) setBars(data.items)
    }).catch(() => {
      if (active) setBars([])
    })
    return () => {
      active = false
    }
  }, [adjust, target])

  const analysis = result?.analysis_result
  const summary = analysis?.summary ?? {}
  const dataQuality = analysis?.data_quality ?? {}
  const trendState = asRecord(analysis?.trend_state)
  const dailyTrend = asRecord(trendState.daily)
  const weeklyTrend = asRecord(trendState.weekly)
  const overlays = useMemo(() => asOverlayAnnotations(analysis?.overlay_annotations), [analysis])
  const warnings = textList(dataQuality.warnings)

  const handleRun = async () => {
    try {
      setRunning(true)
      setError(null)
      const response = await runApplicationAnalysis({ targetType: target.target_type as StockTargetType, symbol: target.symbol, name: target.name, adjust })
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Application Analysis 失败")
    } finally {
      setRunning(false)
    }
  }

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Application Analysis">
      <div className="relative -mx-2 -my-4 rounded-3xl border border-slate-200 bg-[#f6f7f9] p-3 sm:p-5 xl:p-6">
        <div className="space-y-6">
          <Card className="overflow-hidden rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
            <CardHeader className="border-b border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)]">
              <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                <div className="space-y-3">
                  <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm">
                    <Sparkles className="size-3.5" />Application Analysis · annotation prompt
                  </div>
                  <CardTitle className="text-4xl font-semibold tracking-[-0.055em] text-slate-950">AI K 线结构标注分析</CardTitle>
                  <CardDescription className="max-w-3xl leading-6 text-slate-500">后端使用真实 K 线、周线、市场情绪序列和四大指数数据，严格按 prompt/annotation.md 生成 JSON 与 overlay_annotations。</CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={adjust} onValueChange={(value) => setAdjust(value as StockAdjust)}>
                    <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="qfq">前复权</SelectItem>
                      <SelectItem value="none">不复权</SelectItem>
                      <SelectItem value="hfq">后复权</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button className="rounded-xl bg-slate-950 text-white hover:bg-slate-800" onClick={() => void handleRun()} disabled={running}>
                    <RefreshCw className={`mr-2 size-4 ${running ? "animate-spin" : ""}`} />执行 AI 分析
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 p-5">
              <SymbolSearch onSelect={(item) => {
                setTarget(item)
                setResult(null)
              }} />
              <div className="grid gap-3 md:grid-cols-4">
                <MetricCard icon={LineChart} label="当前目标" value={`${target.name} · ${target.symbol}`} />
                <MetricCard icon={FileJson} label="日 K 数量" value={String(bars.length)} />
                <MetricCard icon={Bot} label="AI 状态" value={running ? "分析中" : result ? "已完成" : "待执行"} />
                <MetricCard icon={CheckCircle2} label="可渲染标注" value={String(overlays.length)} />
              </div>
            </CardContent>
          </Card>

          {error ? (
            <Alert variant="destructive" className="rounded-2xl border-red-200 bg-red-50">
              <ShieldAlert className="size-4" />
              <AlertTitle>分析失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {warnings.length ? (
            <Alert className="rounded-2xl border-amber-200 bg-amber-50 text-amber-900">
              <AlertTriangle className="size-4" />
              <AlertTitle>数据质量提示</AlertTitle>
              <AlertDescription>{warnings.join("；")}</AlertDescription>
            </Alert>
          ) : null}

          <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
            <CardHeader>
              <CardTitle>{target.name} · {target.symbol}</CardTitle>
              <CardDescription>AI overlay_annotations 会直接叠加到 K 线图。</CardDescription>
            </CardHeader>
            <CardContent>
              <ChartPanel bars={bars} annotations={[]} overlayAnnotations={overlays} bsSignals={[]} manualSignalMode={null} onManualSignalCreate={() => undefined} symbol={target.symbol} period="1d" indicators={["MA", "AMOUNT"]} maLines={[5, 10, 20, 60]} />
            </CardContent>
          </Card>

          {analysis ? (
            <>
              <div className="grid gap-6 xl:grid-cols-2">
                <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                  <CardHeader>
                    <CardTitle>趋势状态</CardTitle>
                    <CardDescription>{summary.current_status || "AI 返回的日线与周线结构判断。"}</CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4 md:grid-cols-2">
                    <TrendBlock title="日线" data={dailyTrend} />
                    <TrendBlock title="周线" data={weeklyTrend} />
                  </CardContent>
                </Card>

                <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                  <CardHeader>
                    <CardTitle>结构摘要</CardTitle>
                    <CardDescription>仅展示 AI JSON 中的摘要字段，不额外编造结论。</CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4 md:grid-cols-2">
                    <SummaryList title="主要支撑" tone="success" items={textList(summary.main_support)} />
                    <SummaryList title="主要压力" tone="danger" items={textList(summary.main_resistance)} />
                    <SummaryList title="主要风险" tone="danger" items={textList(summary.main_risks)} />
                    <SummaryList title="主要观察" tone="neutral" items={textList(summary.main_observations)} />
                  </CardContent>
                </Card>
              </div>

              <OverlayTable items={overlays} />

              <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
                <CardHeader>
                  <CardTitle>严格 JSON 结果</CardTitle>
                  <CardDescription>用于核对 AI 返回是否符合 annotation.md schema。</CardDescription>
                </CardHeader>
                <CardContent>
                  <pre className="max-h-[520px] overflow-auto rounded-2xl border border-slate-200 bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(analysis, null, 2)}</pre>
                </CardContent>
              </Card>
            </>
          ) : null}
        </div>
      </div>
    </WorkspaceShell>
  )
}
