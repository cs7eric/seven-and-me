import { fetchWithRetry } from "@/services/common/http"
import { SERVICE_PREFIX } from "@/services/common/service-prefix"

const SCHEDULER_API_BASE = `${SERVICE_PREFIX.legacy}/api/scheduler`

export interface SchedulerJobItem {
  id: string
  name: string
  description?: string
  config_file?: string
  service_module?: string
  service_class?: string
  registered_at?: string
  categories?: number[]
  categorySortOrders?: Record<number, number>
  supports_enable: boolean
  enabled: boolean
  config_enabled: boolean
  config: Record<string, unknown>
  live: Record<string, unknown>
  last_run?: {
    last_run_at: string | null
    last_status: string | null
    last_targets_processed: number | null
    last_duration_seconds: number | null
    last_error: string | null
    total_runs: number | null
  }
}

export interface SchedulerJobsResponse {
  ok: boolean
  items: SchedulerJobItem[]
  count: number
  error?: string
}

export interface SchedulerCategory {
  id: number
  label: string
  icon_hint: string
  sort_order: number
  description?: string
  count: number
}

export interface SchedulerCategoriesResponse {
  ok: boolean
  items: SchedulerCategory[]
  count: number
  error?: string
}

export interface SchedulerDailyStatItem {
  date: string
  total: number
  success: number
  failed: number
  skipped: number
}

export interface SchedulerDailyStatsSummary {
  total: number
  failed: number
  success_rate: number
}

export interface SchedulerDailyStatsResponse {
  ok: boolean
  items: SchedulerDailyStatItem[]
  summary: SchedulerDailyStatsSummary
  error?: string
}

export interface SchedulerJobActionResponse {
  ok: boolean
  job_id?: string
  enabled?: boolean
  status?: Record<string, unknown>
  result?: Record<string, unknown> | { ok: boolean; items?: unknown[]; count?: number; error?: string }
  config?: Record<string, unknown>
  error?: string
}

export interface SchedulerJobHistoryItem {
  id?: string
  start_at: string
  end_at: string
  trigger_type: "auto" | "manual" | string
  status: "success" | "failed" | "skipped" | "running" | "processing" | string
  error: string | null
  message?: string | null
  duration_seconds: number | null
  target_count?: number
  succeeded?: number
}

export interface SchedulerJobHistoryResponse {
  ok: boolean
  job_id?: string
  items: SchedulerJobHistoryItem[]
  count: number
  error?: string
}

export async function fetchSchedulerDailyStats(days = 14): Promise<SchedulerDailyStatsResponse> {
  const res = await fetchWithRetry(
    `${SCHEDULER_API_BASE}/stats/daily?days=${encodeURIComponent(String(days))}`,
    { cache: "no-store" },
  )
  const data = (await res.json().catch(() => null)) as SchedulerDailyStatsResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务日统计失败")
  return data
}

export async function fetchSchedulerCategories(): Promise<SchedulerCategoriesResponse> {
  const res = await fetchWithRetry(`${SCHEDULER_API_BASE}/categories`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as SchedulerCategoriesResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务分类失败")
  return data
}

export async function fetchSchedulerJobs(): Promise<SchedulerJobsResponse> {
  const res = await fetchWithRetry(`${SCHEDULER_API_BASE}/jobs`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as SchedulerJobsResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务列表失败")
  return data
}

export async function fetchSchedulerJobHistory(
  jobId: string,
  limit = 50,
): Promise<SchedulerJobHistoryResponse> {
  const res = await fetchWithRetry(
    `${SCHEDULER_API_BASE}/jobs/${encodeURIComponent(jobId)}/history?limit=${encodeURIComponent(String(limit))}`,
    { cache: "no-store" },
  )
  const data = (await res.json().catch(() => null)) as SchedulerJobHistoryResponse | null
  if (!res.ok || !data) throw new Error(`获取 job history 失败: ${res.status}`)
  return data
}

async function postSchedulerAction(
  jobId: string,
  action: "enable" | "disable" | "trigger" | "start" | "stop",
  body?: Record<string, unknown>,
): Promise<SchedulerJobActionResponse> {
  const res = await fetchWithRetry(`${SCHEDULER_API_BASE}/jobs/${encodeURIComponent(jobId)}/${action}`, {
    method: "POST",
    ...(body
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  })
  const data = (await res.json().catch(() => null)) as SchedulerJobActionResponse | null
  if (!res.ok || !data) {
    throw new Error(data?.error || `调度任务 ${action} 失败`)
  }
  return data
}

export const enableSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "enable")
export const disableSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "disable")

// Trigger keeps calling the Python scheduler runtime. Java core only owns persisted scheduler data for now.
export const triggerSchedulerJob = (jobId: string, options?: { targetDate?: string | null }) =>
  postSchedulerAction(
    jobId,
    "trigger",
    options?.targetDate ? { target_date: options.targetDate } : undefined,
  )

export const startSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "start")
export const stopSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "stop")

export async function deleteSchedulerJob(jobId: string): Promise<SchedulerJobActionResponse> {
  const res = await fetchWithRetry(`${SCHEDULER_API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  })
  const data = (await res.json().catch(() => null)) as SchedulerJobActionResponse | null
  if (!res.ok || !data) {
    throw new Error(data?.error || `删除 job ${jobId} 失败`)
  }
  return data
}

