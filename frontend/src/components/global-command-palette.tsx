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
  { id: "page-dashboard", label: "Dashboard", group: "Pages", icon: LayoutDashboard, to: "/dashboard", keywords: "dashboard home" },
  { id: "page-downloader", label: "Downloader", group: "Pages", icon: Sparkles, to: "/downloader", keywords: "downloader media" },
  { id: "page-mp4", label: "MP4 to Word · Workspace", group: "Pages", icon: History, to: "/mp4-to-word", keywords: "mp4 word transcript" },
  { id: "page-mp4-history", label: "MP4 · History", group: "Pages", icon: History, to: "/mp4-to-word/history", keywords: "mp4 history archive" },
  { id: "page-stock-chart", label: "Stock Chart · Workspace", group: "Pages", icon: TrendingUp, to: "/stock-chart", keywords: "stock chart kline k 线" },
  { id: "page-stock-overview", label: "Stock Overview · 市场情景", group: "Pages", icon: LineChart, to: "/stock-overview", keywords: "market regime overview 大盘" },
  { id: "page-app-analysis", label: "Application Analysis", group: "Pages", icon: Compass, to: "/stock-overview/application-analysis", keywords: "application analysis 题材 120 日 4 段" },
  { id: "page-self-selected", label: "Self-Selected · 自选", group: "Pages", icon: Star, to: "/stock-overview/self-selected", keywords: "self selected watchlist 自选" },
  { id: "page-stock-review", label: "Stock Review", group: "Pages", icon: LineChart, to: "/stock-review", keywords: "stock review" },
  { id: "page-scheduler", label: "Settings · Scheduler", group: "Pages", icon: Sparkles, to: "/settings/scheduler", keywords: "scheduler settings 调度" },
  { id: "page-knowledge", label: "Knowledge Base", group: "Pages", icon: History, to: "/knowledge-base", keywords: "knowledge base 知识库" },
]

const PALETTE_CACHE_TTL_MS = 30_000

interface PaletteData {
  selfSelected: SelfSelectedItem[]
  groups: SelfSelectedGroup[]
  analysis: ApplicationAnalysisTarget[]
  recentMp4: MP4HistoryListItem[]
  fetchedAt: number
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
        "inline-flex h-8 items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground",
        className,
      )}
    >
      <Search className="size-3.5" />
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

    const selfSelected: PaletteItem[] = data.selfSelected.map((it) => {
      const groupName = groupNameById.get(it.group_id) ?? ""
      return {
        id: `self-${it.id}`,
        label: `${it.name || it.symbol} · ${it.symbol}`,
        hint: groupName || undefined,
        group: "自选",
        icon: Star,
        to: `/stock-chart?target_type=${encodeURIComponent(it.market || "stock")}&symbol=${encodeURIComponent(it.symbol)}&name=${encodeURIComponent(it.name || it.symbol)}`,
        keywords: `${it.symbol} ${it.name ?? ""} ${groupName} watchlist`,
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
      className="border-0 shadow-2xl"
    >
      <CommandInput
        autoFocus
        placeholder="搜索页面、股票、代码、拼音... (Alt + K)"
        className="border-0"
      />
      <CommandList>
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
