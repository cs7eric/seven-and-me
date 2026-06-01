import { useEffect, useMemo, useState } from "react"
import { LineChart, RefreshCw, ShieldAlert, TrendingUp } from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fetchMarketOverview } from "@/lib/api"

interface MarketLevel {
  price: number
  type: string
  source: string
  strength: number
  label: string
  distancePct: number
}

interface WindowMetrics {
  window: number
  returnN: number | null
  highN: number | null
  lowN: number | null
  rangePosition: number | null
  drawdownFromHigh: number | null
  reboundFromLow: number | null
  volatility: number | null
  atrPct: number | null
  upDaysRatio: number | null
  volumeRatio: number | null
  amountRatio: number | null
  closeAboveMa20: boolean
  closeAboveMa60: boolean
  ma20Slope: number | null
  ma60Slope: number | null
}

interface SimilarForwardStat {
  forwardDays: number
  winRate: number
  avgReturn: number
  medianReturn: number
  maxReturn: number
  worstReturn: number
  medianMaxDrawdown: number
  positiveRatio: number
}

interface SimilarMatchDetail {
  date: string
  distance: number
  regimeBucket: string
  dominantStyle: string
  sentimentTrend: string
  rangePos60: number
  return20: number
  return60: number
}

interface MarketOverview {
  tradeDate: string
  summary: {
    regime: string
    overallScore: number
    shortTermState: string
    midTermState: string
    longTermState: string
    dominantStyle: string
    riskState: string
    conclusion: string
  }
  shanghai: {
    close: number
    rangeType: string
    windowMetrics: WindowMetrics[]
    supportLevels: MarketLevel[]
    resistanceLevels: MarketLevel[]
    nearestSupport: MarketLevel | null
    nearestResistance: MarketLevel | null
    ma20: number | null
    ma60: number | null
    ma120: number | null
    ma250: number | null
  }
  sentiment: {
    todayScore: number
    trendScore: number
    riskDiffusionScore: number
    state: string
    trend: string
    score5: number
    score20: number
  }
  styles: Array<{
    style: string
    source: string
    relativeReturn5: number | null
    relativeReturn20: number | null
    relativeReturn60: number | null
    state: string
  }>
  industries: Array<{
    name: string
    indexName: string
    symbol: string
    industryQuery: string
    provider: string
    relativeReturn5: number | null
    relativeReturn20: number | null
    relativeReturn60: number | null
    state: string
    score: number
  }>
  similarScenarioBacktest: {
    matchedCount: number
    medianDistance: number | null
    matchThreshold: number
    conclusion: string
    matchedDetails: SimilarMatchDetail[]
    forwardStats: SimilarForwardStat[]
  }
}

function fmtPct(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toFixed(digits)
}

function sourceLabel(source: string) {
  if (source === "ma") return "均线"
  if (source === "gap") return "缺口"
  if (source === "volumeNode") return "成交密集区"
  if (source === "swing") return "波段"
  if (source === "cluster") return "聚类"
  if (source === "rangeHighLow") return "区间高低点"
  return source
}

function regimeBucketLabel(bucket: string) {
  if (bucket === "trend_up") return "上升趋势"
  if (bucket === "trend_down") return "下降趋势"
  if (bucket === "near_high") return "接近上沿"
  if (bucket === "near_low") return "接近下沿"
  if (bucket === "range") return "震荡区间"
  if (bucket === "transition") return "过渡阶段"
  return bucket
}

function SummaryCard({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <Card className="border-border/40">
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{hint}</CardContent>
    </Card>
  )
}

function LevelList({ title, items }: { title: string; items: MarketLevel[] }) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-foreground">{title}</div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={`${item.source}-${item.label}-${item.price}`} className="rounded-xl border border-border/30 p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="font-medium">{item.label}</div>
              <Badge variant="secondary">{sourceLabel(item.source)}</Badge>
            </div>
            <div className="mt-1 text-muted-foreground">{fmtNum(item.price)} · {fmtPct(item.distancePct)} · 强度 {item.strength}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function StockOverviewPage() {
  const [data, setData] = useState<MarketOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await fetchMarketOverview()
      setData(result as unknown as MarketOverview)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载市场概览失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  const topIndustries = useMemo(() => (data?.industries ?? []).slice(0, 5), [data])
  const bottomIndustries = useMemo(() => (data?.industries ?? []).slice(-5).reverse(), [data])

  return (
    <WorkspaceShell sectionLabel="Market Regime" pageTitle="Application Overview">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
            <LineChart className="size-3.5" />
            Market Regime Overview
          </div>
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Application Overview</h1>
            <p className="max-w-4xl text-sm leading-7 text-muted-foreground sm:text-base">
              聚焦上证结构、多周期区间定位、支撑压力地图、情绪趋势、风格轮动、真实行业指数强弱，以及历史相似情景回测。
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`mr-2 size-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive">
          <ShieldAlert className="size-4" />
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
            <SummaryCard title="市场情景" value={data.summary.regime} hint={data.summary.conclusion} />
            <SummaryCard title="综合环境分" value={String(data.summary.overallScore)} hint={`风险状态：${data.summary.riskState}`} />
            <SummaryCard title="短期状态" value={data.summary.shortTermState} hint={`中期：${data.summary.midTermState}`} />
            <SummaryCard title="长期背景" value={data.summary.longTermState} hint={`主导风格：${data.summary.dominantStyle}`} />
            <SummaryCard title="今日情绪" value={fmtNum(data.sentiment.todayScore, 0)} hint={`5日 ${fmtNum(data.sentiment.score5, 0)} / 20日 ${fmtNum(data.sentiment.score20, 0)}`} />
            <SummaryCard title="情绪趋势" value={data.sentiment.trend} hint={`风险扩散 ${fmtNum(data.sentiment.riskDiffusionScore, 0)}`} />
          </div>

          <Card className="border-border/40">
            <CardHeader>
              <CardTitle>上证结构卡</CardTitle>
              <CardDescription>当前点位、均线、最近支撑与压力。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-border/30 p-4">
                <div className="text-xs text-muted-foreground">当前点位</div>
                <div className="mt-2 text-2xl font-semibold">{fmtNum(data.shanghai.close)}</div>
                <div className="mt-2 text-sm text-muted-foreground">区间类型：{data.shanghai.rangeType}</div>
              </div>
              <div className="space-y-1 rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                <div>MA20：{fmtNum(data.shanghai.ma20)}</div>
                <div>MA60：{fmtNum(data.shanghai.ma60)}</div>
                <div>MA120：{fmtNum(data.shanghai.ma120)}</div>
                <div>MA250：{fmtNum(data.shanghai.ma250)}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                <div className="font-medium text-foreground">最近支撑</div>
                <div>{data.shanghai.nearestSupport?.label ?? "—"}</div>
                <div>{fmtNum(data.shanghai.nearestSupport?.price)}</div>
                <div>{fmtPct(data.shanghai.nearestSupport?.distancePct)}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                <div className="font-medium text-foreground">最近压力</div>
                <div>{data.shanghai.nearestResistance?.label ?? "—"}</div>
                <div>{fmtNum(data.shanghai.nearestResistance?.price)}</div>
                <div>{fmtPct(data.shanghai.nearestResistance?.distancePct)}</div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
            <Card className="border-border/40">
              <CardHeader>
                <CardTitle>多周期回看矩阵</CardTitle>
                <CardDescription>5 / 10 / 15 / 20 / 30 / 60 / 100 / 120 / 250 日窗口。</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>窗口</TableHead>
                      <TableHead>涨跌幅</TableHead>
                      <TableHead>区间位置</TableHead>
                      <TableHead>距高点</TableHead>
                      <TableHead>距低点</TableHead>
                      <TableHead>ATR</TableHead>
                      <TableHead>状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.shanghai.windowMetrics.map((item) => (
                      <TableRow key={item.window}>
                        <TableCell>{item.window}</TableCell>
                        <TableCell>{fmtPct(item.returnN)}</TableCell>
                        <TableCell>{fmtPct(item.rangePosition)}</TableCell>
                        <TableCell>{fmtPct(item.drawdownFromHigh)}</TableCell>
                        <TableCell>{fmtPct(item.reboundFromLow)}</TableCell>
                        <TableCell>{fmtPct(item.atrPct)}</TableCell>
                        <TableCell>{item.rangePosition !== null && item.rangePosition > 0.8 ? "上沿" : item.rangePosition !== null && item.rangePosition < 0.2 ? "下沿" : (item.returnN ?? 0) > 0.03 ? "偏强" : (item.returnN ?? 0) < -0.03 ? "偏弱" : "震荡"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card className="border-border/40">
              <CardHeader>
                <CardTitle>支撑压力地图</CardTitle>
                <CardDescription>结合均线、区间高低点、缺口、波段聚类与成交密集区。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <LevelList title="上方压力" items={data.shanghai.resistanceLevels} />
                <LevelList title="下方支撑" items={data.shanghai.supportLevels} />
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card className="border-border/40">
              <CardHeader>
                <CardTitle>风格轮动</CardTitle>
                <CardDescription>5 / 20 / 60 日相对上证强弱。</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>风格</TableHead>
                      <TableHead>5日</TableHead>
                      <TableHead>20日</TableHead>
                      <TableHead>60日</TableHead>
                      <TableHead>状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.styles.map((item) => (
                      <TableRow key={item.style}>
                        <TableCell>{item.style}</TableCell>
                        <TableCell>{fmtPct(item.relativeReturn5)}</TableCell>
                        <TableCell>{fmtPct(item.relativeReturn20)}</TableCell>
                        <TableCell>{fmtPct(item.relativeReturn60)}</TableCell>
                        <TableCell>{item.state}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card className="border-border/40">
              <CardHeader>
                <CardTitle>行业强弱</CardTitle>
                <CardDescription>当前基于真实行业指数，展示相对上证的前后排分布。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium"><TrendingUp className="size-4" /> 强势前五</div>
                  <div className="space-y-2">
                    {topIndustries.map((item) => (
                      <div key={`${item.name}-${item.symbol}`} className="rounded-xl border border-border/30 p-3 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">{item.name}</div>
                          <Badge variant="secondary">{item.symbol}</Badge>
                        </div>
                        <div className="mt-1 text-muted-foreground">{item.indexName}</div>
                        <div className="mt-1 text-muted-foreground">20日 {fmtPct(item.relativeReturn20)} / 60日 {fmtPct(item.relativeReturn60)} / {item.state}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium"><ShieldAlert className="size-4" /> 弱势后五</div>
                  <div className="space-y-2">
                    {bottomIndustries.map((item) => (
                      <div key={`${item.name}-${item.symbol}`} className="rounded-xl border border-border/30 p-3 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">{item.name}</div>
                          <Badge variant="secondary">{item.symbol}</Badge>
                        </div>
                        <div className="mt-1 text-muted-foreground">{item.indexName}</div>
                        <div className="mt-1 text-muted-foreground">20日 {fmtPct(item.relativeReturn20)} / 60日 {fmtPct(item.relativeReturn60)} / {item.state}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="border-border/40">
            <CardHeader>
              <CardTitle>历史相似情景回测</CardTitle>
              <CardDescription>{data.similarScenarioBacktest.conclusion}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                  <div>相似样本数</div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">{data.similarScenarioBacktest.matchedCount}</div>
                </div>
                <div className="rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                  <div>中位距离</div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">{fmtNum(data.similarScenarioBacktest.medianDistance)}</div>
                </div>
                <div className="rounded-xl border border-border/30 p-4 text-sm text-muted-foreground">
                  <div>匹配阈值</div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">{fmtNum(data.similarScenarioBacktest.matchThreshold)}</div>
                </div>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>后续周期</TableHead>
                    <TableHead>上涨概率</TableHead>
                    <TableHead>平均收益</TableHead>
                    <TableHead>中位收益</TableHead>
                    <TableHead>最差表现</TableHead>
                    <TableHead>中位最大回撤</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.similarScenarioBacktest.forwardStats.map((item) => (
                    <TableRow key={item.forwardDays}>
                      <TableCell>{item.forwardDays}日</TableCell>
                      <TableCell>{fmtPct(item.winRate)}</TableCell>
                      <TableCell>{fmtPct(item.avgReturn)}</TableCell>
                      <TableCell>{fmtPct(item.medianReturn)}</TableCell>
                      <TableCell>{fmtPct(item.worstReturn)}</TableCell>
                      <TableCell>{fmtPct(item.medianMaxDrawdown)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="space-y-3">
                <div className="text-sm font-medium text-foreground">最近匹配样本</div>
                <div className="grid gap-3 xl:grid-cols-3">
                  {data.similarScenarioBacktest.matchedDetails.map((item) => (
                    <div key={`${item.date}-${item.distance}`} className="rounded-xl border border-border/30 p-4 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">{item.date}</div>
                        <Badge variant="outline">距离 {fmtNum(item.distance)}</Badge>
                      </div>
                      <div className="mt-2 space-y-1 text-muted-foreground">
                        <div>结构：{regimeBucketLabel(item.regimeBucket)}</div>
                        <div>风格：{item.dominantStyle}</div>
                        <div>情绪：{item.sentimentTrend}</div>
                        <div>60日区间位：{fmtPct(item.rangePos60)}</div>
                        <div>20日收益：{fmtPct(item.return20)}</div>
                        <div>60日收益：{fmtPct(item.return60)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      ) : null}
    </WorkspaceShell>
  )
}
