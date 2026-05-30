import { useEffect, useState } from "react"

import { searchStockChart } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { StockSearchItem } from "../lib/types"

export function SymbolSearch({ onSelect }: { onSelect: (item: StockSearchItem) => void }) {
  const [query, setQuery] = useState("")
  const [items, setItems] = useState<StockSearchItem[]>([])

  useEffect(() => {
    let active = true
    void searchStockChart(query).then((result) => {
      if (active) setItems(result)
    }).catch(() => {
      if (active) setItems([])
    })
    return () => {
      active = false
    }
  }, [query])

  return (
    <div className="space-y-3">
      <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索股票 / 指数 / 板块" />
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <Button
            key={`${item.target_type}-${item.symbol}`}
            variant="outline"
            className="justify-start"
            onClick={() => {
              onSelect(item)
              setQuery("")
              setItems([])
            }}
          >
            {item.name} · {item.symbol}
          </Button>
        ))}
      </div>
    </div>
  )
}
