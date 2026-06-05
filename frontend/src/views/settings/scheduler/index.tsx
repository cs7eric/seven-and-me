import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CirclePause,
  Clock,
  FileCode2,
  ListChecks,
  Play,
  Power,
  PowerOff,
  RefreshCcw,
  RefreshCw,
  Settings2,
  TimerReset,
  Zap,
} from "lucide-react"

import { WorkspaceShell } from "@/components/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { toast } from "sonner"
import {
  type SchedulerJobItem,
  disableSchedulerJob,
  enableSchedulerJob,
  fetchSchedulerJobs,
  startSchedulerJob,
  stopSchedulerJob,
  triggerSchedulerJob,
} from "@/lib/api"

type ActionKey = "enable" | "disable" | "start" | "stop" | "trigger"
type ActionState = Record<string, ActionKey | null>

const REFRESH_INTERVAL_MS = 5_000

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { hour12: false })
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  if (value < 60) return `${value.toFixed(1)}s`
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function statusBadgeVariant(status: string | null | undefined): "default" | "secondary" | "destructive" | "outline" {
  switch ((status || "").toLowerCase()) {
    case "success":
      return "default"
    case "failed":
    case "error":
    case "partial_failed":
      return "destructive"
    case "running":
    case "in_progress":
      return "secondary"
    default:
      return "outline"
  }
}

function pickValue<T = unknown>(record: Record<string, unknown> | undefined, key: string): T | undefined {
  if (!record) return undefined
  const value = record[key]
  return value as T | undefined
}

interface JobCardProps {
  job: SchedulerJobItem
  pending: ActionKey | null
  onAction: (jobId: string, action: ActionKey) => void
}

function JobCard({ job, pending, onAction }: JobCardProps) {
  const live = job.live || {}
  const config = job.config || {}
  const isRunning = Boolean(pickValue<boolean>(live, "running"))
  const tickCount = pickValue<number>(live, "tick_count")
  const runsCount = pickValue<number>(live, "runs_count")
  const startedAt = pickValue<string>(live, "started_at")
  const lastRunAt = pickValue<string>(config, "last_run_at") ?? pickValue<string>(config, "last_run_at")
  const lastStatus = pickValue<string>(config, "last_status")
  const lastError = pickValue<string>(config, "last_error")
  const lastDuration = pickValue<number>(config, "last_duration_seconds")
  const lastTargets = pickValue<number>(config, "last_targets_processed")
  const totalRuns = pickValue<number>(config, "total_runs")
  const inflight = pickValue<Record<string, string>>(live, "inflight")
  const lastRun = pickValue<Record<string, unknown>>(live, "last_run")

  const isActionPending = (action: ActionKey) => pending === action

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Settings2 className="size-4 text-muted-foreground" />
              {job.name}
              <span className="font-mono text-xs text-muted-foreground">({job.id})</span>
            </CardTitle>
            {job.description ? (
              <CardDescription>{job.description}</CardDescription>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={isRunning ? "default" : "secondary"}>
              {isRunning ? "运行中" : "已停止"}
            </Badge>
            {job.supports_enable ? (
              <Badge variant={job.config_enabled ? "outline" : "destructive"}>
                {job.config_enabled ? "已启用" : "已禁用"}
              </Badge>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            icon={<Activity className="size-3.5" />}
            label="tick 次数"
            value={tickCount ?? "—"}
          />
          <Stat
            icon={<ListChecks className="size-3.5" />}
            label="run 次数"
            value={runsCount ?? totalRuns ?? "—"}
          />
          <Stat
            icon={<Clock className="size-3.5" />}
            label="启动时间"
            value={formatDateTime(startedAt)}
          />
          <Stat
            icon={<TimerReset className="size-3.5" />}
            label="最后耗时"
            value={formatSeconds(lastDuration ?? null)}
          />
        </div>

        <Separator />

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5 text-sm">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              上次运行
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">时间：</span>
              <span>{formatDateTime(lastRunAt)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">状态：</span>
              {lastStatus ? (
                <Badge variant={statusBadgeVariant(lastStatus)}>{lastStatus}</Badge>
              ) : (
                <span>—</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">处理标的：</span>
              <span>{lastTargets ?? "—"} 个</span>
            </div>
            {lastError ? (
              <div className="flex items-start gap-2 text-destructive">
                <AlertTriangle className="mt-0.5 size-3.5" />
                <span className="text-xs leading-5">{lastError}</span>
              </div>
            ) : null}
          </div>

          <div className="space-y-1.5 text-sm">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              注册信息
            </div>
            <div className="flex items-center gap-2">
              <FileCode2 className="size-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">config：</span>
              <span className="break-all font-mono text-xs">{job.config_file || "—"}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">service：</span>
              <span className="break-all font-mono text-xs">
                {job.service_class || "—"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">module：</span>
              <span className="break-all font-mono text-xs">
                {job.service_module || "—"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">注册时间：</span>
              <span>{formatDateTime(job.registered_at)}</span>
            </div>
          </div>
        </div>

        {inflight && Object.keys(inflight).length > 0 ? (
          <>
            <Separator />
            <div className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                正在执行
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(inflight).map(([targetId, startedAtValue]) => (
                  <Badge key={targetId} variant="secondary">
                    {targetId} · {formatDateTime(startedAtValue)}
                  </Badge>
                ))}
              </div>
            </div>
          </>
        ) : null}

        {lastRun && Object.keys(lastRun).length > 0 ? (
          <>
            <Separator />
            <div className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                最近 per-target run
              </div>
              <div className="space-y-1">
                {Object.entries(lastRun)
                  .slice(0, 4)
                  .map(([targetId, info]) => {
                    const infoRecord = info as Record<string, unknown> | undefined
                    const status = pickValue<string>(infoRecord, "status") || "—"
                    return (
                      <div
                        key={targetId}
                        className="flex items-center justify-between gap-3 text-xs"
                      >
                        <span className="font-mono">{targetId}</span>
                        <span className="flex items-center gap-2 text-muted-foreground">
                          <Badge variant={statusBadgeVariant(status)} className="px-1.5 py-0">
                            {status}
                          </Badge>
                          <span>{formatDateTime(pickValue<string>(infoRecord, "finished_at"))}</span>
                        </span>
                      </div>
                    )
                  })}
                {Object.keys(lastRun).length > 4 ? (
                  <div className="text-xs text-muted-foreground">
                    ……还有 {Object.keys(lastRun).length - 4} 个 target
                  </div>
                ) : null}
              </div>
            </div>
          </>
        ) : null}

        <Separator />

        <div className="flex flex-wrap items-center gap-2">
          {job.supports_enable ? (
            job.config_enabled ? (
              <Button
                size="sm"
                variant="outline"
                className="rounded-xl"
                disabled={isActionPending("disable")}
                onClick={() => onAction(job.id, "disable")}
              >
                <PowerOff className="size-3.5" />
                {isActionPending("disable") ? "禁用中…" : "禁用"}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="default"
                className="rounded-xl"
                disabled={isActionPending("enable")}
                onClick={() => onAction(job.id, "enable")}
              >
                <Power className="size-3.5" />
                {isActionPending("enable") ? "启用中…" : "启用"}
              </Button>
            )
          ) : null}

          {isRunning ? (
            <Button
              size="sm"
              variant="destructive"
              className="rounded-xl"
              disabled={isActionPending("stop")}
              onClick={() => onAction(job.id, "stop")}
            >
              <CirclePause className="size-3.5" />
              {isActionPending("stop") ? "停止中…" : "停止调度"}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="default"
              className="rounded-xl"
              disabled={isActionPending("start")}
              onClick={() => onAction(job.id, "start")}
            >
              <Play className="size-3.5" />
              {isActionPending("start") ? "启动中…" : "启动调度"}
            </Button>
          )}

          <Button
            size="sm"
            variant="secondary"
            className="rounded-xl"
            disabled={isActionPending("trigger")}
            onClick={() => onAction(job.id, "trigger")}
          >
            <Zap className="size-3.5" />
            {isActionPending("trigger") ? "触发中…" : "立即触发一次"}
          </Button>

          {job.config_enabled && !isRunning ? (
            <span className="inline-flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle className="size-3" />
              配置启用但线程未运行（重启 Flask 或点 "启动调度"）
            </span>
          ) : null}
          {job.config_enabled === false && isRunning ? (
            <span className="inline-flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle className="size-3" />
              线程运行中但配置已禁用（下次 start 会读取新配置）
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-border/30 bg-muted/30 p-3">
      <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="text-sm font-medium text-foreground">{value}</div>
    </div>
  )
}

export default function SchedulerSettingsPage() {
  const [jobs, setJobs] = useState<SchedulerJobItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [pending, setPending] = useState<ActionState>({})

  const refresh = useCallback(async (withSpinner = false) => {
    if (withSpinner) setLoading(true)
    try {
      const res = await fetchSchedulerJobs()
      if (res.ok) {
        setJobs(res.items || [])
        setError(null)
        setLastUpdated(new Date())
      } else {
        setError(res.error || "获取调度任务列表失败")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "未知错误")
    } finally {
      if (withSpinner) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh(true)
    const timer = window.setInterval(() => {
      void refresh(false)
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const handleAction = useCallback(
    async (jobId: string, action: ActionKey) => {
      setPending((prev) => ({ ...prev, [jobId]: action }))
      try {
        let res
        switch (action) {
          case "enable":
            res = await enableSchedulerJob(jobId)
            toast.success("已启用", { description: `job ${jobId} 已开启` })
            break
          case "disable":
            res = await disableSchedulerJob(jobId)
            toast.success("已禁用", { description: `job ${jobId} 已关闭` })
            break
          case "start":
            res = await startSchedulerJob(jobId)
            toast.success("调度已启动", { description: `job ${jobId}` })
            break
          case "stop":
            res = await stopSchedulerJob(jobId)
            toast.success("调度已停止", { description: `job ${jobId}` })
            break
          case "trigger":
            res = await triggerSchedulerJob(jobId)
            toast.success("已触发一次", { description: `job ${jobId} 跑完后会自动刷新` })
            break
        }
        if (res && res.ok === false) {
          toast.error("操作失败", { description: res.error || "请查看后端日志" })
        }
      } catch (err) {
        toast.error("操作失败", {
          description: err instanceof Error ? err.message : "未知错误",
        })
      } finally {
        setPending((prev) => ({ ...prev, [jobId]: null }))
        // 操作后等一拍再刷新，让后端先把状态写回 JSON
        window.setTimeout(() => {
          void refresh(false)
        }, 600)
      }
    },
    [refresh],
  )

  const summary = useMemo(() => {
    const total = jobs.length
    const running = jobs.filter((job) => Boolean(pickValue<boolean>(job.live, "running"))).length
    const enabled = jobs.filter((job) => job.config_enabled).length
    return { total, running, enabled }
  }, [jobs])

  return (
    <WorkspaceShell sectionLabel="Settings" pageTitle="Scheduler">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
            <Settings2 className="size-3.5" />
            Settings · Scheduler
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            调度任务管理
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            统一管理 <code className="rounded bg-muted px-1.5 py-0.5 text-xs">scheduler/jobs.json</code> 注册的调度任务：
            实时查看线程状态、上一轮运行情况，并支持启用 / 禁用 / 启动 / 停止 / 手动触发。
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="rounded-xl"
            onClick={() => void refresh(false)}
            disabled={loading}
          >
            <RefreshCcw className="size-3.5" />
            立即刷新
          </Button>
          <div className="text-xs text-muted-foreground">
            {lastUpdated
              ? `最近刷新：${lastUpdated.toLocaleTimeString("zh-CN", { hour12: false })} · 每 ${REFRESH_INTERVAL_MS / 1000}s 自动刷新`
              : `每 ${REFRESH_INTERVAL_MS / 1000}s 自动刷新`}
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          icon={<ListChecks className="size-4" />}
          label="注册任务"
          value={summary.total}
          hint="jobs.json 中注册的 job 数量"
        />
        <SummaryCard
          icon={<Activity className="size-4" />}
          label="运行中"
          value={summary.running}
          hint="线程 alive 状态"
        />
        <SummaryCard
          icon={<CheckCircle2 className="size-4" />}
          label="已启用"
          value={summary.enabled}
          hint="config.enabled = true"
        />
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>拉取调度任务失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading && jobs.length === 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72 w-full rounded-2xl" />
          <Skeleton className="h-72 w-full rounded-2xl" />
          <Skeleton className="h-72 w-full rounded-2xl" />
        </div>
      ) : jobs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <RefreshCw className="size-8 text-muted-foreground" />
            <div className="text-sm font-medium text-foreground">
              jobs.json 中还没有注册任何调度任务
            </div>
            <p className="max-w-md text-sm leading-6 text-muted-foreground">
              启动一次 Flask 后，scheduler 会自动把 turnover / auction / application_analysis
              三个内置 job 注册进去；或者手动编辑{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">scheduler/jobs.json</code>。
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              pending={pending[job.id] ?? null}
              onAction={handleAction}
            />
          ))}
        </div>
      )}
    </WorkspaceShell>
  )
}

function SummaryCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode
  label: string
  value: number
  hint: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-4">
        <div className="flex size-9 items-center justify-center rounded-xl bg-muted text-foreground">
          {icon}
        </div>
        <div>
          <div className="text-2xl font-semibold leading-none text-foreground">{value}</div>
          <div className="mt-1 text-xs text-muted-foreground">{label}</div>
        </div>
        <div className="ml-auto text-right text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  )
}
