import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { StockTargetType } from "../../stock-chart/lib/types"

export interface FundFlowTabProps {
  targetType: StockTargetType
  symbol: string
  name: string
}

export function FundFlowTab({ symbol, name }: FundFlowTabProps) {
  return (
    <Card className="min-w-0 border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
      <CardHeader>
        <CardTitle className="break-words text-base">资金 · {name} · {symbol}</CardTitle>
        <CardDescription>先保留 mock 结构，后续接入主力资金 / 分时资金等指标。</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-6 text-sm text-slate-500">
          资金模块待接入真实数据，当前为占位内容。
        </div>
      </CardContent>
    </Card>
  )
}
