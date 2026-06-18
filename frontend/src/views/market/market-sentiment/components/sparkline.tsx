/**
 * Recharts 折线图 (替代内联 SVG sparkline, 60px 高 + hover tooltip)
 */
import { Area, AreaChart, ResponsiveContainer, Tooltip, type TooltipContentProps } from "recharts"
import type { SparkPoint } from "../lib/spark"

interface SparklineProps {
  data: SparkPoint[]
  /** 线条颜色: 默认按末值 vs 首值 (涨红跌绿). 传 null 用中性. */
  color?: "auto" | "neutral" | "inverse"
  height?: number
  /** inverse: 末值越大越红 (适用 vol, score) */
  formatter?: (v: number) => string
}

export function Sparkline({ data, color = "auto", height = 60, formatter }: SparklineProps) {
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