import { useEffect, useMemo, useState } from "react"
import { Activity, Flame, Loader2, RefreshCw, TrendingUp } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { fetchStyleSectors, type StyleSectorItem } from "@/lib/api"

const PLACEHOLDER_CARDS = [
  {
    title: "Index Snapshot",
    description: "三大指数实时涨跌、成交额、领涨/领跌板块概览(占位)。",
  },
  {
    title: "Sector Heatmap",
    description: "申万一级 / 同花顺行业板块的涨跌幅热力图(占位)。",
  },
  {
    title: "Limit Up / Down",
    description: "涨停 / 跌停家数、连板高度、炸板率(占位)。",
  },
  {
    title: "Northbound Flow",
    description: "北向资金净流入、十大活跃股(占位)。",
  },
  {
    title: "Volume Leaders",
    description: "成交额 / 换手率 Top 榜单(占位)。",
  },
  {
    title: "Anomaly Alerts",
    description: "异动提醒:快速拉升、急速跳水、量比突增(占位)。",
  },
]

function changeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-muted-foreground"
  if (pct > 0.05) return "text-red-600 dark:text-red-400"
  if (pct < -0.05) return "text-emerald-600 dark:text-emerald-400"
  return "text-muted-foreground"
}

function changeBg(pct: number | null | undefined): string {
  if (pct == null) return "bg-muted/40"
  if (pct > 0.05) return "bg-red-50 dark:bg-red-950/30"
  if (pct < -0.05) return "bg-emerald-50 dark:bg-emerald-950/30"
  return "bg-muted/40"
}

function formatPct(pct: number | null | undefined): string {
  if (pct == null) return "—"
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(2)}%`
}

export default function MarketPulsePage() {
  const [items, setItems] = useState<StyleSectorItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchStyleSectors()
      setItems(res.items || [])
      setFetchedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const sorted = useMemo(
    () => [...items].sort((a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity)),
    [items],
  )

  return (
    <WorkspaceShell sectionLabel="Market Pulse" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Flame className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Market Pulse
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            市场脉搏的预留页面,后续接入指数快照、板块热力、涨跌停统计、北向资金等实时指标。
          </p>
        </div>
      </div>

      {/* === 风格板块涨跌幅 (29 个, 来自 /api/stock-chart/style-sectors) === */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              风格板块涨跌幅
            </h2>
            <p className="text-sm text-muted-foreground">
              29 个动态股票池, 等权平均涨跌幅 (TDX 风格板块口径)
              {fetchedAt ? ` · ${fetchedAt} 拉取` : ""}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            <span className="ml-1">刷新</span>
          </Button>
        </div>

        {error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            拉取失败: {error}
          </div>
        )}

        {loading && items.length === 0 ? (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-2xl border border-border/30 bg-muted/30"
              />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sorted.map((item) => (
              <Card key={item.name} className={`${changeBg(item.change_pct)} border-border/30`}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center justify-between text-sm font-medium text-foreground">
                    <span className="truncate">{item.name}</span>
                    <span className={`tabular-nums text-base font-semibold ${changeColor(item.change_pct)}`}>
                      {formatPct(item.change_pct)}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-xs text-muted-foreground tabular-nums">
                    样本 {item.valid_size} / {item.sample_size} 只
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* === 后续接入模块的占位 === */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {PLACEHOLDER_CARDS.map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="size-4 text-muted-foreground" />
                {item.title}
              </CardTitle>
              <CardDescription>Mock · 待接入</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-5 text-sm text-muted-foreground">
        <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
          <TrendingUp className="size-4" />
          路线
        </div>
        后续把 stock-overview/mock-market.tsx 中的强势板块 / 主力净流入 / 行业轮动 三个核心模块拆解后,逐步迁入本页面。
      </div>
    </WorkspaceShell>
  )
}
