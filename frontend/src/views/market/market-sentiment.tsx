import { Activity, Heart, MessageSquareQuote, Smile } from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const PLACEHOLDER_CARDS = [
  {
    title: "Fear & Greed Index",
    description: "综合涨跌停比、量能、北向、新高新低等指标合成的市场情绪温度计(占位)。",
  },
  {
    title: "Bull-Bear Spread",
    description: "多空比、融资融券余额变化、期权 PCR(占位)。",
  },
  {
    title: "News Sentiment",
    description: "财经新闻 / 公告 / 研报的 NLP 情绪打分(占位)。",
  },
  {
    title: "Social Buzz",
    description: "雪球 / 东方财富吧 / X(推特)等社区讨论热度与情绪倾向(占位)。",
  },
  {
    title: "Margin & Leverage",
    description: "融资余额、场外杠杆、ETF 申赎信号(占位)。",
  },
  {
    title: "Regime Tag",
    description: "上行 / 震荡 / 下行 / 转折 的市场状态识别(占位)。",
  },
]

export default function MarketSentimentPage() {
  return (
    <WorkspaceShell sectionLabel="Market Sentiment" pageTitle="Mock Workspace">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Smile className="size-3.5" />
          Mock Workspace
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Market Sentiment
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            市场情绪的预留页面,后续接入情绪温度、多空对比、新闻 / 社区舆情打分、融资杠杆信号等。
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {PLACEHOLDER_CARDS.map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Heart className="size-4 text-muted-foreground" />
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
          <MessageSquareQuote className="size-4" />
          路线
        </div>
        后续接入 backend/services/stock/market_overview/sentiment.py,以及情绪相关调度任务,提供分钟级 / 日级的情绪分位曲线。
      </div>
    </WorkspaceShell>
  )
}
