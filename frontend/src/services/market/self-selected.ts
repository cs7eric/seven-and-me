import { cynexusResult } from "@/services/common/cynexus-result"
import { fetchWithRetry } from "@/services/common/http"
import { SERVICE_PREFIX } from "@/services/common/service-prefix"

export interface SelfSelectedGroup {
  id: string
  name: string
  description?: string | null
  color?: string
  list_kind?: string
  sort_order?: number
  created_at: string
  updated_at: string
}

export interface SelfSelectedItem {
  id: string
  group_id: string
  symbol: string
  market?: string | null
  name?: string | null
  notes?: string | null
  target_type?: "stock" | "hk_stock" | "etf" | "index" | "other"
  source_type?: "manual" | "search" | "imported"
  sort_order?: number
  created_at: string
  updated_at: string
}

export interface SelfSelectedGroupListResponse {
  ok: boolean
  items: SelfSelectedGroup[]
  count: number
  error?: string
}

export interface SelfSelectedGroupActionResponse {
  ok: boolean
  item?: SelfSelectedGroup
  group_id?: string
  error?: string
}

export interface SelfSelectedItemListResponse {
  ok: boolean
  items: SelfSelectedItem[]
  count: number
  group_id?: string | null
  error?: string
}

export interface SelfSelectedItemActionResponse {
  ok: boolean
  item?: SelfSelectedItem
  item_id?: string
  error?: string
}

interface JavaSelfSelectedListDTO {
  id: string
  legacyKey?: string | null
  name?: string | null
  description?: string | null
  color?: string | null
  listKind?: string | null
  status?: string | null
  sortOrder?: number | null
  createdAt?: string | null
  updatedAt?: string | null
  deletedAt?: string | null
}

interface JavaSelfSelectedListItemDTO {
  id: string
  legacyKey?: string | null
  listId: string
  symbol?: string | null
  market?: string | null
  name?: string | null
  notes?: string | null
  targetType?: "stock" | "hk_stock" | "etf" | "index" | "other" | null
  sourceType?: "manual" | "search" | "imported" | null
  status?: string | null
  sortOrder?: number | null
  createdAt?: string | null
  updatedAt?: string | null
  deletedAt?: string | null
}

function toSelfSelectedGroup(dto: JavaSelfSelectedListDTO): SelfSelectedGroup {
  const now = new Date().toISOString()
  return {
    id: String(dto.id),
    name: dto.name || "",
    description: dto.description ?? null,
    color: dto.color || "blue",
    list_kind: dto.listKind || "manual",
    sort_order: dto.sortOrder ?? 0,
    created_at: dto.createdAt || now,
    updated_at: dto.updatedAt || dto.createdAt || now,
  }
}

function toSelfSelectedItem(dto: JavaSelfSelectedListItemDTO): SelfSelectedItem {
  const now = new Date().toISOString()
  return {
    id: String(dto.id),
    group_id: String(dto.listId),
    symbol: dto.symbol || "",
    market: dto.market ?? null,
    name: dto.name ?? null,
    notes: dto.notes ?? null,
    target_type: dto.targetType || "stock",
    source_type: dto.sourceType || "manual",
    sort_order: dto.sortOrder ?? 0,
    created_at: dto.createdAt || now,
    updated_at: dto.updatedAt || dto.createdAt || now,
  }
}

function toJavaListPayload(payload: {
  id?: string
  name?: string
  description?: string | null
  color?: string | null
  sort_order?: number
}): Partial<JavaSelfSelectedListDTO> & { id?: string } {
  const value: Partial<JavaSelfSelectedListDTO> & { id?: string; extra?: string } = {
    id: payload.id,
    name: payload.name,
    description: payload.description,
    color: payload.color ?? undefined,
    sortOrder: payload.sort_order,
  }
  if (!payload.id) {
    value.color = payload.color || "blue"
    value.listKind = "manual"
    value.status = "active"
    value.sortOrder = payload.sort_order ?? 0
    value.extra = "{}"
  }
  return value
}

function toJavaItemPayload(payload: {
  id?: string
  group_id?: string
  symbol?: string
  market?: string | null
  name?: string | null
  notes?: string | null
  target_type?: "stock" | "hk_stock" | "etf" | "index" | "other"
  sort_order?: number
}): Partial<JavaSelfSelectedListItemDTO> & { id?: string; listId?: string; extra: string } {
  const value: Partial<JavaSelfSelectedListItemDTO> & { id?: string; listId?: string; extra?: string } = {
    id: payload.id,
  }
  if (payload.group_id !== undefined) value.listId = payload.group_id
  if (payload.symbol !== undefined) value.symbol = payload.symbol.trim().toUpperCase()
  if ("market" in payload) value.market = payload.market || null
  if ("name" in payload) value.name = payload.name || null
  if ("notes" in payload) value.notes = payload.notes || null
  if (payload.target_type) value.targetType = payload.target_type
  if (payload.sort_order !== undefined) value.sortOrder = payload.sort_order
  if (!payload.id) {
    value.targetType = payload.target_type || "stock"
    value.sourceType = "manual"
    value.status = "active"
    value.sortOrder = payload.sort_order ?? 0
    value.extra = "{}"
  }
  return value as Partial<JavaSelfSelectedListItemDTO> & { id?: string; listId?: string; extra: string }
}

async function getSelfSelectedGroup(groupId: string): Promise<SelfSelectedGroup> {
  const dto = await cynexusResult<JavaSelfSelectedListDTO>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-lists/${encodeURIComponent(groupId)}`, { cache: "no-store" }),
  )
  return toSelfSelectedGroup(dto)
}

async function getSelfSelectedItem(itemId: string): Promise<SelfSelectedItem> {
  const dto = await cynexusResult<JavaSelfSelectedListItemDTO>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-list-items/${encodeURIComponent(itemId)}`, { cache: "no-store" }),
  )
  return toSelfSelectedItem(dto)
}

export async function fetchSelfSelectedGroups(): Promise<SelfSelectedGroupListResponse> {
  const items = await cynexusResult<JavaSelfSelectedListDTO[]>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-lists`, { cache: "no-store" }),
  )
  const groups = (items || [])
    .filter((item) => !item.deletedAt && item.status !== "disabled")
    .map(toSelfSelectedGroup)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  return { ok: true, items: groups, count: groups.length }
}

export async function createSelfSelectedGroup(
  payload: { name: string; description?: string; color?: string },
): Promise<SelfSelectedGroupActionResponse> {
  const id = await cynexusResult<string>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-lists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaListPayload(payload)),
    }),
  )
  return { ok: true, group_id: String(id), item: await getSelfSelectedGroup(String(id)) }
}

export async function updateSelfSelectedGroup(
  groupId: string,
  payload: Partial<Pick<SelfSelectedGroup, "name" | "description" | "color" | "sort_order">>,
): Promise<SelfSelectedGroupActionResponse> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-lists`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaListPayload({ id: groupId, ...payload })),
    }),
  )
  return { ok: true, group_id: groupId, item: await getSelfSelectedGroup(groupId) }
}

export async function deleteSelfSelectedGroup(groupId: string): Promise<SelfSelectedGroupActionResponse> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-lists/${encodeURIComponent(groupId)}`, {
      method: "DELETE",
    }),
  )
  return { ok: true, group_id: groupId }
}

export async function fetchSelfSelectedItems(
  groupId?: string,
): Promise<SelfSelectedItemListResponse> {
  const items = await cynexusResult<JavaSelfSelectedListItemDTO[]>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-list-items`, { cache: "no-store" }),
  )
  const mapped = (items || [])
    .filter((item) => !item.deletedAt && item.status !== "disabled")
    .map(toSelfSelectedItem)
    .filter((item) => !groupId || item.group_id === groupId)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  return { ok: true, items: mapped, count: mapped.length, group_id: groupId || null }
}

export async function createSelfSelectedItem(
  payload: {
    group_id: string
    symbol: string
    market?: string
    name?: string
    notes?: string
    target_type?: "stock" | "hk_stock" | "etf" | "index" | "other"
  },
): Promise<SelfSelectedItemActionResponse> {
  const id = await cynexusResult<string>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-list-items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaItemPayload(payload)),
    }),
  )
  return { ok: true, item_id: String(id), item: await getSelfSelectedItem(String(id)) }
}

export async function updateSelfSelectedItem(
  itemId: string,
  payload: Partial<Pick<SelfSelectedItem, "group_id" | "symbol" | "market" | "name" | "notes" | "target_type" | "sort_order">>,
): Promise<SelfSelectedItemActionResponse> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-list-items`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaItemPayload({ id: itemId, ...payload })),
    }),
  )
  return { ok: true, item_id: itemId, item: await getSelfSelectedItem(itemId) }
}

export async function deleteSelfSelectedItem(itemId: string): Promise<SelfSelectedItemActionResponse> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.marketData}/self-selected-list-items/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    }),
  )
  return { ok: true, item_id: itemId }
}

