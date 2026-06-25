import { useCallback, useEffect, useMemo, useState } from "react"
import { BrainCircuit, CheckCircle2, Database, Plus, RefreshCw, Save, Trash2 } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { notification } from "@/components/ui/notification"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { WorkspaceShell } from "@/layout/workspace-shell"
import {
  type AiBindingItem,
  type AiCapability,
  type AiProviderItem,
  type AiProviderType,
  createAiProvider,
  deleteAiProvider,
  fetchAiBindings,
  fetchAiCapabilities,
  fetchAiProviderTypes,
  fetchAiProviders,
  updateAiProvider,
  upsertAiBinding,
} from "@/lib/api"
import { cn } from "@/lib/utils"

// AI Provider frontend docs:
//   design/frontend/ai-provider.md
// Keep that document in sync when changing this settings UI, route behavior, or payload shape.

type ProviderDraft = {
  id?: string
  code: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  api_key: string
  api_key_env: string
  group_id: string
  group_id_env: string
  timeout_seconds: string
  is_enabled: boolean
  remark: string
}

const emptyDraft: ProviderDraft = {
  code: "",
  name: "",
  provider_type: "openai_compatible",
  base_url: "",
  default_model: "",
  api_key: "",
  api_key_env: "",
  group_id: "",
  group_id_env: "",
  timeout_seconds: "120",
  is_enabled: true,
  remark: "",
}

function draftFromProvider(provider: AiProviderItem): ProviderDraft {
  return {
    id: provider.id,
    code: provider.code,
    name: provider.name,
    provider_type: provider.provider_type,
    base_url: provider.base_url,
    default_model: provider.default_model,
    api_key: "",
    api_key_env: provider.api_key_env,
    group_id: provider.group_id,
    group_id_env: provider.group_id_env,
    timeout_seconds: String(provider.timeout_seconds || 120),
    is_enabled: provider.is_enabled,
    remark: provider.remark,
  }
}

export default function AiProviderSettingsPage() {
  const [providers, setProviders] = useState<AiProviderItem[]>([])
  const [providerTypes, setProviderTypes] = useState<AiProviderType[]>([])
  const [bindings, setBindings] = useState<AiBindingItem[]>([])
  const [capabilities, setCapabilities] = useState<AiCapability[]>([])
  const [draft, setDraft] = useState<ProviderDraft>(emptyDraft)
  const [selectedProviderId, setSelectedProviderId] = useState("")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const selectedProvider = useMemo(
    () => providers.find((item) => item.id === selectedProviderId) || null,
    [providers, selectedProviderId],
  )

  const reload = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const [nextCapabilities, nextProviders, nextBindings] = await Promise.all([
        fetchAiCapabilities(),
        fetchAiProviders(),
        fetchAiBindings(),
      ])
      const nextProviderTypes = await fetchAiProviderTypes()
      setCapabilities(nextCapabilities)
      setProviderTypes(nextProviderTypes)
      setProviders(nextProviders)
      setBindings(nextBindings)
      if (!selectedProviderId && nextProviders[0]) {
        setSelectedProviderId(nextProviders[0].id)
        setDraft(draftFromProvider(nextProviders[0]))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 AI Provider 设置失败")
    } finally {
      setLoading(false)
    }
  }, [selectedProviderId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [reload])

  const bindingByCapability = useMemo(() => {
    const map = new Map<string, AiBindingItem>()
    bindings.forEach((item) => map.set(item.capability, item))
    return map
  }, [bindings])

  async function handleSaveProvider() {
    if (!draft.code.trim() || !draft.name.trim()) {
      notification.danger({ title: "Provider 未保存", description: "Code 和名称不能为空" })
      return
    }
    setSaving(true)
    try {
      const payload = {
        ...draft,
        timeout_seconds: Number(draft.timeout_seconds || 120),
      }
      const saved = draft.id
        ? await updateAiProvider(draft.id, payload)
        : await createAiProvider(payload)
      notification.success({ title: "Provider 已保存", description: saved.name })
      setSelectedProviderId(saved.id)
      setDialogOpen(false)
      await reload()
    } catch (err) {
      notification.danger({ title: "Provider 保存失败", description: err instanceof Error ? err.message : "保存失败" })
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteProvider() {
    if (!draft.id) return
    setSaving(true)
    try {
      await deleteAiProvider(draft.id)
      notification.success({ title: "Provider 已删除", description: draft.name })
      setDraft(emptyDraft)
      setSelectedProviderId("")
      setDialogOpen(false)
      await reload()
    } catch (err) {
      notification.danger({ title: "删除失败", description: err instanceof Error ? err.message : "删除失败" })
    } finally {
      setSaving(false)
    }
  }

  function openCreateDialog() {
    setDialogMode("create")
    setDraft(emptyDraft)
    setDialogOpen(true)
  }

  function openEditDialog(provider: AiProviderItem) {
    setDialogMode("edit")
    setSelectedProviderId(provider.id)
    setDraft(draftFromProvider(provider))
    setDialogOpen(true)
  }

  function handleProviderTypeChange(providerTypeCode: string) {
    const providerType = providerTypes.find((item) => item.code === providerTypeCode)
    setDraft((current) => ({
      ...current,
      provider_type: providerTypeCode,
      base_url: current.base_url || providerType?.default_base_url || "",
      default_model: current.default_model || providerType?.default_model || "",
      api_key_env: current.api_key_env || providerType?.api_key_env || "",
      group_id_env: current.group_id_env || providerType?.group_id_env || "",
    }))
  }

  async function handleBindingChange(capability: AiCapability, providerId: string, modelOverride: string) {
    try {
      const saved = await upsertAiBinding({
        capability: capability.code,
        label: capability.label,
        provider_id: providerId,
        model_override: modelOverride,
        is_enabled: true,
      })
      setBindings((current) => {
        const rest = current.filter((item) => item.capability !== saved.capability)
        return [...rest, saved].sort((a, b) => a.capability.localeCompare(b.capability))
      })
      notification.success({ title: "绑定已保存", description: capability.label })
    } catch (err) {
      notification.danger({ title: "绑定保存失败", description: err instanceof Error ? err.message : "保存失败" })
    }
  }

  return (
    <WorkspaceShell>
      <div className="flex w-full flex-col gap-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <BrainCircuit className="size-4" />
              Settings
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">AI Provider</h1>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              管理模型连接和功能绑定。OpenAI-compatible endpoint 可以直接通过配置接入。
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void reload()} disabled={loading}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} />
              Refresh
            </Button>
            <Button
              variant="secondary"
              onClick={openCreateDialog}
            >
              <Plus className="size-4" />
              New provider
            </Button>
          </div>
        </div>

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>AI Provider 设置加载失败</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="space-y-4">
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Database className="size-4" />
                Provider switchboard
              </div>
              <Badge variant="secondary">{providers.length}</Badge>
            </div>
            <div className="overflow-hidden rounded-lg bg-muted/50">
              {providers.length ? (
                <div className="grid grid-cols-[minmax(180px,1.2fr)_minmax(150px,0.85fr)_minmax(160px,1fr)_100px_96px] gap-3 px-3 py-2 text-xs font-medium text-muted-foreground">
                  <div>Provider</div>
                  <div>Type</div>
                  <div>Model</div>
                  <div>Timeout</div>
                  <div className="text-right">Action</div>
                </div>
              ) : null}
              {providers.map((provider) => (
                <div
                  key={provider.id}
                  onClick={() => {
                    setSelectedProviderId(provider.id)
                    setDraft(draftFromProvider(provider))
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      setSelectedProviderId(provider.id)
                      setDraft(draftFromProvider(provider))
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  className={cn(
                    "grid w-full cursor-pointer grid-cols-[minmax(180px,1.2fr)_minmax(150px,0.85fr)_minmax(160px,1fr)_100px_96px] items-center gap-3 px-3 py-3 text-left transition hover:bg-background/70",
                    selectedProviderId === provider.id && "bg-background",
                  )}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "size-2 rounded-full",
                        provider.is_enabled ? "bg-emerald-500" : "bg-muted-foreground/30",
                      )} />
                      <span className="truncate font-medium">{provider.name}</span>
                    </div>
                    <div className="truncate pl-4 text-xs text-muted-foreground">{provider.code}</div>
                  </div>
                  <div className="truncate text-sm text-muted-foreground">{provider.provider_type}</div>
                  <div className="truncate text-sm text-muted-foreground">{provider.default_model || "no model"}</div>
                  <div className="text-sm text-muted-foreground">{provider.timeout_seconds || 120}s</div>
                  <div className="flex justify-end">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2"
                      onClick={(event) => {
                        event.stopPropagation()
                        openEditDialog(provider)
                      }}
                    >
                      Edit
                    </Button>
                  </div>
                </div>
              ))}
              {!providers.length && !loading ? (
                <div className="p-4 text-sm text-muted-foreground">
                  暂无 provider，先新建一个。
                </div>
              ) : null}
            </div>
          </section>

          <section className="rounded-xl bg-muted/50 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <CheckCircle2 className="size-4" />
                Routing matrix
              </div>
              <Badge variant="secondary">{capabilities.length}</Badge>
            </div>
            <div className="overflow-x-auto rounded-lg bg-background/70">
              <div className="grid min-w-[760px] grid-cols-[minmax(180px,1.4fr)_minmax(180px,1fr)_minmax(160px,1fr)_96px] gap-3 px-3 py-2 text-xs font-medium text-muted-foreground">
                <div>Capability</div>
                <div>Provider</div>
                <div>Model override</div>
                <div>Status</div>
              </div>
              <div className="divide-y divide-border/50">
                {capabilities.map((capability) => {
                  const binding = bindingByCapability.get(capability.code)
                  const providerId = binding?.provider_id || ""
                  return (
                    <div key={capability.code} className="grid min-w-[760px] grid-cols-[minmax(180px,1.4fr)_minmax(180px,1fr)_minmax(160px,1fr)_96px] items-center gap-3 px-3 py-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{capability.label}</div>
                        <div className="truncate text-xs text-muted-foreground">{capability.code}</div>
                      </div>
                      <Select
                        value={providerId || "none"}
                        onValueChange={(value) => void handleBindingChange(capability, value === "none" ? "" : value, binding?.model_override || "")}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">No provider</SelectItem>
                          {providers.map((provider) => (
                            <SelectItem key={provider.id} value={provider.id}>{provider.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Input
                        defaultValue={binding?.model_override || ""}
                        onBlur={(event) => void handleBindingChange(capability, providerId, event.target.value)}
                        placeholder={binding?.provider?.default_model || "provider default"}
                      />
                      <Badge variant={binding?.is_enabled ? "outline" : "secondary"}>
                        {binding?.is_enabled ? "active" : "fallback"}
                      </Badge>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>

          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogContent className="w-[calc(100vw-2rem)] sm:!max-w-[88rem] max-h-[calc(100vh-2rem)] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{dialogMode === "create" ? "New provider" : "Edit provider"}</DialogTitle>
                <DialogDescription>
                  Configure the model endpoint and credentials used by AI capabilities.
                </DialogDescription>
              </DialogHeader>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="space-y-2">
                  <Label>Code</Label>
                  <Input value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} placeholder="openai-main" />
                </div>
                <div className="space-y-2">
                  <Label>Name</Label>
                  <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="OpenAI Main" />
                </div>
                <div className="space-y-2">
                  <Label>Provider type</Label>
                  <Select value={draft.provider_type} onValueChange={handleProviderTypeChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {providerTypes.map((providerType) => (
                        <SelectItem key={providerType.code} value={providerType.code}>
                          {providerType.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Default model</Label>
                  <Input value={draft.default_model} onChange={(e) => setDraft({ ...draft, default_model: e.target.value })} placeholder="gpt-4.1-mini" />
                </div>
                <div className="space-y-2 md:col-span-2 xl:col-span-4">
                  <Label>Base URL</Label>
                  <Input value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} placeholder="https://api.openai.com" />
                </div>
                <div className="space-y-2">
                  <Label>API key env</Label>
                  <Input value={draft.api_key_env} onChange={(e) => setDraft({ ...draft, api_key_env: e.target.value })} placeholder="OPENAI_API_KEY" />
                </div>
                <div className="space-y-2">
                  <Label>API key</Label>
                  <Input
                    type="password"
                    value={draft.api_key}
                    onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
                    placeholder={dialogMode === "edit" ? selectedProvider?.api_key_masked || "leave blank to keep" : "optional if env is set"}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Group ID env</Label>
                  <Input value={draft.group_id_env} onChange={(e) => setDraft({ ...draft, group_id_env: e.target.value })} placeholder="MINIMAX_GROUP_ID" />
                </div>
                <div className="space-y-2">
                  <Label>Timeout seconds</Label>
                  <Input value={draft.timeout_seconds} onChange={(e) => setDraft({ ...draft, timeout_seconds: e.target.value })} />
                </div>
              </div>

              <DialogFooter>
                {dialogMode === "edit" && draft.id ? (
                  <Button variant="destructive" onClick={() => void handleDeleteProvider()} disabled={saving}>
                    <Trash2 className="size-4" />
                    Delete
                  </Button>
                ) : null}
                <Button onClick={() => void handleSaveProvider()} disabled={saving}>
                  <Save className="size-4" />
                  Save provider
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </WorkspaceShell>
  )
}
