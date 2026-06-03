import { Badge } from "@/components/ui/badge"
import type { StockKlineBar } from "../../stock-chart/lib/types"
import { fmtDateTime, fmtNumberWithCompact, fmtPercent, fmtSigned } from "../lib/format"

export function BarSummary({
  bar,
  prevClose,
  prevVolume,
  prevTurnover,
  color,
  focused,
}: {
  bar: StockKlineBar
  prevClose: number | null
  prevVolume: number | null
  prevTurnover: number | null
  color: string
  focused: boolean
}) {
  const hasPrev = typeof prevClose === "number" && Number.isFinite(prevClose)
  const change = hasPrev ? bar.close - (prevClose as number) : null
  const changePct = hasPrev && (prevClose as number) !== 0 ? ((change as number) / (prevClose as number)) * 100 : null
  const amplitude = bar.open !== 0 ? ((bar.high - bar.low) / bar.open) * 100 : null
  const upTone = change !== null && change > 0
  const downTone = change !== null && change < 0
  // A 股配色：涨红跌绿
  const toneText = upTone ? "text-rose-600" : downTone ? "text-emerald-600" : "text-slate-600"
  const toneBg = upTone
    ? "bg-rose-50 border-rose-200"
    : downTone
      ? "bg-emerald-50 border-emerald-200"
      : "bg-slate-50 border-slate-200"
  // 较昨日放/缩量
  const hasPrevVol = typeof prevVolume === "number" && Number.isFinite(prevVolume) && (prevVolume as number) > 0
  const volDelta = hasPrevVol ? bar.volume - (prevVolume as number) : null
  const volDeltaPct = hasPrevVol ? ((volDelta as number) / (prevVolume as number)) * 100 : null
  const volUpTone = volDelta !== null && volDelta > 0
  const volDownTone = volDelta !== null && volDelta < 0
  const volToneText = volUpTone ? "text-rose-600" : volDownTone ? "text-emerald-600" : "text-slate-600"
  const volToneBg = volUpTone
    ? "bg-rose-50 border-rose-200"
    : volDownTone
      ? "bg-emerald-50 border-emerald-200"
      : "bg-slate-50 border-slate-200"
  // 较昨日放/缩额
  const hasTurnover = typeof bar.turnover === "number"
  const hasPrevTurnover = typeof prevTurnover === "number" && Number.isFinite(prevTurnover) && (prevTurnover as number) > 0
  const turnoverDelta = hasTurnover && hasPrevTurnover ? (bar.turnover as number) - (prevTurnover as number) : null
  const turnoverDeltaPct = hasTurnover && hasPrevTurnover && (prevTurnover as number) !== 0
    ? ((turnoverDelta as number) / (prevTurnover as number)) * 100
    : null
  const turnoverUpTone = turnoverDelta !== null && turnoverDelta > 0
  const turnoverDownTone = turnoverDelta !== null && turnoverDelta < 0
  const turnoverToneText = turnoverUpTone ? "text-rose-600" : turnoverDownTone ? "text-emerald-600" : "text-slate-600"
  const turnoverToneBg = turnoverUpTone
    ? "bg-rose-50 border-rose-200"
    : turnoverDownTone
      ? "bg-emerald-50 border-emerald-200"
      : "bg-slate-50 border-slate-200"
  return (
    <>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-900">K 柱 · {fmtDateTime(bar.timestamp)}</div>
        <Badge
          className="rounded-full bg-white text-[10px]"
          style={{ borderColor: color, color }}
          variant="outline"
        >
          K Line
        </Badge>
      </div>
      <div className="grid gap-0.5 text-[11px] leading-5 text-slate-600">
        <div>
          <span className="text-slate-400">开</span>{" "}
          <span className="font-mono text-slate-700">{bar.open.toFixed(2)}</span>
          <span className="mx-1.5 text-slate-300">·</span>
          <span className="text-slate-400">高</span>{" "}
          <span className="font-mono text-slate-700">{bar.high.toFixed(2)}</span>
          <span className="mx-1.5 text-slate-300">·</span>
          <span className="text-slate-400">低</span>{" "}
          <span className="font-mono text-slate-700">{bar.low.toFixed(2)}</span>
          <span className="mx-1.5 text-slate-300">·</span>
          <span className="text-slate-400">收</span>{" "}
          <span className="font-mono text-slate-700">{bar.close.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-slate-400">成交量</span>{" "}
          <span className="font-mono text-slate-700">{bar.volume.toLocaleString()}</span>
          {hasPrevVol ? (
            <>
              <span className="mx-1.5 text-slate-300">·</span>
              <span className="text-slate-400">昨量</span>{" "}
              <span className="font-mono text-slate-700">{(prevVolume as number).toLocaleString()}</span>
            </>
          ) : null}
          {hasTurnover ? (
            <>
              <span className="mx-1.5 text-slate-300">·</span>
              <span className="text-slate-400">成交额</span>{" "}
              <span className="font-mono text-slate-700">{(bar.turnover as number).toLocaleString()}</span>
              {hasPrevTurnover ? (
                <>
                  <span className="mx-1.5 text-slate-300">·</span>
                  <span className="text-slate-400">昨额</span>{" "}
                  <span className="font-mono text-slate-700">{(prevTurnover as number).toLocaleString()}</span>
                </>
              ) : null}
            </>
          ) : null}
        </div>
        <div>
          <span className="text-slate-400">振幅</span>{" "}
          <span className="font-mono text-slate-700">{fmtPercent(amplitude ?? NaN)}</span>
          {hasPrev ? (
            <>
              <span className="mx-1.5 text-slate-300">·</span>
              <span className="text-slate-400">昨收</span>{" "}
              <span className="font-mono text-slate-700">{(prevClose as number).toFixed(2)}</span>
            </>
          ) : null}
        </div>
        {change !== null && changePct !== null ? (
          <div className={`mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${toneBg} ${toneText}`}>
            <span>{upTone ? "▲" : downTone ? "▼" : "■"}</span>
            <span className="font-mono">{fmtSigned(change)}</span>
            <span className="font-mono">{fmtPercent(changePct)}</span>
            <span className="text-slate-400">{upTone ? "涨幅" : downTone ? "跌幅" : "持平"}</span>
          </div>
        ) : (
          <div className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">
            <span>■</span>
            <span className="font-mono">—</span>
            <span className="text-slate-400">无昨收参考</span>
          </div>
        )}
        {volDelta !== null && volDeltaPct !== null ? (
          <div className={`mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${volToneBg} ${volToneText}`}>
            <span>{volUpTone ? "▲" : volDownTone ? "▼" : "■"}</span>
            <span className="font-mono">{fmtNumberWithCompact(volDelta)}</span>
            <span className="font-mono">{fmtPercent(volDeltaPct)}</span>
            <span className="text-slate-400">{volUpTone ? "放量" : volDownTone ? "缩量" : "持平"}</span>
          </div>
        ) : (
          <div className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">
            <span>■</span>
            <span className="font-mono">—</span>
            <span className="text-slate-400">无昨量参考</span>
          </div>
        )}
        {turnoverDelta !== null && turnoverDeltaPct !== null ? (
          <div className={`mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${turnoverToneBg} ${turnoverToneText}`}>
            <span>{turnoverUpTone ? "▲" : turnoverDownTone ? "▼" : "■"}</span>
            <span className="font-mono">{fmtNumberWithCompact(turnoverDelta)}</span>
            <span className="font-mono">{fmtPercent(turnoverDeltaPct)}</span>
            <span className="text-slate-400">{turnoverUpTone ? "放额" : turnoverDownTone ? "缩额" : "持平"}</span>
          </div>
        ) : hasTurnover ? (
          <div className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">
            <span>■</span>
            <span className="font-mono">—</span>
            <span className="text-slate-400">无昨额参考</span>
          </div>
        ) : null}
        {focused ? <div className="mt-0.5 text-[10px] text-slate-400">已聚焦 · 可在右侧继续叠加分析项</div> : null}
      </div>
    </>
  )
}
