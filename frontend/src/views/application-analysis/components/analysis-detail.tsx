import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { OverlayTable } from "./overlay-table"
import { SummaryList } from "./summary-list"
import { TrendBlock } from "./trend-block"
import { asRecord, textList } from "../lib/format"
import type { StockOverlayAnnotation } from "../../stock-chart/lib/types"

export function AnalysisDetail({
  analysis,
  overlays,
}: {
  analysis: Record<string, unknown>
  overlays: StockOverlayAnnotation[]
}) {
  const summary = (analysis.summary as Record<string, unknown> | undefined) || {}
  const trendState = asRecord(analysis.trend_state)
  const trendEntries = Object.entries(trendState)

  return (
    <div className="min-w-0 space-y-4">
      {trendEntries.length ? (
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {trendEntries.map(([key, value]) => (
            <TrendBlock key={key} title={`段 ${key.replace("segment_", "")} 趋势`} data={asRecord(value)} />
          ))}
        </div>
      ) : null}

      <Card className="min-w-0 rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
        <CardHeader>
          <CardTitle>结构摘要</CardTitle>
          <CardDescription>仅展示 AI JSON 中的摘要字段，不额外编造结论。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <SummaryList title="主要支撑" tone="success" items={textList(summary.main_support)} />
          <SummaryList title="主要压力" tone="danger" items={textList(summary.main_resistance)} />
          <SummaryList title="主要风险" tone="danger" items={textList(summary.main_risks)} />
          <SummaryList title="主要观察" tone="neutral" items={textList(summary.main_observations)} />
        </CardContent>
      </Card>

      <OverlayTable items={overlays} />

      <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
        <CardHeader>
          <CardTitle>严格 JSON 结果</CardTitle>
          <CardDescription>用于核对 AI 返回是否符合 annotation.md schema。</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="max-h-[520px] max-w-full overflow-auto rounded-2xl border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-100 sm:p-4">
            {JSON.stringify(analysis, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
