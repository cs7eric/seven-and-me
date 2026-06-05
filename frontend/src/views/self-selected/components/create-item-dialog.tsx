import { useEffect, useRef, useState } from "react"
import { ArrowLeft, Loader2, Search } from "lucide-react"

import { searchStockChart } from "@/lib/api"
import type { StockSearchItem } from "@/views/stock-chart/lib/types"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import {
  TARGET_TYPE_LABEL,
  getMarketClasses,
  inferMarketFromSymbol,
} from "../lib/constants"

interface CreateItemDialogProps {
  groupName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: (payload: { symbol: string; market?: string; name?: string; notes?: string }) => Promise<void>
}

const SEARCH_DEBOUNCE_MS = 250

export function CreateItemDialog({
  groupName,
  open,
  onOpenChange,
  onCreate,
}: CreateItemDialogProps) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<StockSearchItem[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [picked, setPicked] = useState<StockSearchItem | null>(null)
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 关闭 / 打开时重置
  useEffect(() => {
    if (open) {
      // 打开时让 input 自动聚焦
    } else {
      setQuery("")
      setResults([])
      setSearchError(null)
      setPicked(null)
      setNotes("")
      setSubmitError(null)
    }
  }, [open])

  // 输入 debounce 后调搜索
  useEffect(() => {
    if (picked) return
    const q = query.trim()
    if (!q) {
      setResults([])
      setSearchError(null)
      return
    }
    const timer = window.setTimeout(() => {
      let active = true
      setSearching(true)
      setSearchError(null)
      void searchStockChart(q)
        .then((res) => {
          if (!active) return
          setResults(res)
        })
        .catch((err: unknown) => {
          if (!active) return
          setSearchError(err instanceof Error ? err.message : "搜索失败")
          setResults([])
        })
        .finally(() => {
          if (active) setSearching(false)
        })
      return () => {
        active = false
      }
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [query, picked])

  const handlePick = (item: StockSearchItem) => {
    setPicked(item)
    setQuery("")
    setResults([])
  }

  const handleBack = () => {
    setPicked(null)
    setNotes("")
    setSubmitError(null)
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!picked) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await onCreate({
        symbol: picked.symbol,
        name: picked.name,
        market: inferMarketFromSymbol(picked.symbol) || undefined,
        notes: notes.trim() || undefined,
      })
      onOpenChange(false)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "未知错误")
    } finally {
      setSubmitting(false)
    }
  }

  const pickedMarket = inferMarketFromSymbol(picked?.symbol)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        {!picked ? (
          // ===== 第 1 步：搜索选择 =====
          <div className="space-y-3">
            <DialogHeader>
              <DialogTitle>加入「{groupName}」</DialogTitle>
              <DialogDescription>
                从搜索结果中选一只股票；输入代码（如 600519）或名称（如 茅台）。
              </DialogDescription>
            </DialogHeader>

            <SearchInput
              value={query}
              onChange={setQuery}
              loading={searching}
              onClear={() => {
                setQuery("")
                setResults([])
              }}
            />

            <div className="flex items-center justify-between px-1 text-[10px] font-medium text-muted-foreground">
              <span>{query ? "搜索结果" : "热门标的"}</span>
              <span>{searching ? "搜索中…" : `${results.length} 条`}</span>
            </div>

            <ResultsList
              items={results}
              emptyMessage={
                query
                  ? searchError
                    ? searchError
                    : "没有匹配的结果，换个关键词试试"
                  : "输入代码或名称开始搜索"
              }
              onPick={handlePick}
            />
          </div>
        ) : (
          // ===== 第 2 步：确认 =====
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>确认加入</DialogTitle>
              <DialogDescription>把以下股票加入「{groupName}」，可填备注。</DialogDescription>
            </DialogHeader>

            <div className="flex items-center gap-3 rounded-2xl border border-border/40 bg-muted/30 p-4">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-background/80 font-mono text-sm font-bold text-foreground">
                {picked.symbol.slice(0, 2)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-base font-bold text-foreground">
                    {picked.symbol}
                  </span>
                  {pickedMarket ? (
                    <span
                      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${getMarketClasses(pickedMarket)}`}
                    >
                      {pickedMarket}
                    </span>
                  ) : null}
                  <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {TARGET_TYPE_LABEL[picked.target_type] || picked.target_type}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-sm text-foreground">{picked.name}</div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="item-notes">备注</Label>
              <textarea
                id="item-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="可选，例如 行业地位 / 入场逻辑"
                rows={2}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>

            {submitError ? <p className="text-sm text-destructive">{submitError}</p> : null}

            <DialogFooter className="gap-2 sm:gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={handleBack}
                disabled={submitting}
                className="gap-1"
              >
                <ArrowLeft className="size-3.5" />
                换一只
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "加入中…" : "加入"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------
// 子组件
// ------------------------------------------------------------------

function SearchInput({
  value,
  onChange,
  loading,
  onClear,
}: {
  value: string
  onChange: (v: string) => void
  loading: boolean
  onClear: () => void
}) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (inputRef.current) inputRef.current.focus()
  }, [])

  return (
    <div className="group relative flex items-center rounded-2xl border border-border/40 bg-background/60 px-3 py-2 transition focus-within:border-border/80 focus-within:bg-background">
      {loading ? (
        <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
      ) : (
        <Search className="size-3.5 text-muted-foreground transition group-focus-within:text-foreground" />
      )}
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="600519 / 300750 / 茅台 / 宁德"
        className="ml-2 w-full border-0 bg-transparent text-sm shadow-none outline-none ring-0 focus-visible:ring-0 focus-visible:ring-offset-0"
      />
      {value ? (
        <button
          type="button"
          aria-label="清除搜索"
          className="ml-1 inline-flex size-5 items-center justify-center rounded-full text-muted-foreground transition hover:bg-muted hover:text-foreground"
          onClick={onClear}
        >
          ×
        </button>
      ) : null}
    </div>
  )
}

function ResultsList({
  items,
  emptyMessage,
  onPick,
}: {
  items: StockSearchItem[]
  emptyMessage: string
  onPick: (item: StockSearchItem) => void
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border/40 bg-muted/15 px-4 py-8 text-center text-xs text-muted-foreground">
        {emptyMessage}
      </div>
    )
  }
  return (
    <div className="max-h-[280px] overflow-y-auto rounded-2xl border border-border/30 bg-muted/20 p-1.5">
      <div className="flex flex-col gap-1">
        {items.map((item) => {
          const market = inferMarketFromSymbol(item.symbol)
          return (
            <button
              key={`${item.target_type}-${item.symbol}`}
              type="button"
              onClick={() => onPick(item)}
              className="flex items-center gap-2 rounded-xl border border-transparent bg-background/60 px-3 py-2 text-left text-sm transition-colors hover:border-border/40 hover:bg-muted/40"
            >
              <span className="font-mono text-sm font-bold text-foreground">
                {item.symbol}
              </span>
              {market ? (
                <span
                  className={`inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${getMarketClasses(market)}`}
                >
                  {market}
                </span>
              ) : null}
              <span className="min-w-0 flex-1 truncate text-foreground">{item.name}</span>
              <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {TARGET_TYPE_LABEL[item.target_type] || item.target_type}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
