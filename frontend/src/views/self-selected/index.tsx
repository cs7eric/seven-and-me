import { useCallback, useEffect, useMemo, useState } from "react"
import { Star, Trash2 } from "lucide-react"
import { notification } from "@/components/ui/notification"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import DogLoader from "@/components/loader/dog-loader"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  type SelfSelectedGroup,
  type SelfSelectedItem,
  type StockSectorsResponse,
  createSelfSelectedGroup,
  createSelfSelectedItem,
  deleteSelfSelectedGroup,
  deleteSelfSelectedItem,
  fetchApplicationAnalysisTargets,
  fetchSelfSelectedGroups,
  fetchSelfSelectedItems,
  fetchStockSectors,
  updateSelfSelectedItem,
} from "@/lib/api"

import { AddItemTile } from "./components/add-item-tile"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { CreateGroupDialog } from "./components/create-group-dialog"
import { CreateItemDialog } from "./components/create-item-dialog"
import { EditItemNotesDialog } from "./components/edit-item-notes-dialog"
import { ItemRow } from "./components/item-row"
import { getGroupColorClasses, type GroupColorKey } from "./lib/constants"

const REFRESH_INTERVAL_MS = 8_000

function isSystemTargetGroup(group: Pick<SelfSelectedGroup, "name" | "list_kind"> | null | undefined) {
  return (group?.list_kind || "").toLowerCase() === "system" && (group?.name || "").trim().toLowerCase() === "target"
}

export default function SelfSelectedPage() {
  const [groups, setGroups] = useState<SelfSelectedGroup[]>([])
  const [itemsByGroup, setItemsByGroup] = useState<Record<string, SelfSelectedItem[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const [pendingGroup, setPendingGroup] = useState<string | null>(null)
  const [pendingItem, setPendingItem] = useState<string | null>(null)
  // 当前正在打开「加自选」弹窗的 group（同时只允许一个对话框打开）
  const [addDialogGroupId, setAddDialogGroupId] = useState<string | null>(null)
  // 当前正在打开「删分类」确认弹窗的 group
  const [confirmDeleteGroupId, setConfirmDeleteGroupId] = useState<string | null>(null)
  const [editingItem, setEditingItem] = useState<SelfSelectedItem | null>(null)
  // 已加入「应用分析」的标的 symbol 集合（用于在 item 卡上打「已加入」徽章）
  const [inAnalysisSymbols, setInAnalysisSymbols] = useState<Set<string>>(new Set())
  // active group 股票的 F10 板块归属缓存，用于卡片展示行业 / 概念 / 风格
  const [sectorsBySymbol, setSectorsBySymbol] = useState<Record<string, StockSectorsResponse>>({})
  const [loadingSectorSymbols, setLoadingSectorSymbols] = useState<Set<string>>(new Set())
  const targetGroup = useMemo(() => groups.find((group) => isSystemTargetGroup(group)) ?? null, [groups])

  const loadAll = useCallback(async (withSpinner = false) => {
    if (withSpinner) setLoading(true)
    try {
      const [groupsRes, itemsRes] = await Promise.all([
        fetchSelfSelectedGroups(),
        fetchSelfSelectedItems(),
      ])
      if (!groupsRes.ok) {
        setError(groupsRes.error || "获取分类失败")
        if (withSpinner) {
          notification.danger({
            title: "获取分类失败",
            description: groupsRes.error || "请检查后端服务",
          })
        }
        return
      }
      setGroups(groupsRes.items)
      const grouped: Record<string, SelfSelectedItem[]> = {}
      for (const it of itemsRes.items) {
        if (!grouped[it.group_id]) grouped[it.group_id] = []
        grouped[it.group_id].push(it)
      }
      setItemsByGroup(grouped)
      setError(null)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "未知错误"
      setError(msg)
      if (withSpinner) {
        notification.danger({ title: "加载自选股失败", description: msg })
      }
    } finally {
      if (withSpinner) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadAll(true)
    const timer = window.setInterval(() => {
      void loadAll(false)
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loadAll])

  // 拉一次应用分析 targets，用于在 item 卡上打「已加入」徽章
  const loadAnalysisSymbols = useCallback(async () => {
    try {
      const res = await fetchApplicationAnalysisTargets()
      const set = new Set<string>(
        (res.items || []).map((it) => (it.symbol || "").toUpperCase()).filter(Boolean),
      )
      setInAnalysisSymbols(set)
    } catch {
      // 静默：徽章只是辅助，挂了不挡其它功能
    }
  }, [])
  useEffect(() => {
    void loadAnalysisSymbols()
    const timer = window.setInterval(() => {
      void loadAnalysisSymbols()
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loadAnalysisSymbols])

  useEffect(() => {
    if (!activeGroupId && groups.length > 0) {
      setActiveGroupId(groups[0].id)
    }
  }, [activeGroupId, groups])

  // ---------- actions ----------

  const handleCreateGroup = useCallback(
    async (payload: { name: string; color: GroupColorKey; description?: string }) => {
      const res = await createSelfSelectedGroup(payload)
      if (!res.ok || !res.item) {
        throw new Error(res.error || "创建分类失败")
      }
      notification.success({ title: "分类已创建", description: res.item.name })
      setActiveGroupId(res.item.id)
      await loadAll(false)
    },
    [loadAll],
  )

  const handleDeleteGroup = useCallback(
    async (groupId: string) => {
      const target = groups.find((g) => g.id === groupId)
      const name = target?.name ?? groupId
      setPendingGroup(groupId)
      try {
        const res = await deleteSelfSelectedGroup(groupId)
        if (!res.ok) {
          notification.danger({
            title: "删除分类失败",
            description: res.error || "请查看后端日志",
          })
          return
        }
        notification.success({ title: "分类已删除", description: name })
        if (activeGroupId === groupId) {
          setActiveGroupId(null)
        }
        await loadAll(false)
      } finally {
        setPendingGroup(null)
      }
    },
    [activeGroupId, groups, loadAll],
  )

  const handleCreateItem = useCallback(
    async (
      groupId: string,
      payload: {
        symbol: string
        market?: string
        name?: string
        notes?: string
        target_type?: "stock" | "hk_stock" | "etf" | "index" | "other"
      },
    ) => {
      const res = await createSelfSelectedItem({ group_id: groupId, ...payload })
      if (!res.ok || !res.item) {
        throw new Error(res.error || "加入自选失败")
      }
      notification.success({
        title: "已加入自选",
        description: `${res.item.symbol} ${res.item.name ?? ""}`.trim(),
      })
      await loadAll(false)
    },
    [loadAll],
  )

  const handleDeleteItem = useCallback(
    async (itemId: string) => {
      setPendingItem(itemId)
      try {
        const res = await deleteSelfSelectedItem(itemId)
        if (!res.ok) {
          notification.danger({
            title: "删除失败",
            description: res.error || "请查看后端日志",
          })
          return
        }
        notification.success({ title: "已移除" })
        await loadAll(false)
      } finally {
        setPendingItem(null)
      }
    },
    [loadAll],
  )

  const handleEditItemNotes = useCallback(
    async (payload: { notes?: string }) => {
      if (!editingItem) return
      setPendingItem(editingItem.id)
      try {
        const res = await updateSelfSelectedItem(editingItem.id, { notes: payload.notes })
        if (!res.ok) {
          throw new Error(res.error || "更新备注失败")
        }
        notification.success({ title: "备注已更新" })
        await loadAll(false)
      } finally {
        setPendingItem(null)
      }
    },
    [editingItem, loadAll],
  )

  const handleAddToTargetGroup = useCallback(
    async (item: SelfSelectedItem) => {
      if (!targetGroup) {
        notification.danger({
          title: "未找到 target 分组",
          description: "请检查系统分组是否已初始化",
        })
        return
      }
      const res = await createSelfSelectedItem({
        group_id: targetGroup.id,
        symbol: item.symbol,
        market: item.market || undefined,
        name: item.name || undefined,
        notes: item.notes || undefined,
        target_type: item.target_type,
      })
      if (!res.ok || !res.item) {
        throw new Error(res.error || "加入 target 分组失败")
      }
      notification.success({
        title: "已加入 target 分组",
        description: `${item.symbol} ${item.name ?? ""}`.trim(),
      })
      await Promise.all([loadAll(false), loadAnalysisSymbols()])
    },
    [loadAll, loadAnalysisSymbols, targetGroup],
  )

  const totalItems = useMemo(
    () => Object.values(itemsByGroup).reduce((acc, arr) => acc + arr.length, 0),
    [itemsByGroup],
  )

  useEffect(() => {
    const activeItems = activeGroupId ? (itemsByGroup[activeGroupId] ?? []) : []
    const candidates = activeItems.filter((it) => {
      const symbol = (it.symbol || "").trim()
      const market = (it.market || "").toUpperCase()
      return symbol.length === 6 && (market === "SH" || market === "SZ" || market === "")
    })
    const missingSymbols = Array.from(
      new Set(
        candidates
          .map((it) => (it.symbol || "").trim())
          .filter((symbol) => symbol && !sectorsBySymbol[symbol]),
      ),
    )
    if (missingSymbols.length === 0) return

    let active = true
    setLoadingSectorSymbols((prev) => new Set([...prev, ...missingSymbols]))
    Promise.allSettled(missingSymbols.map((symbol) => fetchStockSectors(symbol))).then((results) => {
      if (!active) return
      const next: Record<string, StockSectorsResponse> = {}
      for (let i = 0; i < results.length; i += 1) {
        const result = results[i]
        const symbol = missingSymbols[i]
        if (result.status === "fulfilled") {
          next[symbol] = result.value
        }
      }
      if (Object.keys(next).length > 0) {
        setSectorsBySymbol((prev) => ({ ...prev, ...next }))
      }
      setLoadingSectorSymbols((prev) => {
        const nextSet = new Set(prev)
        for (const symbol of missingSymbols) nextSet.delete(symbol)
        return nextSet
      })
    })
    return () => {
      active = false
    }
  }, [activeGroupId, itemsByGroup, sectorsBySymbol])

  return (
    <WorkspaceShell sectionLabel="Stock Overview" pageTitle="Self-Selected">
      {/* 顶部 header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
            <Star className="size-3.5" />
            Self-Selected
          </div>
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              Self-Selected
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
              自选股模块：自己创建分类作为 tab，往里面加入股票。运行时数据现在统一持久化到
              PostgreSQL，并通过后端 API 提供读写能力。
              {groups.length > 0 ? (
                <>
                  共 <span className="font-medium text-foreground">{groups.length}</span> 个分类、
                  <span className="font-medium text-foreground"> {totalItems}</span> 只自选股。
                </>
              ) : null}
            </p>
          </div>
        </div>
        <CreateGroupDialog onCreate={handleCreateGroup} />
      </div>

      {error ? (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {/* 删分类的确认弹窗（受 confirmDeleteGroupId 控制） */}
      <ConfirmDialog
        open={confirmDeleteGroupId !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDeleteGroupId(null)
        }}
        title="删除分类"
        description={
          confirmDeleteGroupId
            ? (() => {
                const target = groups.find((g) => g.id === confirmDeleteGroupId)
                return (
                  <>
                    确定要删除分类{" "}
                    <span className="font-semibold text-foreground">
                      「{target?.name ?? confirmDeleteGroupId}」
                    </span>
                    吗？该分类下的所有自选股也会被一起删除，此操作无法撤销。
                  </>
                )
              })()
            : null
        }
        confirmText="删除分类"
        destructive
        pending={pendingGroup === confirmDeleteGroupId}
        onConfirm={async () => {
          if (confirmDeleteGroupId) {
            await handleDeleteGroup(confirmDeleteGroupId)
          }
        }}
      />

      <EditItemNotesDialog
        open={editingItem !== null}
        item={editingItem}
        pending={pendingItem === editingItem?.id}
        onOpenChange={(open) => {
          if (!open) setEditingItem(null)
        }}
        onSubmit={handleEditItemNotes}
      />

      {loading && groups.length === 0 ? (
        <DogLoader overlay size={25} label="正在加载自选分类..." />
      ) : groups.length === 0 ? (
        <EmptyState onCreate={handleCreateGroup} />
      ) : (
        <Tabs
          value={activeGroupId ?? undefined}
          onValueChange={setActiveGroupId}
          className="w-full"
        >
          <TabsList className="inline-flex h-fit w-fit max-w-full flex-wrap items-center gap-2 rounded-2xl border border-border/30 bg-muted/35 p-2">
            {groups.map((g) => {
              const colors = getGroupColorClasses(g.color)
              const count = itemsByGroup[g.id]?.length ?? 0
              return (
                <TabsTrigger
                  key={g.id}
                  value={g.id}
                  className="inline-flex h-7 min-w-[120px] items-center justify-center gap-1.5 rounded-md border border-transparent px-2.5 py-1 text-xs font-medium transition-all data-[state=active]:border-border/50 data-[state=active]:bg-background data-[state=active]:shadow-sm"
                >
                  <span className={`size-2.5 shrink-0 rounded-full ${colors.text.replace("text-", "bg-")}`} />
                  <span className="truncate">{g.name}</span>
                  <Badge variant="secondary" className="ml-1 shrink-0 px-1.5 py-0 text-[10px]">
                    {count}
                  </Badge>
                </TabsTrigger>
              )
            })}
          </TabsList>

          {groups.map((g) => {
            const items = itemsByGroup[g.id] ?? []
            const colors = getGroupColorClasses(g.color)
            const isTargetGroup = isSystemTargetGroup(g)
            return (
              <TabsContent key={g.id} value={g.id} className="mt-4 space-y-3">
                {/* 简化版 group header：只放描述 + 删分类按钮 */}
                <div className="flex items-center justify-between gap-2 rounded-xl bg-muted/30 px-3 py-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    {isTargetGroup ? (
                      <Badge variant="secondary" className="shrink-0 bg-amber-500/12 text-amber-700">
                        系统 target
                      </Badge>
                    ) : null}
                    <p className="truncate text-xs text-muted-foreground">
                      {isTargetGroup
                        ? "Application Analysis 联动分组：这里的增删改会同步到 targets，系统分组不可删除。"
                        : g.description || "点击下方「+ 加入自选」开始添加"}
                    </p>
                  </div>
                  {!isTargetGroup ? (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="size-7 rounded-lg text-muted-foreground hover:text-destructive"
                      onClick={() => setConfirmDeleteGroupId(g.id)}
                      disabled={pendingGroup === g.id}
                      aria-label="delete group"
                      title="删除分类"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  ) : null}
                </div>

                {/* items 网格：每个 item 一张卡 + 末尾加号 tile */}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {items.map((it) => (
                    <ItemRow
                      key={it.id}
                      item={it}
                      pending={pendingItem === it.id}
                      systemGroup={isTargetGroup}
                      sectors={sectorsBySymbol[(it.symbol || "").trim()] ?? null}
                      sectorsLoading={loadingSectorSymbols.has((it.symbol || "").trim())}
                      inAnalysis={inAnalysisSymbols.has((it.symbol || "").toUpperCase())}
                      canAddToTarget={!isTargetGroup && !inAnalysisSymbols.has((it.symbol || "").toUpperCase())}
                      onAddToTarget={handleAddToTargetGroup}
                      onDelete={handleDeleteItem}
                      onEdit={setEditingItem}
                    />
                  ))}
                  <AddItemTile
                    onClick={() => setAddDialogGroupId(g.id)}
                    accentClass={colors.border}
                    label={isTargetGroup ? "加入 target 分组" : "加入自选"}
                  />
                </div>

                <CreateItemDialog
                  groupName={g.name}
                  open={addDialogGroupId === g.id}
                  onOpenChange={(open) => setAddDialogGroupId(open ? g.id : null)}
                  onCreate={(payload) => handleCreateItem(g.id, payload)}
                />
              </TabsContent>
            )
          })}
        </Tabs>
      )}
    </WorkspaceShell>
  )
}

// ------------------------------------------------------------------
// 子组件
// ------------------------------------------------------------------

function EmptyState({
  onCreate,
}: {
  onCreate: (payload: { name: string; color: GroupColorKey; description?: string }) => Promise<void>
}) {
  return (
    <div className="rounded-3xl border border-dashed border-border/40 bg-muted/20 p-10 text-center">
      <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-background/80 text-muted-foreground shadow-sm shadow-black/5">
        <Star className="size-5" />
      </div>
      <h3 className="mt-4 text-base font-semibold text-foreground">还没有自选分类</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        创建一个分类（如「长线持仓」「短线观察」），然后往里面加入股票。分类会作为 tab 展示在页面顶部。
      </p>
      <div className="mt-5 inline-flex">
        <CreateGroupDialog onCreate={onCreate} />
      </div>
    </div>
  )
}
