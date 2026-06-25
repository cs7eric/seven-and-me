import { useCallback, useEffect, useMemo, useState } from "react"
import { createPortal } from "react-dom"
import { useNavigate } from "react-router-dom"
import {
  Compass,
  History,
  LayoutDashboard,
  LineChart,
  Search,
  Sparkles,
  Star,
  TrendingUp,
} from "lucide-react"

import { cn } from "@/lib/utils"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  fetchApplicationAnalysisTargets,
  fetchSelfSelectedGroups,
  fetchSelfSelectedItems,
  listMP4History,
  type ApplicationAnalysisTarget,
  type MP4HistoryListItem,
  type SelfSelectedGroup,
  type SelfSelectedItem,
} from "@/lib/api"

interface PaletteItem {
  id: string
  label: string
  hint?: string
  group: string
  icon: React.ComponentType<{ className?: string }>
  to: string
  keywords: string
}

const STATIC_NAV_ITEMS: PaletteItem[] = [
  { id: "page-home", label: "Applications · 首页", group: "Core", icon: LayoutDashboard, to: "/", keywords: "home applications app launcher 首页 应用" },
  { id: "page-dashboard", label: "Dashboard", group: "Core", icon: LayoutDashboard, to: "/dashboard", keywords: "dashboard overview metrics home 总览 仪表盘" },
  { id: "page-downloader", label: "Downloader", group: "Tools", icon: Sparkles, to: "/downloader", keywords: "downloader media video audio download 下载 媒体" },
  { id: "page-mp4", label: "MP4 to Word · Workspace", group: "Tools", icon: History, to: "/mp4-to-word", keywords: "mp4 word transcript transcription parse video 转写 文稿" },
  { id: "page-mp4-history", label: "MP4 · History", group: "Tools", icon: History, to: "/mp4-to-word/history", keywords: "mp4 history archive transcript 历史 归档" },
  { id: "page-scheduler", label: "Settings · Scheduler", group: "Tools", icon: Sparkles, to: "/settings/scheduler", keywords: "scheduler settings cron job 调度 任务 设置" },
  { id: "page-stock-chart", label: "Stock Chart · Workspace", group: "Stock", icon: TrendingUp, to: "/stock-chart", keywords: "stock chart kline candlestick k 线 股票 图表" },
  { id: "page-self-selected", label: "Self-Selected · 自选", group: "Stock", icon: Star, to: "/stock-overview/self-selected", keywords: "self selected watchlist favorites 自选 分组" },
  { id: "page-stock-review", label: "Stock Review", group: "Stock", icon: LineChart, to: "/stock-review", keywords: "stock review 复盘 股票 评审" },
  { id: "page-stock-overview", label: "Stock Overview · 市场情景", group: "Market", icon: LineChart, to: "/stock-overview", keywords: "market regime overview 大盘 市场概览 情景" },
  { id: "page-stock-overview-market", label: "Stock Overview · Market Pulse", group: "Market", icon: LineChart, to: "/stock-overview/market", keywords: "market pulse old overview 大盘 市场脉搏 旧版" },
  { id: "page-market-pulse", label: "Market Pulse · 市场脉搏", group: "Market", icon: TrendingUp, to: "/market/pulse", keywords: "market pulse breadth industry fund flow 涨跌 行业 资金 市场脉搏" },
  { id: "page-market-sentiment", label: "Market Sentiment · MSI", group: "Market", icon: LineChart, to: "/market/sentiment", keywords: "market sentiment msi emotion risk appetite 市场情绪 情绪指数" },
  { id: "page-app-analysis", label: "Application Analysis", group: "Market", icon: Compass, to: "/stock-overview/application-analysis", keywords: "application analysis theme 题材 120 日 四段 分析" },
  { id: "page-industry-application", label: "Industry / Concept · 行业概念", group: "Market", icon: Compass, to: "/stock-overview/industry-application", keywords: "industry concept sector heatmap 行业 概念 板块 sh8803 sh8804 eltdx 热力图" },
  { id: "page-poc", label: "POC Lab", group: "Dev", icon: Sparkles, to: "/poc", keywords: "poc lab prototype demo 实验" },
  { id: "page-heatmap-demo", label: "Heatmap Demo", group: "Dev", icon: LineChart, to: "/heatmap-demo", keywords: "heatmap demo treemap 热力图 demo" },
  { id: "page-heatmap-debug", label: "Heatmap Data Debug", group: "Dev", icon: LineChart, to: "/heatmap-data-debug", keywords: "heatmap data debug treemap 热力图 数据 调试" },
]

const PALETTE_CACHE_TTL_MS = 30_000

interface PaletteData {
  selfSelected: SelfSelectedItem[]
  groups: SelfSelectedGroup[]
  analysis: ApplicationAnalysisTarget[]
  recentMp4: MP4HistoryListItem[]
  fetchedAt: number
}

function normalizeSelfSelectedTarget(item: SelfSelectedItem) {
  const symbol = item.symbol.trim().toUpperCase()
  const targetType =
    item.target_type ?? (item.market?.toUpperCase() === "HK" ? "hk_stock" : "stock")
  const market = (item.market || targetType).trim().toUpperCase()
  return {
    key: `${targetType}:${market}:${symbol}`,
    symbol,
    targetType,
  }
}

function formatGroupHint(groupNames: string[]) {
  const names = Array.from(new Set(groupNames.filter(Boolean)))
  if (names.length === 0) return undefined
  if (names.length === 1) return names[0]
  return `${names[0]} +${names.length - 1}`
}

// ---- 模块级 store（singleton open 状态 + 跨组件触发） ----
type Listener = (open: boolean) => void
let openState = false
const listeners = new Set<Listener>()
const emit = () => listeners.forEach((l) => l(openState))
const setOpenState = (next: boolean) => {
  if (next === openState) return
  openState = next
  emit()
}

export function openGlobalCommand() {
  setOpenState(true)
}
export function closeGlobalCommand() {
  setOpenState(false)
}
export function toggleGlobalCommand() {
  setOpenState(!openState)
}

export function GlobalCommandTrigger({ className }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={openGlobalCommand}
      className={cn(
        "inline-flex h-9 items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 text-sm text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground",
        className,
      )}
    >
      <Search className="size-4" />
      <span>搜索</span>
      <span className="ml-1 inline-flex items-center gap-0.5 rounded border border-border/70 bg-background/80 px-1 py-0.5 font-mono text-[10px]">
        Alt K
      </span>
    </button>
  )
}

export function GlobalCommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(openState)
  const [data, setData] = useState<PaletteData | null>(null)
  const [loading, setLoading] = useState(false)

  // 订阅 singleton 状态
  useEffect(() => {
    const l: Listener = (next) => setOpen(next)
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])

  // 全局快捷键：Alt+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.altKey &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.shiftKey &&
        e.key.toLowerCase() === "k"
      ) {
        e.preventDefault()
        toggleGlobalCommand()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const ensureData = useCallback(async () => {
    if (data && Date.now() - data.fetchedAt < PALETTE_CACHE_TTL_MS) return
    setLoading(true)
    try {
      const [groupsRes, itemsRes, analysisRes, historyRes] = await Promise.allSettled([
        fetchSelfSelectedGroups(),
        fetchSelfSelectedItems(),
        fetchApplicationAnalysisTargets(),
        listMP4History(),
      ])

      setData({
        groups:
          groupsRes.status === "fulfilled" && groupsRes.value.ok
            ? groupsRes.value.items
            : [],
        selfSelected:
          itemsRes.status === "fulfilled" && itemsRes.value.ok
            ? itemsRes.value.items
            : [],
        analysis:
          analysisRes.status === "fulfilled" ? analysisRes.value.items || [] : [],
        recentMp4:
          historyRes.status === "fulfilled" ? historyRes.value.slice(0, 8) : [],
        fetchedAt: Date.now(),
      })
    } catch {
      setData({
        groups: [],
        selfSelected: [],
        analysis: [],
        recentMp4: [],
        fetchedAt: Date.now(),
      })
    } finally {
      setLoading(false)
    }
  }, [data])

  useEffect(() => {
    if (open) void ensureData()
  }, [open, ensureData])

  const handleSelect = useCallback(
    (to: string) => {
      closeGlobalCommand()
      navigate(to)
    },
    [navigate],
  )

  const handleOpenChange = useCallback((next: boolean) => {
    setOpenState(next)
  }, [])

  const items = useMemo<PaletteItem[]>(() => {
    if (!data) return STATIC_NAV_ITEMS
    const groupNameById = new Map(data.groups.map((g) => [g.id, g.name]))

    const uniqueSelfSelected = new Map<
      string,
      { item: SelfSelectedItem; groupNames: string[] }
    >()
    for (const item of data.selfSelected) {
      const target = normalizeSelfSelectedTarget(item)
      const groupName = groupNameById.get(item.group_id) ?? ""
      const existing = uniqueSelfSelected.get(target.key)
      if (existing) {
        existing.groupNames.push(groupName)
      } else {
        uniqueSelfSelected.set(target.key, { item, groupNames: [groupName] })
      }
    }

    const selfSelected: PaletteItem[] = Array.from(uniqueSelfSelected.values()).map(({ item, groupNames }) => {
      const target = normalizeSelfSelectedTarget(item)
      const hint = formatGroupHint(groupNames)
      return {
        id: `self-${target.key}`,
        label: `${item.name || target.symbol} · ${target.symbol}`,
        hint,
        group: "自选",
        icon: Star,
        to: `/stock-chart?target_type=${encodeURIComponent(target.targetType)}&symbol=${encodeURIComponent(target.symbol)}&name=${encodeURIComponent(item.name || target.symbol)}`,
        keywords: `${target.symbol} ${item.name ?? ""} ${groupNames.join(" ")} watchlist 自选`,
      }
    })

    const analysis: PaletteItem[] = data.analysis.map((it) => ({
      id: `analysis-${it.id}`,
      label: `${it.name} · ${it.symbol}`,
      hint: it.target_type === "index" ? "指数" : "个股",
      group: "Application Analysis",
      icon: Compass,
      to: `/stock-overview/application-analysis?target=${encodeURIComponent(it.id)}`,
      keywords: `${it.symbol} ${it.name} analysis 题材 120 日`,
    }))

    const mp4: PaletteItem[] = data.recentMp4.map((it) => ({
      id: `mp4-${it.id}`,
      label: it.title || it.task_id,
      hint: it.status,
      group: "MP4 历史",
      icon: History,
      to: `/mp4-to-word/history/${encodeURIComponent(it.id)}`,
      keywords: `${it.title ?? ""} ${it.task_id} mp4 history`,
    }))

    return [...STATIC_NAV_ITEMS, ...selfSelected, ...analysis, ...mp4]
  }, [data])

  const groups = useMemo(() => {
    const map = new Map<string, PaletteItem[]>()
    for (const it of items) {
      const arr = map.get(it.group) ?? []
      arr.push(it)
      map.set(it.group, arr)
    }
    return Array.from(map.entries())
  }, [items])

  if (typeof document === "undefined") return null

  return createPortal(
    <CommandDialog
      open={open}
      onOpenChange={handleOpenChange}
      title="全局搜索"
      description="Alt + K 唤起，搜索页面 / 自选 / 分析标的 / MP4 历史"
      className="w-[calc(100vw-1rem)] border-0 shadow-2xl sm:max-w-[840px] lg:max-w-[960px]"
    >
      <CommandInput
        autoFocus
        placeholder="搜索页面、股票、代码、拼音... (Alt + K)"
        className="border-0"
      />
      <CommandList className="max-h-[min(72vh,640px)]">
        <CommandEmpty>
          {loading ? "正在拉取数据..." : "未找到结果"}
        </CommandEmpty>
        {groups.map(([groupName, groupItems]) => (
          <CommandGroup key={groupName} heading={groupName}>
            {groupItems.map((it) => {
              const Icon = it.icon
              return (
                <CommandItem
                  key={it.id}
                  value={`${it.label} ${it.hint ?? ""} ${it.keywords}`}
                  onSelect={() => handleSelect(it.to)}
                >
                  <Icon className="mr-2 size-4 text-slate-500" />
                  <span className="flex-1 truncate">{it.label}</span>
                  {it.hint ? (
                    <span className="ml-2 text-xs text-slate-400">{it.hint}</span>
                  ) : null}
                </CommandItem>
              )
            })}
          </CommandGroup>
        ))}
      </CommandList>
      <div className="flex items-center gap-3 border-t border-slate-200 px-3 py-1.5 text-[10px] tracking-wide text-slate-400">
        <span>↑↓ 选择</span>
        <span>↵ 打开</span>
        <span>esc 关闭</span>
        <span className="ml-auto rounded border border-border/70 bg-background/80 px-1 py-0.5 font-mono">
          Alt K
        </span>
      </div>
    </CommandDialog>,
    document.body,
  )
}
