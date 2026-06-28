import { cynexusResult } from "@/services/common/cynexus-result"
import { fetchWithRetry } from "@/services/common/http"
import { SERVICE_PREFIX } from "@/services/common/service-prefix"

export interface AiCapability {
  code: string
  label: string
}

export interface AiProviderType {
  code: string
  label: string
  default_base_url: string
  default_model: string
  api_key_env: string
  group_id_env: string
}

export interface AiProviderItem {
  id: string
  code: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  models: string[]
  api_key?: string
  api_key_masked: string
  api_key_env: string
  group_id: string
  group_id_env: string
  is_enabled: boolean
  timeout_seconds: number | null
  extra: Record<string, unknown>
  remark: string
  created_at?: string | null
  updated_at?: string | null
}

export interface AiBindingItem {
  id: string
  capability: string
  label: string
  provider_id: string
  provider: AiProviderItem | null
  model_override: string
  is_enabled: boolean
  params: Record<string, unknown>
  remark: string
}

interface JavaAiProviderDTO {
  id: string
  code?: string | null
  name?: string | null
  providerType?: string | null
  baseUrl?: string | null
  defaultModel?: string | null
  apiKey?: string | null
  apiKeyMasked?: string | null
  apiKeyEnv?: string | null
  groupId?: string | null
  groupIdEnv?: string | null
  enabled?: boolean | null
  timeoutSeconds?: number | null
  extra?: string | null
  remark?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  deletedAt?: string | null
  models?: string | null
}

interface JavaAiUsageBindingDTO {
  id: string
  capability?: string | null
  label?: string | null
  providerId?: string | null
  modelOverride?: string | null
  enabled?: boolean | null
  params?: string | null
  remark?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  deletedAt?: string | null
}

const AI_CAPABILITIES: AiCapability[] = [
  { code: "text_polish", label: "MP4 text polish" },
  { code: "text_summary", label: "MP4 summary" },
  { code: "post_metadata", label: "Markdown metadata" },
  { code: "mp4_qa", label: "MP4 Ask AI" },
  { code: "application_analysis", label: "Stock application analysis" },
  { code: "application_recent30", label: "Recent 30-day analysis" },
  { code: "auction_analysis", label: "Auction AI analysis" },
]

const AI_PROVIDER_TYPES: AiProviderType[] = [
  {
    code: "minimax",
    label: "MiniMax",
    default_base_url: "https://api.minimaxi.com",
    default_model: "MiniMax-M2.5",
    api_key_env: "MINIMAX_API_KEY",
    group_id_env: "MINIMAX_GROUP_ID",
  },
  {
    code: "openai_compatible",
    label: "OpenAI compatible",
    default_base_url: "https://api.openai.com",
    default_model: "",
    api_key_env: "OPENAI_API_KEY",
    group_id_env: "",
  },
  {
    code: "deepseek",
    label: "DeepSeek",
    default_base_url: "https://api.deepseek.com",
    default_model: "deepseek-v4-flash",
    api_key_env: "DEEPSEEK_API_KEY",
    group_id_env: "",
  },
  {
    code: "anthropic_compatible",
    label: "Anthropic compatible",
    default_base_url: "",
    default_model: "",
    api_key_env: "",
    group_id_env: "",
  },
]

function parseJsonObject(value?: string | null): Record<string, unknown> {
  if (!value) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function parseJsonStringList(value?: string | null): string[] {
  if (!value) return []
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.map((item) => String(item).trim()).filter(Boolean) : []
  } catch {
    return []
  }
}

function maskSecret(value?: string | null): string {
  if (!value) return ""
  if (value.length <= 8) return "****"
  return `${value.slice(0, 4)}...${value.slice(-4)}`
}

function toAiProviderItem(dto: JavaAiProviderDTO): AiProviderItem {
  return {
    id: String(dto.id),
    code: dto.code || "",
    name: dto.name || "",
    provider_type: dto.providerType || "",
    base_url: dto.baseUrl || "",
    default_model: dto.defaultModel || "",
    models: parseJsonStringList(dto.models),
    api_key: "",
    api_key_masked: dto.apiKeyMasked || maskSecret(dto.apiKey),
    api_key_env: dto.apiKeyEnv || "",
    group_id: dto.groupId || "",
    group_id_env: dto.groupIdEnv || "",
    is_enabled: dto.enabled ?? true,
    timeout_seconds: dto.timeoutSeconds ?? null,
    extra: parseJsonObject(dto.extra),
    remark: dto.remark || "",
    created_at: dto.createdAt || null,
    updated_at: dto.updatedAt || null,
  }
}

function toJavaAiProviderPayload(payload: Partial<AiProviderItem>): Partial<JavaAiProviderDTO> {
  const value: Partial<JavaAiProviderDTO> = {
    id: payload.id,
    code: payload.code,
    name: payload.name,
    providerType: payload.provider_type,
    baseUrl: payload.base_url,
    defaultModel: payload.default_model,
    apiKeyEnv: payload.api_key_env,
    groupId: payload.group_id,
    groupIdEnv: payload.group_id_env,
    enabled: payload.is_enabled,
    timeoutSeconds: payload.timeout_seconds,
    extra: JSON.stringify(payload.extra || {}),
    remark: payload.remark,
    models: JSON.stringify(payload.models || []),
  }
  if (payload.api_key && payload.api_key.trim()) {
    value.apiKey = payload.api_key.trim()
  }
  return value
}

function toAiBindingItem(
  dto: JavaAiUsageBindingDTO,
  providerById: Map<string, AiProviderItem> = new Map(),
): AiBindingItem {
  const providerId = dto.providerId ? String(dto.providerId) : ""
  return {
    id: String(dto.id),
    capability: dto.capability || "",
    label: dto.label || dto.capability || "",
    provider_id: providerId,
    provider: providerById.get(providerId) || null,
    model_override: dto.modelOverride || "",
    is_enabled: dto.enabled ?? true,
    params: parseJsonObject(dto.params),
    remark: dto.remark || "",
  }
}

function toJavaAiBindingPayload(payload: Partial<AiBindingItem>): Partial<JavaAiUsageBindingDTO> {
  return {
    id: payload.id,
    capability: payload.capability,
    label: payload.label,
    providerId: payload.provider_id || null,
    modelOverride: payload.model_override,
    enabled: payload.is_enabled,
    params: JSON.stringify(payload.params || {}),
    remark: payload.remark,
  }
}

async function getAiProvider(id: string): Promise<AiProviderItem> {
  const dto = await cynexusResult<JavaAiProviderDTO>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/providers/${encodeURIComponent(id)}`, { cache: "no-store" }),
  )
  return toAiProviderItem(dto)
}

export async function fetchAiCapabilities(): Promise<AiCapability[]> {
  return AI_CAPABILITIES
}

export async function fetchAiProviderTypes(): Promise<AiProviderType[]> {
  return AI_PROVIDER_TYPES
}

export async function fetchAiProviders(): Promise<AiProviderItem[]> {
  const items = await cynexusResult<JavaAiProviderDTO[]>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/providers`, { cache: "no-store" }),
  )
  return (items || [])
    .filter((item) => !item.deletedAt)
    .map(toAiProviderItem)
}

export async function createAiProvider(payload: Partial<AiProviderItem>): Promise<AiProviderItem> {
  const id = await cynexusResult<string>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/providers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaAiProviderPayload(payload)),
    }),
  )
  return getAiProvider(String(id))
}

export async function updateAiProvider(id: string, payload: Partial<AiProviderItem>): Promise<AiProviderItem> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/providers`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaAiProviderPayload({ id, ...payload })),
    }),
  )
  return getAiProvider(id)
}

export async function deleteAiProvider(id: string): Promise<void> {
  await cynexusResult<boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/providers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  )
}

export async function fetchAiBindings(): Promise<AiBindingItem[]> {
  const [providers, bindings] = await Promise.all([
    fetchAiProviders(),
    cynexusResult<JavaAiUsageBindingDTO[]>(
      await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/usage-bindings`, { cache: "no-store" }),
    ),
  ])
  const providerById = new Map(providers.map((provider) => [provider.id, provider]))
  return (bindings || [])
    .filter((item) => !item.deletedAt)
    .map((item) => toAiBindingItem(item, providerById))
    .sort((a, b) => a.capability.localeCompare(b.capability))
}

export async function upsertAiBinding(payload: Partial<AiBindingItem>): Promise<AiBindingItem> {
  const existing = (await fetchAiBindings()).find((item) => item.capability === payload.capability)
  const method = existing ? "PUT" : "POST"
  const savedPayload = existing ? { ...payload, id: existing.id } : payload
  const result = await cynexusResult<string | boolean>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/usage-bindings`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toJavaAiBindingPayload(savedPayload)),
    }),
  )
  const id = existing?.id || String(result)
  const dto = await cynexusResult<JavaAiUsageBindingDTO>(
    await fetchWithRetry(`${SERVICE_PREFIX.aiConfig}/usage-bindings/${encodeURIComponent(id)}`, { cache: "no-store" }),
  )
  const providerById = new Map((await fetchAiProviders()).map((provider) => [provider.id, provider]))
  return toAiBindingItem(dto, providerById)
}

