import { useEffect, useMemo, useState } from "react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { notification } from "@/components/ui/notification"
import {
  fetchStyleSectors,
  fetchMarketOverviewAkshare,
  fetchMarketOverviewEltdx,
  fetchStyleSectorConstituents,
  fetchMarketHeatmap,
  fetchMarketPulseHistory,
  fetchManualFundFlow,
  type StyleSectorItem,
  type MarketOverview,
  type MarketOverviewEltdx,
  type MarketHistoryPoint,
  type MarketHistoryResponse,
  type ManualFundFlow,
  type IndustryConstituentsIndexResponse,
  type StyleSectorConstituent,
} from "@/lib/api"
import { formatReadable } from "./lib/format"
import { getMostRecentTradingDayClient, getPrevTradingDayClient, isTradeTimeClient } from "./lib/trading-time"

import { IndexKlineDeck } from "./components/index-kline-deck"
import { MarketPulsePanel } from "./components/market-pulse-panel"
import { IndustryHeatmap } from "./components/industry-heatmap"
import { LimitEmotionPanel } from "./components/limit-emotion-panel"
import { MarketPulseHeader } from "./components/market-pulse-header"
import { MarketOverviewCards } from "./components/market-overview-cards"
import { MarketStyleSectorsSection } from "./components/market-style-sectors-section"
import { MarketPlaceholderCards } from "./components/market-placeholder-cards"
import { MarketRoadmapNote } from "./components/market-roadmap-note"
import { ManualFundFlowDialog } from "./components/manual-fund-flow-dialog"
import { IndustryConstituentsDrawer } from "@/components/industry-constituents-drawer"

export default function MarketPulsePage() {
  const [items, setItems] = useState<StyleSectorItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  // 大盘成交额 / 主力净流入 (AKShare)
  const [overview, setOverview] = useState<MarketOverview | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [overviewFetchedAt, setOverviewFetchedAt] = useState<string | null>(null)
  // 市场概况 (eltdx): 独立获取, 互不影响 fund-flow 持久化
  const [overviewCounts, setOverviewCounts] = useState<MarketOverviewEltdx | null>(null)
  const [overviewCountsError, setOverviewCountsError] = useState<string | null>(null)

  // 手动粘贴的资金流 (东方财富资金流页面 copy-paste 兜底)
  const [manualFundFlow, setManualFundFlow] = useState<ManualFundFlow | null>(null)
  const [manualDialogOpen, setManualDialogOpen] = useState(false)

  // 历史序列 (用于"较昨日"diff: 从 history 找当前显示日期的真实上一交易日,
  // 不用 latest.json 里 stale 的 prevDayFlow, 否则用户粘贴 manual 6-15 时,
  // diff 会拿 6-11 的数据去减, 错一天)
  const [history, setHistory] = useState<MarketHistoryResponse | null>(null)

  // 风格板块 成分股 drawer (复用 industry-constituents-drawer, 走 external data 模式)
  const [constituentsOpen, setConstituentsOpen] = useState(false)
  const [constituentsStyle, setConstituentsStyle] = useState<string | null>(null)
  const [constituentsData, setConstituentsData] = useState<IndustryConstituentsIndexResponse | null>(null)
  const [constituentsLoading, setConstituentsLoading] = useState(false)

  // 行业板块热力图
  const [heatmapData, setHeatmapData] = useState<Awaited<ReturnType<typeof fetchMarketHeatmap>> | null>(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [heatmapAutoRefresh, setHeatmapAutoRefresh] = useState(false)
  const [heatmapKind, setHeatmapKind] = useState<"industries" | "concepts">("industries")

  // 历史趋势图 联动:
  //   hoveredPoint  → 鼠标 hover 某根柱子 (瞬时预览, 不持久化, 不影响 K 线)
  //   selectedPoint → 鼠标 click 某根柱子 (持久化, 钉住, 顶部 K 线 + 快照卡 全部跟随)
  //
  // **三级 fallback** 决定 overview 卡片显示:
  //   hoveredPoint ?? selectedPoint ?? overview (今日 / 上次收盘)
  //   hover 优先于 click: 用户先 click 锁定到 A 日, 然后 hover B 日预览 → 显示 B
  //   鼠标离开 hover → 自动回退到 click 锁定的 A 日
  //
  // selectedPoint 为 null 时, K 线回退到 getMostRecentTradingDayClient() / overview.tradingDate,
  // 优先级见下面的 activeTradingDate.
  const [hoveredPoint, setHoveredPoint] = useState<MarketHistoryPoint | null>(null)
  const [selectedPoint, setSelectedPoint] = useState<MarketHistoryPoint | null>(null)
  // overview 卡片显示源: hover > click > 今日 overview
  const activePoint = hoveredPoint ?? selectedPoint
  // isTradeTime: 后端 get_latest_snapshot 已经覆盖为"当前真实时间", 这里再补一道
  // 客户端兜底, 处理 overview 尚未到达的初始空窗.
  const liveIsTradeTime = overview?.isTradeTime ?? isTradeTimeClient()
  // K 线 + replay 状态只看 click 锁定的 selectedPoint (hover 不影响 K 线, 避免抖动).
  // selectedPoint 为 null 时直接用 getMostRecentTradingDayClient(): 工作日 → 今天,
  // 周末 → 上周五. 不要走 overview.tradingDate 兜底 (akshare 失败时它会是归档日
  // 例如 6-12, 把整个 deck 钉死). 注意: 不要用 liveIsTradeTime 做 fallback 分支,
  // 午休 (11:30-13:00) 和盘后 (15:00+) 也会被它打成 false, 仍然会走到 6-12.
  // Holidays: 客户端只懂周末; 真节假日前端会显示"暂无数据"空态, 这是合理退化.
  const activeTradingDate = selectedPoint?.date ?? getMostRecentTradingDayClient()
  const isReplayMode = Boolean(selectedPoint)
  const isPinnedReplay = Boolean(selectedPoint)

  /** 当前显示日期的真实"上一交易日" (用交易日历算, 再去 history 查) —
   *  cards 较昨日 diff 用这个, 不用 overview.prevDayFlow (stale).
   *  用日历而不是"history 中最大 < target" 是因为 history 可能含周末/非交易日的
   *  脏数据 (e.g. scheduler 误写在周六), 不能盲信. */
  const prevDayPoint = useMemo<MarketHistoryPoint | null>(() => {
    if (!history?.items?.length) return null
    const targetDate = selectedPoint?.date ?? activeTradingDate
    const expectedPrev = getPrevTradingDayClient(targetDate)
    // 1) 先按交易日历精确查
    const exact = history.items.find((p) => p.date === expectedPrev)
    if (exact) return exact
    // 2) 找不到 (history 缺那天, e.g. 节假日后端 archive 缺失), 退到 history 中
    //    < targetDate 的最大日期 (即使有周末夹在中间)
    let prev: MarketHistoryPoint | null = null
    for (const p of history.items) {
      if (p.date < targetDate) prev = p
      else break
    }
    return prev
  }, [history, selectedPoint, activeTradingDate])

  const clearReplay = () => {
    setSelectedPoint(null)
  }

  /**
   * 鼠标 hover 历史图某根柱子 → 瞬时切换 overview 卡片数据预览
   * (K 线不动, 只有成交额 / 主力净流入 卡片跟手)
   */
  const handlePointHover = (point: MarketHistoryPoint | null) => {
    setHoveredPoint(point)
  }

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

  const loadOverview = async () => {
    setOverviewLoading(true)
    setOverviewError(null)
    try {
      // fund-flow: eastmoney 资金流 (独立持久化)
      const res = await fetchMarketOverviewAkshare()
      setOverview(res)
      setOverviewFetchedAt(
        res.fetchedAt
          ? new Date(res.fetchedAt).toLocaleTimeString()
          : new Date().toLocaleTimeString(),
      )
    } catch (e) {
      setOverviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setOverviewLoading(false)
    }

    // eltdx: 全A成交额 / 涨跌家数 (独立持久化, 互不影响)
    try {
      const counts = await fetchMarketOverviewEltdx()
      setOverviewCounts(counts)
    } catch (e) {
      setOverviewCountsError(e instanceof Error ? e.message : String(e))
    }
  }

  const loadManualFundFlow = async (tradingDate: string) => {
    try {
      const data = await fetchManualFundFlow(tradingDate)
      setManualFundFlow(data)
    } catch {
      // 404 / 网络错都当 null, 不影响主流程
      setManualFundFlow(null)
    }
  }

  const loadHistory = async (range: "20d" | "60d" | "120d" | "1y" = "60d") => {
    try {
      const res = await fetchMarketPulseHistory(range)
      setHistory(res)
    } catch {
      // 拉不到不影响主流程, cards 退到 overview.prevDayFlow
      setHistory(null)
    }
  }

  /**
   * 把后端 constituents 映射到 14 列 IndustryConstituentsIndexResponse 形状,
   * 喂给现成的 IndustryConstituentsDrawer (external data 模式).
   *
   * 关键:  **column key 必须严格匹配 drawer COLUMNS 数组里的 key** (含 `(%)` 后缀).
   *        否则 drawer 的 `r[key]` 读 undefined -> 显示 "—".
   *        涨跌幅(%) / 换手(%) / 振幅(%) 都带 "(%)" 后缀.
   *
   * 数值列 (流通市值 / 流通股 / 成交额) 用 ``formatReadable`` 预格式化成
   * "1.5亿" / "2300万" / "5百万" / "1.2万亿" 字符串 (drawer 的 formatAmount 不做单位格式化).
   *
   * 缺失字段 (涨速 / 量比 / 市盈率) tencent snapshot 拿不到, 留 null -> drawer 渲染为 "—".
   */
  const mapToIndustryShape = (
    name: string,
    constituents: StyleSectorConstituent[],
  ): IndustryConstituentsIndexResponse => {
    return {
      ok: true,
      name,
      code: name, // 复用 drawer's code 字段 (显示用)
      count: constituents.length,
      matched: constituents.filter((c) => c.valid).length,
      indexFetchedAt: null,
      rowsFetchedAt: constituents[0] ? new Date().toISOString() : null,
      rows: constituents.map((c, i) => ({
        序号: i + 1,
        代码: c.code,                      // 已去前缀 (000048)
        名称: c.name,
        现价: c.last_price,
        "涨跌幅(%)": c.change_pct,        // <- 关键: 带 "(%)" 后缀
        涨跌: c.change_amount,
        涨速: null,                       // tencent snapshot 无 -> "—"
        "换手(%)": c.turnover_rate,       // <- 关键: 带 "(%)" 后缀, 后端实时算
        量比: null,                       // tencent snapshot 无 -> "—"
        "振幅(%)": c.amplitude,           // <- 关键: 带 "(%)" 后缀
        成交额: formatReadable(c.turnover_amount),    // 元 -> "1.5亿" / "2300万"
        流通股: formatReadable(c.circulating_shares),  // 股 -> "1.5亿" / "2300万"
        流通市值: formatReadable(c.circulating_market_cap),  // 元 -> "1.5亿" / "2300万"
        市盈率: null,                     // tencent snapshot 无 -> "—"
      })),
    }
  }

  const loadConstituents = async (name: string) => {
    setConstituentsLoading(true)
    setConstituentsData(null)
    try {
      const res = await fetchStyleSectorConstituents(name)
      if (!res.ok) {
        throw new Error(res.error || "加载失败")
      }
      setConstituentsData(mapToIndustryShape(name, res.constituents))
    } catch (e) {
      // drawer 静默失败, 由 drawer 自身的 loading skeleton 状态展示
      setConstituentsData(null)
    } finally {
      setConstituentsLoading(false)
    }
  }

  const loadHeatmap = async (kind: "industries" | "concepts" = heatmapKind) => {
    setHeatmapLoading(true)
    try {
      const data = await fetchMarketHeatmap(kind)
      setHeatmapData(data)
    } catch (err) {
      notification.danger({
        title: "热力图加载失败",
        description: err instanceof Error ? err.message : "未知错误",
      })
    } finally {
      setHeatmapLoading(false)
    }
  }

  useEffect(() => {
    void load()
    void loadOverview()
    void loadHeatmap()
    // 手动粘贴的资金流: 按当前 activeTradingDate 拉 (今天 / 上一个交易日)
    void loadManualFundFlow(getMostRecentTradingDayClient())
    // 历史序列 (用于 cards 的较昨日 diff)
    void loadHistory("60d")
    // 交易时间 5min 一次轮询; 非交易时间 30min 一次 (scheduler 也没在跑, 读 archive)
    const id = window.setInterval(
      () => {
        void loadOverview()
      },
      liveIsTradeTime ? 5 * 60_000 : 30 * 60_000,
    )
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveIsTradeTime])

  useEffect(() => {
    void loadHeatmap(heatmapKind)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatmapKind])

  return (
    <WorkspaceShell sectionLabel="Market Pulse" pageTitle="Mock Workspace">
      <MarketPulseHeader />

      {/* === 页面正文: 统一 24px section 间距, 5 大区块按 spec 顺序堆叠 === */}
      <div className="space-y-6">
        {/* === 大盘成交额 / 主力净流入 (AKShare 双源) === */}
        <MarketOverviewCards
          overview={overview}
          overviewError={overviewError}
          overviewLoading={overviewLoading}
          overviewFetchedAt={overviewFetchedAt}
          overviewCounts={overviewCounts}
          activePoint={activePoint}
          prevDayPoint={prevDayPoint}
          onRefresh={() => void loadOverview()}
          onClearReplay={clearReplay}
          manualFundFlow={manualFundFlow}
          onOpenManualDialog={() => setManualDialogOpen(true)}
        />

        {/* === 三大指数分时图 === */}
        <IndexKlineDeck
          tradingDate={activeTradingDate}
          replay={isReplayMode}
          pinned={isPinnedReplay}
          onClearPinned={clearReplay}
          isTradeTime={liveIsTradeTime}
        />

        {/* === 市场脉搏 · 历史趋势图 (4 视图复合图 + 洞察小指标) === */}
        <MarketPulsePanel
          defaultView="flow"
          selectedPoint={selectedPoint}
          hoveredPoint={hoveredPoint}
          onPointClick={(_idx, point) => {
            // toggle: 同一根再点 → 取消; 不同的 → 切换
            setSelectedPoint((cur) => (cur?.date === point.date ? null : point))
          }}
          onPointHover={handlePointHover}
        />

        {/* === 风格板块涨跌幅 (29 个, 来自 /api/stock-chart/style-sectors) === */}
        <MarketStyleSectorsSection
          items={items}
          loading={loading}
          error={error}
          fetchedAt={fetchedAt}
          onRefresh={() => void load()}
          onCellClick={(name) => {
            setConstituentsStyle(name)
            setConstituentsOpen(true)
            void loadConstituents(name)
          }}
        />

        {/* === 行业板块热力图 (同花顺式 ECharts Treemap) === */}
        <div className="h-[420px]">
          <IndustryHeatmap
            data={heatmapData as never}
            loading={heatmapLoading}
            onRefresh={() => void loadHeatmap(heatmapKind)}
            autoRefresh={heatmapAutoRefresh}
            onAutoRefreshChange={setHeatmapAutoRefresh}
            kind={heatmapKind}
            onKindChange={setHeatmapKind}
          />
        </div>

        {/* === 涨跌停情绪 (limitEmotion) · 涨停/跌停/触板/炸板/连板梯队 ===
            扩展模块, 挂在行业热力图下方, 不修改既有代码. */}
        <LimitEmotionPanel />

        {/* === 后续接入模块的占位 === */}
        <MarketPlaceholderCards />

        <MarketRoadmapNote />
      </div>

      {/* === 风格板块 成分股 drawer (复用 industry-application 的 IndustryConstituentsDrawer) === */}
      <IndustryConstituentsDrawer
        industryCode={constituentsStyle}
        industryName={constituentsStyle}
        open={constituentsOpen}
        onOpenChange={setConstituentsOpen}
        data={constituentsData}
        loading={constituentsLoading}
      />

      {/* === 手动粘贴资金流 dialog (东方财富资金流页面 copy-paste 兜底) === */}
      <ManualFundFlowDialog
        open={manualDialogOpen}
        onOpenChange={setManualDialogOpen}
        tradingDate={getMostRecentTradingDayClient()}
        existing={manualFundFlow}
        onSaved={(saved) => {
          setManualFundFlow(saved)
          // 保存后顺手 re-pull overview, 让 "数据滞后" 角标等状态刷新
          void loadOverview()
        }}
      />
    </WorkspaceShell>
  )
}
