import { useEffect, useState } from "react"
import { Check, Plus, Search } from "lucide-react"

import { searchStockChart } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import AnimatedList from "@/components/AnimatedList"
import type { StockSearchItem } from "../lib/types"

const TYPE_LABEL: Record<string, string> = {
  stock: "个股",
  index: "指数",
  sector: "板块",
}

export function SymbolSearch({
  onSelect,
  knownIds = [],
}: {
  onSelect: (item: StockSearchItem) => void
  knownIds?: string[]
}) {
  const [query, setQuery] = useState("")
  const [items, setItems] = useState<StockSearchItem[]>([])
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [recentlyAdded, setRecentlyAdded] = useState<Record<string, true>>({})

  useEffect(() => {
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedIndex(-1)
    void searchStockChart(query).then((result) => {
      if (active) setItems(result)
    }).catch(() => {
      if (active) setItems([])
    })
    return () => {
      active = false
    }
  }, [query])

  useEffect(() => {
    if (Object.keys(recentlyAdded).length === 0) return
    const timer = window.setTimeout(() => setRecentlyAdded({}), 1600)
    return () => window.clearTimeout(timer)
  }, [recentlyAdded])

  const handlePick = (item: StockSearchItem) => {
    onSelect(item)
    setRecentlyAdded((prev) => ({ ...prev, [`${item.target_type}-${item.symbol}`]: true }))
    setQuery("")
    setItems([])
    setSelectedIndex(-1)
  }

  return (
    <div className="space-y-2">
      <div className="group relative flex items-center rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-sm transition focus-within:border-slate-400 focus-within:shadow-md">
        <Search className="size-3.5 text-slate-400 transition group-focus-within:text-slate-700" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索股票 / 指数 / 板块"
          className="ml-2 w-full border-0 bg-transparent text-xs text-slate-700 outline-none focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-slate-400"
        />
        {query ? (
          <button
            type="button"
            aria-label="清除搜索"
            className="ml-1 inline-flex size-5 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            onClick={() => {
              setQuery("")
              setItems([])
            }}
          >
            ×
          </button>
        ) : null}
      </div>
      <div className="flex items-center justify-between px-1 text-[10px] font-medium text-slate-400">
        <span>{query ? "搜索结果" : "热门标的"}</span>
        <span>{items.length} 条</span>
      </div>
      <AnimatedList
        items={items}
        selectedIndex={selectedIndex >= 0 ? selectedIndex : undefined}
        onItemSelect={(item, index) => {
          setSelectedIndex(index)
          if (item) handlePick(item)
        }}
        renderItem={(item) => {
          const id = `${item.target_type}-${item.symbol}`
          const inList = knownIds.includes(id)
          const justAdded = Boolean(recentlyAdded[id])
          return (
            <div
              className={`flex w-full items-center justify-between gap-2 rounded-xl border bg-white px-3 py-2 text-left transition ${
                inList ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 hover:border-slate-400 hover:bg-slate-50"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="truncate text-sm font-semibold text-slate-800">{item.name}</div>
                  {inList && !justAdded ? <Badge className="rounded-full border-emerald-200 bg-emerald-50 text-emerald-700" variant="outline">已添加</Badge> : null}
                </div>
                <div className="mt-0.5 truncate text-xs text-slate-400">{item.symbol}</div>
              </div>
              <div className="flex items-center gap-2">
                <Badge className="rounded-full border-slate-200 bg-white text-slate-600" variant="outline">
                  {TYPE_LABEL[item.target_type] || item.target_type}
                </Badge>
                <button
                  type="button"
                  aria-label={justAdded ? "已加入目标" : "加入目标"}
                  className={`inline-flex size-7 items-center justify-center rounded-full border transition ${
                    justAdded
                      ? "border-emerald-300 bg-emerald-100 text-emerald-700"
                      : inList
                        ? "border-slate-200 bg-slate-50 text-slate-400"
                        : "border-slate-900 bg-slate-950 text-white hover:bg-slate-800"
                  }`}
                  onClick={(event) => {
                    event.stopPropagation()
                    if (!inList) handlePick(item)
                  }}
                  disabled={inList}
                >
                  {justAdded ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                </button>
              </div>
            </div>
          )
        }}
        emptyMessage={query ? `未找到「${query}」相关结果。` : "输入关键词搜索股票 / 指数 / 板块。"}
        maxHeight="max-h-[320px]"
        itemClassName="w-full"
      />
    </div>
  )
}
