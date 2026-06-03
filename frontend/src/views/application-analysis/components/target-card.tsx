import { ChevronDown, ChevronRight, Clock, Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react"

import AnimatedList from "@/components/AnimatedList"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ApplicationAnalysisSchedulerStatus, ApplicationAnalysisTarget } from "@/lib/api"
import { SymbolSearch } from "../../stock-chart/components/symbol-search"
import type { StockSearchItem } from "../../stock-chart/lib/types"

export type HorizonPatch = Partial<Record<"days" | "segments" | "monthly_keep" | "weekly_keep", number>>

export function TargetCard({
  targets,
  filteredTargets,
  searchKeyword,
  setSearchKeyword,
  selectedId,
  setSelectedId,
  expandedId,
  setExpandedId,
  collapsed,
  setCollapsed,
  showAddForm,
  setShowAddForm,
  horizon,
  onHorizonChange,
  scheduler,
  saving,
  onAddFromSearch,
  onRemove,
  onUpdateTarget,
  onTriggerTarget,
  onSave,
  onToggleScheduler,
  onRefreshAll,
}: {
  targets: ApplicationAnalysisTarget[]
  filteredTargets: ApplicationAnalysisTarget[]
  searchKeyword: string
  setSearchKeyword: (value: string) => void
  selectedId: string | null
  setSelectedId: (id: string) => void
  expandedId: string | null
  setExpandedId: React.Dispatch<React.SetStateAction<string | null>>
  collapsed: boolean
  setCollapsed: React.Dispatch<React.SetStateAction<boolean>>
  showAddForm: boolean
  setShowAddForm: React.Dispatch<React.SetStateAction<boolean>>
  horizon: Record<string, number>
  onHorizonChange: (patch: HorizonPatch) => void
  scheduler: ApplicationAnalysisSchedulerStatus | null
  saving: boolean
  onAddFromSearch: (item: StockSearchItem) => void
  onRemove: (id: string) => void
  onUpdateTarget: (id: string, patch: Partial<ApplicationAnalysisTarget>) => void
  onTriggerTarget: (targetId: string) => void
  onSave: () => void
  onToggleScheduler: () => void
  onRefreshAll: () => void
}) {
  return (
    <Card className="rounded-3xl border-slate-200 bg-white shadow-[0_16px_46px_rgba(15,23,42,0.06)]">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">分析目标</CardTitle>
            <CardDescription>参考 reference/application-analysis/targets.json</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button className="rounded-xl" size="sm" variant="outline" onClick={() => setShowAddForm((value) => !value)}>
              <Plus className="mr-1 size-3.5" />新增
            </Button>
            <Button
              className="rounded-xl"
              size="icon-sm"
              variant="ghost"
              onClick={() => setCollapsed((value) => !value)}
              aria-label={collapsed ? "展开分析目标" : "折叠分析目标"}
            >
              {collapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      {!collapsed ? (
        <CardContent className="space-y-3">
          {showAddForm ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
              <SymbolSearch
                onSelect={onAddFromSearch}
                knownIds={targets.map((item) => item.id)}
              />
            </div>
          ) : null}
          <div className="space-y-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchKeyword}
                onChange={(event) => setSearchKeyword(event.target.value)}
                placeholder="搜索目标 · 名称 / 代码 / 标签"
                className="w-full rounded-xl border border-slate-200 bg-white pl-7 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              />
            </div>
            <AnimatedList
              items={filteredTargets}
              selectedIndex={filteredTargets.findIndex((item) => item.id === selectedId)}
              onItemSelect={(_item, index) => {
                const target = filteredTargets[index]
                if (!target) return
                setSelectedId(target.id)
                setExpandedId((current) => (current === target.id ? null : target.id))
              }}
              renderItem={(item, index) => {
                const target = item as ApplicationAnalysisTarget
                if (!target?.id) return null
                const isExpanded = expandedId === target.id
                const isSelected = target.id === selectedId
                return (
                  <div
                    className={`rounded-2xl border transition ${
                      isSelected ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white hover:border-slate-400"
                    }`}
                  >
                    <div className="flex w-full items-center justify-between gap-2 px-3 py-3 text-left">
                      <div className="flex min-w-0 items-center gap-2">
                        {isExpanded ? <ChevronDown className="size-3.5 text-slate-500" /> : <ChevronRight className="size-3.5 text-slate-500" />}
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                            <span className="truncate">{target.name}</span>
                            <span className="text-slate-400">· {target.symbol}</span>
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                            <Clock className="size-3" />每 {target.interval_minutes} 分钟
                            {target.enabled ? <Badge className="rounded-full border-emerald-200 bg-emerald-50 text-emerald-700" variant="outline">启用</Badge> : <Badge className="rounded-full border-slate-200 bg-slate-100 text-slate-500" variant="outline">停用</Badge>}
                            {target.last_updated_at ? <span>· 最近 {new Date(target.last_updated_at).toLocaleString()}</span> : null}
                          </div>
                        </div>
                      </div>
                      <Badge className="rounded-full border-slate-200 bg-white text-slate-700" variant="outline">{target.target_type}</Badge>
                    </div>
                    {isExpanded ? (
                      <div className="space-y-3 border-t border-slate-100 bg-slate-50/60 px-3 py-3" onClick={(event) => event.stopPropagation()}>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                            调整
                            <Select value={target.adjust} onValueChange={(value) => onUpdateTarget(target.id, { adjust: value })}>
                              <SelectTrigger className="h-7 w-20"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="qfq">前复权</SelectItem>
                                <SelectItem value="none">不复权</SelectItem>
                                <SelectItem value="hfq">后复权</SelectItem>
                              </SelectContent>
                            </Select>
                          </label>
                          <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                            周期
                            <Select
                              value={target.interval_minutes.toString()}
                              onValueChange={(value) => onUpdateTarget(target.id, { interval_minutes: Number(value) })}
                            >
                              <SelectTrigger className="h-7 w-24"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="15">15 分钟</SelectItem>
                                <SelectItem value="30">30 分钟</SelectItem>
                                <SelectItem value="60">1 小时</SelectItem>
                                <SelectItem value="120">2 小时</SelectItem>
                                <SelectItem value="240">4 小时</SelectItem>
                                <SelectItem value="1440">1 天</SelectItem>
                              </SelectContent>
                            </Select>
                          </label>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <Button size="sm" variant="outline" className="rounded-xl" onClick={() => onUpdateTarget(target.id, { enabled: !target.enabled })}>
                            {target.enabled ? "停用" : "启用"}
                          </Button>
                          <Button size="sm" variant="outline" className="rounded-xl" onClick={() => onTriggerTarget(target.id)}>
                            <RefreshCw className="mr-1 size-3.5" />立即刷新
                          </Button>
                          <Button size="sm" variant="ghost" className="rounded-xl text-slate-500" onClick={() => onRemove(target.id)}>
                            <Trash2 className="mr-1 size-3.5" />删除
                          </Button>
                        </div>
                      </div>
                    ) : null}
                    <div className="sr-only">{index}</div>
                  </div>
                )
              }}
              emptyMessage={targets.length === 0 ? "还没有目标，点击右上角新增。" : "没有匹配的目标。"}
              maxHeight="max-h-[60vh]"
              className=""
              itemClassName=""
            />
          </div>
          <div className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="text-xs font-semibold text-slate-600">数据范围（horizon）</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                天数<input
                  type="number"
                  min={30}
                  value={horizon.days}
                  onChange={(event) => onHorizonChange({ days: Number(event.target.value) || 120 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                段数<input
                  type="number"
                  min={1}
                  value={horizon.segments}
                  onChange={(event) => onHorizonChange({ segments: Number(event.target.value) || 4 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                月 K<input
                  type="number"
                  min={1}
                  value={horizon.monthly_keep}
                  onChange={(event) => onHorizonChange({ monthly_keep: Number(event.target.value) || 6 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                周 K<input
                  type="number"
                  min={1}
                  value={horizon.weekly_keep}
                  onChange={(event) => onHorizonChange({ weekly_keep: Number(event.target.value) || 12 })}
                  className="w-16 rounded-md border border-slate-200 px-1 text-right"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button className="rounded-xl" size="sm" disabled={saving} onClick={onSave}>
                <Save className="mr-1 size-3.5" />{saving ? "保存中" : "保存配置"}
              </Button>
              <Button
                className="rounded-xl"
                size="sm"
                variant={scheduler?.running ? "destructive" : "default"}
                onClick={onToggleScheduler}
              >
                {scheduler?.running ? "停止调度" : "启动调度"}
              </Button>
              <Button className="rounded-xl" size="sm" variant="outline" onClick={onRefreshAll}>
                全部刷新
              </Button>
            </div>
            <div className="text-xs text-slate-500">
              {scheduler
                ? `调度器 ${scheduler.running ? "运行中" : "已停止"} · 累计 ${scheduler.runs_count ?? 0} 次 · 启用 ${scheduler.enabled_target_count ?? 0}/${scheduler.total_target_count ?? 0}`
                : "调度器状态未知"}
            </div>
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}
