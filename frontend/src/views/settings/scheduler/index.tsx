import { useCallback, useEffect, useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CirclePause,
  Clock,
  Database,
  FileCode2,
  Hand,
  History as HistoryIcon,
  LayoutGrid,
  ListChecks,
  Play,
  Power,
  PowerOff,
  RefreshCcw,
  RefreshCw,
  Settings2,
  Sparkles,
  TimerReset,
  Trash2,
  TrendingUp,
  Zap,
} from "lucide-react"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { notification } from "@/components/ui/notification"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import DogLoader from "@/components/loader/dog-loader"
import {
  type SchedulerCategory,
  type SchedulerDailyStatItem,
  type SchedulerJobHistoryItem,
  type SchedulerJobItem,
  deleteSchedulerJob,
  disableSchedulerJob,
  enableSchedulerJob,
  fetchSchedulerCategories,
  fetchSchedulerDailyStats,
  fetchSchedulerJobHistory,
  fetchSchedulerJobs,
  startSchedulerJob,
  stopSchedulerJob,
  triggerSchedulerJob,
} from "@/lib/api"

type ActionKey = "enable" | "disable" | "start" | "stop" | "trigger" | "delete"
type ActionState = Record<string, ActionKey | null>

const REFRESH_INTERVAL_MS = 5_000
const ALL_TAB = "all"  // 兜底 tab (不过滤)

// ---------------------------------------------------------------------------
// Icon mapping: 后端 icon_hint (lucide 图标名) → 实际组件.
// 这是前端唯一与后端耦合的点: 后端返 "activity" / "sparkles" 等字符串,
// 前端用这张表查组件. 加新 category 时, 后端给个新 icon_hint 即可, 前端
// 在这里加一行 fallback. 没找到就回退到 LayoutGrid.
// ---------------------------------------------------------------------------
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  activity: Activity,
  sparkles: Sparkles,
  database: Database,
  refresh: RefreshCcw,
  trending: TrendingUp,
  flask: Settings2,        // lucide 没 Flask, 用 Settings2 凑
  grid: LayoutGrid,
}

function iconFor(hint: string | undefined): React.ComponentType<{ className?: string }> {
  if (!hint) return LayoutGrid
  return ICON_MAP[hint] || LayoutGrid
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" })
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
  const [dialogOpen, setDialogOpen] = useState(false)
  // 历史记录: dialog 打开后才拉, 5s 自动 refresh
  const [history, setHistory] = useState<SchedulerJobHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const live = job.live || {}
  const config = job.config || {}
  const isRunning = Boolean(pickValue<boolean>(live, "running"))
  const lastRunSummary = job.last_run
  const lastRunAt = lastRunSummary?.last_run_at ?? pickValue<string>(config, "last_run_at")
  const lastStatus = lastRunSummary?.last_status ?? pickValue<string>(config, "last_status")
  const lastError = lastRunSummary?.last_error ?? pickValue<string>(config, "last_error")
  const lastMessage = pickValue<string>(live, "lastMessage") ?? pickValue<string>(config, "lastMessage")
  const lastDuration =
    lastRunSummary?.last_duration_seconds ?? pickValue<number>(config, "last_duration_seconds")
  const lastTargets =
    lastRunSummary?.last_targets_processed ?? pickValue<number>(config, "last_targets_processed")
  const totalRuns = lastRunSummary?.total_runs ?? pickValue<number>(config, "total_runs")
  const registeredAt = job.registered_at
  const inflight = pickValue<Record<string, string>>(live, "inflight")
  const lastRun = pickValue<Record<string, unknown>>(live, "last_run")

  const isActionPending = (action: ActionKey) => pending === action

  // history: dialog 打开时才拉, 5s 轮询. pending 变化 (trigger) 也重拉.
  useEffect(() => {
    if (!dialogOpen) {
      setHistory([])
      return
    }
    let cancelled = false
    const load = () => {
      setHistoryLoading(true)
      fetchSchedulerJobHistory(job.id, 20)
        .then((res) => {
          if (!cancelled) setHistory(res.items || [])
        })
        .catch(() => {
          if (!cancelled) setHistory([])
        })
        .finally(() => {
          if (!cancelled) setHistoryLoading(false)
        })
    }
    load()
    const t = window.setInterval(load, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [dialogOpen, job.id, pending])

  return (
    <Card className="mb-4 break-inside-avoid border-0 shadow-none bg-muted/60">
      {/* 列表项: 点击打开 dialog 查看详情 */}
      <CardHeader
        className="cursor-pointer select-none py-0 transition-colors hover:bg-muted/30"
        onClick={() => setDialogOpen(true)}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Settings2 className="size-4 shrink-0 text-muted-foreground" />
            <CardTitle className="truncate text-base font-medium">{job.name}</CardTitle>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 启用状态 */}
            {job.supports_enable ? (
              <Badge variant={job.config_enabled ? "outline" : "destructive"}>
                {job.config_enabled ? "已启用" : "已禁用"}
              </Badge>
            ) : null}
            {/* 运行状态 */}
            {isRunning ? (
              <Badge variant="default" className="bg-emerald-600 hover:bg-emerald-600/90">运行中</Badge>
            ) : (
              <Badge variant="secondary">已停止</Badge>
            )}
            {/* 启用/停用按钮 */}
            {job.supports_enable ? (
              job.config_enabled ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-xl"
                  disabled={isActionPending("disable")}
                  onClick={() => onAction(job.id, "disable")}
                >
                  <PowerOff className="size-3" />
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
                  <Power className="size-3" />
                  {isActionPending("enable") ? "启用中…" : "启用"}
                </Button>
              )
            ) : null}
            {/* 触发按钮 */}
            <Button
              size="sm"
              variant="secondary"
              className="rounded-xl"
              disabled={isActionPending("trigger")}
              onClick={() => onAction(job.id, "trigger")}
            >
              <Zap className="size-3" />
              {isActionPending("trigger") ? "触发中…" : "触发"}
            </Button>
          </div>
        </div>
      </CardHeader>

      {/* Dialog 详情 */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="size-4" />
              {job.name}
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {job.id}
              </span>
            </DialogTitle>
            {(job.categories || []).length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {(job.categories || []).map((c) => (
                  <Badge key={c} variant="outline" className="px-1.5 py-0 text-[10px] font-normal">
                    {c}
                  </Badge>
                ))}
              </div>
            ) : null}
          </DialogHeader>

          {/* 状态条 */}
          <div className="flex flex-wrap items-center gap-2">
            {isRunning ? (
              <Badge variant="default" className="bg-emerald-600 hover:bg-emerald-600/90">运行中</Badge>
            ) : (
              <Badge variant="secondary">已停止</Badge>
            )}
            {job.supports_enable ? (
              <Badge variant={job.config_enabled ? "outline" : "destructive"}>
                {job.config_enabled ? "已启用" : "已禁用"}
              </Badge>
            ) : null}
          </div>

          {/* 计算逻辑 */}
          {job.description ? (
            <>
              <div className="space-y-2 text-sm">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  计算逻辑
                </div>
                <div className="whitespace-pre-wrap rounded-2xl border border-border/40 bg-background/70 p-3 text-xs leading-6 text-muted-foreground">
                  {job.description}
                </div>
              </div>
              <Separator />
            </>
          ) : null}

          {/* 统计网格 */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={<ListChecks className="size-3.5" />} label="累计运行" value={totalRuns ?? "—"} />
            <Stat icon={<TimerReset className="size-3.5" />} label="最后耗时" value={formatSeconds(lastDuration ?? null)} />
            <Stat icon={<Activity className="size-3.5" />} label="处理标的" value={lastTargets ?? "—"} />
            <Stat icon={<Clock className="size-3.5" />} label="注册时间" value={formatDateTime(registeredAt)} />
          </div>

          <Separator />

          {/* 上次运行 + 注册信息 */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">上次运行</div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">时间：</span>
                <span>{formatDateTime(lastRunAt)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">状态：</span>
                {lastStatus ? (
                  <Badge variant={statusBadgeVariant(lastStatus)}>{lastStatus}</Badge>
                ) : <span>—</span>}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">处理标的：</span>
                <span>{lastTargets ?? "—"} 个</span>
              </div>
              {lastError ? (
                <div className={cn("flex items-start gap-2", lastStatus === "skipped" ? "text-amber-600" : "text-destructive")}>
                  <AlertTriangle className="mt-0.5 size-3.5" />
                  <span className="text-xs leading-5">{lastError}</span>
                </div>
              ) : null}
              {!lastError && lastMessage ? (
                <div className="flex items-start gap-2 text-emerald-600">
                  <CheckCircle2 className="mt-0.5 size-3.5" />
                  <span className="text-xs leading-5">{lastMessage}</span>
                </div>
              ) : null}
            </div>

            <div className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">注册信息</div>
              <div className="flex items-center gap-2">
                <FileCode2 className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">config：</span>
                <span className="break-all font-mono text-xs">{job.config_file || "—"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">service：</span>
                <span className="break-all font-mono text-xs">{job.service_class || "—"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">module：</span>
                <span className="break-all font-mono text-xs">{job.service_module || "—"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">注册时间：</span>
                <span>{formatDateTime(job.registered_at)}</span>
              </div>
            </div>
          </div>

          {/* Inflight */}
          {inflight && Object.keys(inflight).length > 0 ? (
            <>
              <Separator />
              <div className="space-y-1.5 text-sm">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">正在执行</div>
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

          {/* Per-target last run */}
          {lastRun && Object.keys(lastRun).length > 0 ? (
            <>
              <Separator />
              <div className="space-y-1.5 text-sm">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">最近 per-target run</div>
                <div className="space-y-1">
                  {Object.entries(lastRun).slice(0, 4).map(([targetId, info]) => {
                    const infoRecord = info as Record<string, unknown> | undefined
                    const status = pickValue<string>(infoRecord, "status") || "—"
                    return (
                      <div key={targetId} className="flex items-center justify-between gap-3 text-xs">
                        <span className="font-mono">{targetId}</span>
                        <span className="flex items-center gap-2 text-muted-foreground">
                          <Badge variant={statusBadgeVariant(status)} className="px-1.5 py-0">{status}</Badge>
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
          <JobHistorySection items={history} loading={historyLoading} />
          <Separator />

          {/* 操作按钮组 */}
          <div className="flex flex-wrap items-center gap-2">
            {isRunning ? (
              <Button size="sm" variant="destructive" className="rounded-xl" disabled={isActionPending("stop")} onClick={() => onAction(job.id, "stop")}>
                <CirclePause className="size-3.5" />
                {isActionPending("stop") ? "停止中…" : "停止调度"}
              </Button>
            ) : (
              <Button size="sm" variant="default" className="rounded-xl" disabled={isActionPending("start")} onClick={() => onAction(job.id, "start")}>
                <Play className="size-3.5" />
                {isActionPending("start") ? "启动中…" : "启动调度"}
              </Button>
            )}

            {job.supports_enable ? (
              job.config_enabled ? (
                <Button size="sm" variant="outline" className="rounded-xl" disabled={isActionPending("disable")} onClick={() => onAction(job.id, "disable")}>
                  <PowerOff className="size-3.5" />
                  {isActionPending("disable") ? "禁用中…" : "禁用"}
                </Button>
              ) : (
                <Button size="sm" variant="default" className="rounded-xl" disabled={isActionPending("enable")} onClick={() => onAction(job.id, "enable")}>
                  <Power className="size-3.5" />
                  {isActionPending("enable") ? "启用中…" : "启用"}
                </Button>
              )
            ) : null}

            {job.config_enabled && !isRunning ? (
              <span className="inline-flex items-center gap-1 text-xs text-amber-600">
                <AlertTriangle className="size-3" />
                配置启用但线程未运行
              </span>
            ) : null}
            {job.config_enabled === false && isRunning ? (
              <span className="inline-flex items-center gap-1 text-xs text-amber-600">
                <AlertTriangle className="size-3" />
                线程运行中但配置已禁用
              </span>
            ) : null}

            <DeleteJobButton
              jobId={job.id}
              jobName={job.name}
              pending={isActionPending("delete")}
              onConfirm={() => {
                onAction(job.id, "delete")
                setDialogOpen(false)
              }}
            />
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

/** Job 历史记录 section. 每行: 开始时间 + 触发方式 (自动/手动) + 状态 (成功/失败/跳过) + 错误 + 耗时. */
function JobHistorySection({
  items,
  loading,
}: {
  items: SchedulerJobHistoryItem[]
  loading: boolean
}) {
  return (
    <div className="space-y-1.5 text-sm">
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <HistoryIcon className="size-3.5" />
        <span>历史记录</span>
        <span className="text-[10px] text-muted-foreground/60">
          (默认显示 3 条, 每 5s 自动刷新)
        </span>
        {loading ? (
          <RefreshCw className="size-3 animate-spin text-muted-foreground/60" />
        ) : null}
      </div>

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/40 bg-background/30 px-3 py-4 text-center text-xs text-muted-foreground">
          {loading ? "加载中…" : "暂无历史记录 (等下次 cron 触发 或 点 \"立即触发\")"}
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border border-border/30">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 bg-muted/30 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <span>开始时间</span>
            <span>触发</span>
            <span>状态</span>
            <span>耗时</span>
          </div>
          <div className="divide-y divide-border/30">
            {items.slice(0, 3).map((it, idx) => (
              <HistoryRow key={`${it.start_at}-${idx}`} item={it} />
            ))}
            {items.length > 3 ? (
              <div className="flex items-center justify-center bg-muted/20 px-2 py-2 text-[11px] text-muted-foreground">
                …… 还有 {items.length - 3} 条历史记录未展开显示
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

function HistoryRow({ item }: { item: SchedulerJobHistoryItem }) {
  const [expanded, setExpanded] = useState(false)
  const isFailed = item.status === "failed"
  const isSkipped = item.status === "skipped"
  const isSuccess = item.status === "success"
  const isManual = item.trigger_type === "manual"
  const hasDetail = (isFailed || isSkipped) ? !!item.error : (isSuccess && !!item.message)

  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto] items-center gap-2 px-2 py-1.5 text-xs",
        isFailed && "bg-red-50/50 dark:bg-red-950/10",
        isSkipped && "bg-amber-50/50 dark:bg-amber-950/10",
        isSuccess && (item.error || item.message) && "bg-emerald-50/50 dark:bg-emerald-950/10",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {hasDetail ? (
          <button
            type="button"
            aria-label={expanded ? "收起详情" : "展开详情"}
            onClick={() => setExpanded((v) => !v)}
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            {expanded ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </button>
        ) : (
          <span className="w-3" />
        )}
        <span className="truncate font-mono tabular-nums" title={item.start_at}>
          {formatDateTime(item.start_at)}
        </span>
      </div>
      <Badge
        variant={isManual ? "secondary" : "outline"}
        className="px-1.5 py-0 text-[10px]"
        title={isManual ? "用户手动触发" : "cron 自动触发"}
      >
        {isManual ? (
          <>
            <Hand className="mr-0.5 size-2.5" />
            手动
          </>
        ) : (
          "自动"
        )}
      </Badge>
      <Badge variant={statusBadgeVariant(item.status)} className="px-1.5 py-0 text-[10px]">
        {item.status}
      </Badge>
      <span className="font-mono tabular-nums text-muted-foreground">
        {formatSeconds(item.duration_seconds)}
      </span>

      {hasDetail && expanded ? (
        <div className={cn(
          "col-span-4 mt-1 flex items-start gap-1.5 rounded border px-2 py-1.5 text-[11px] leading-5",
          isSkipped
            ? "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/20 dark:text-amber-400"
            : isSuccess
              ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/20 dark:text-emerald-400"
              : "border-destructive/30 bg-destructive/5 text-destructive",
        )}>
          {isSuccess ? (
            <CheckCircle2 className="mt-0.5 size-3 shrink-0" />
          ) : (
            <AlertTriangle className="mt-0.5 size-3 shrink-0" />
          )}
          <span className="break-all whitespace-pre-wrap">{isSuccess ? item.message : item.error}</span>
        </div>
      ) : null}

      {!isFailed && item.target_count != null && item.target_count > 0 ? (
        <div className="col-span-4 mt-0.5 text-[10px] text-muted-foreground">
          处理标的 {item.target_count} 个, 成功 {item.succeeded ?? 0}
        </div>
      ) : null}
    </div>
  )
}

/** 删除按钮: 点击弹出确认对话框, 确认后调用 onConfirm */
function DeleteJobButton({
  jobId,
  jobName,
  pending,
  onConfirm,
}: {
  jobId: string
  jobName: string
  pending: boolean
  onConfirm: () => void
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto rounded-xl text-destructive hover:bg-destructive/10 hover:text-destructive"
          disabled={pending}
        >
          <Trash2 className="size-3.5" />
          {pending ? "删除中…" : "删除"}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>删除调度任务</DialogTitle>
          <DialogDescription>
            确认要删除 <span className="font-mono font-semibold">{jobId}</span> 吗？
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-6 text-foreground">
          <div className="font-medium">{jobName}</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            <li>会从 <code className="rounded bg-muted px-1">scheduler/jobs.json</code> 注册表里移除</li>
            <li>后端会停掉该 job 的调度器线程（如果正在运行）</li>
            <li>下次重启 Flask 不会自动重新注册</li>
            <li className="text-destructive">删除后如需恢复，需手动重新注册到 jobs.json</li>
          </ul>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" className="rounded-xl">取消</Button>
          </DialogClose>
          <DialogClose asChild>
            <Button
              variant="destructive"
              className="rounded-xl"
              disabled={pending}
              onClick={onConfirm}
            >
              <Trash2 className="size-3.5" />
              确认删除
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
  const [activeCategory, setActiveCategory] = useState<string>(ALL_TAB)
  const [categories, setCategories] = useState<SchedulerCategory[]>([])
  const [dailyStats, setDailyStats] = useState<SchedulerDailyStatItem[]>([])
  const [dailyStatsSummary, setDailyStatsSummary] = useState<{ total: number; failed: number; success_rate: number } | null>(null)

  const refresh = useCallback(async (withSpinner = false) => {
    if (withSpinner) setLoading(true)
    try {
      const [jobsRes, catRes, statsRes] = await Promise.all([
        fetchSchedulerJobs(),
        fetchSchedulerCategories(),
        fetchSchedulerDailyStats(14),
      ])
      if (jobsRes.ok) {
        setJobs(jobsRes.items || [])
        setError(null)
        setLastUpdated(new Date())
      } else {
        setError(jobsRes.error || "获取调度任务列表失败")
        if (withSpinner) {
          notification.danger({
            title: "加载调度任务失败",
            description: jobsRes.error || "请检查后端服务",
          })
        }
      }
      if (catRes.ok) {
        setCategories(catRes.items || [])
      }
      if (statsRes.ok) {
        setDailyStats(statsRes.items || [])
        setDailyStatsSummary(statsRes.summary ?? null)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "未知错误"
      setError(msg)
      if (withSpinner) {
        notification.danger({ title: "加载调度任务失败", description: msg })
      }
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
            break
          case "disable":
            res = await disableSchedulerJob(jobId)
            break
          case "start":
            res = await startSchedulerJob(jobId)
            break
          case "stop":
            res = await stopSchedulerJob(jobId)
            break
          case "trigger":
            res = await triggerSchedulerJob(jobId)
            break
          case "delete":
            res = await deleteSchedulerJob(jobId)
            break
        }
        if (res && res.ok === false) {
          // trigger 的 error 嵌套在 result.error 里, 其他 action 在 res.error
          const nestedError =
            (res.result && (res.result as { error?: string }).error) || undefined
          const errorMsg = res.error || nestedError || "请查看后端日志"
          notification.danger({
            title: "操作失败",
            description: errorMsg,
          })
          return
        }
        // 成功：根据 action 给具体文案
        switch (action) {
          case "enable":
            notification.success({ title: "已启用", description: `job ${jobId} 已开启` })
            break
          case "disable":
            notification.success({ title: "已禁用", description: `job ${jobId} 已关闭` })
            break
          case "start":
            notification.success({ title: "调度已启动", description: `job ${jobId}` })
            break
          case "stop":
            notification.success({ title: "调度已停止", description: `job ${jobId}` })
            break
          case "trigger": {
            const count = (res && (res as { count?: number }).count) ?? 0
            const failed = (res && (res as { failed_count?: number }).failed_count) ?? 0
            // 从 items 里取具体错误, 结构: result.items[0].lastRunError 或 result.items[0].last_error
            const resultItems = (res && (res as any).result?.items) || []
            const detailError = resultItems.length > 0
              ? (resultItems[0].lastRunError || resultItems[0].last_error || "")
              : ""
            if (count > 0) {
              if (failed > 0) {
                notification.danger({
                  title: `触发完成 — ${failed}/${count} 失败`,
                  description: detailError || "请展开 job 卡片查看详情",
                })
              } else {
                notification.success({
                  title: "已触发一次",
                  description: `${count} 个标的全部执行成功`,
                })
              }
            } else {
              notification.info({
                title: "已触发",
                description: "本次没有可执行的标的（targets 为空或全部未启用）",
              })
            }
            break
          }
          case "delete":
            notification.success({
              title: "已删除",
              description: `job ${jobId} 已从 jobs.json 中移除（后端会停掉线程）`,
            })
            // 立即从本地列表移除, 不等 refresh
            setJobs((prev) => prev.filter((j) => j.id !== jobId))
            break
        }
      } catch (err) {
        notification.danger({
          title: "操作失败",
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

  // 每个 category 的 job 数 (用于 tab 上显示 count; 后端也带, 这里前端再算一份兜底)
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { [ALL_TAB]: jobs.length }
    for (const job of jobs) {
      for (const c of job.categories || []) {
        counts[c] = (counts[c] || 0) + 1
      }
    }
    return counts
  }, [jobs])

  // 按 category 切分 jobs: 每个 tab 一个数组.
  //   - ALL_TAB 返回全部 jobs
  //   - 其它 tab 返回 (categories || []).includes(catId) 的 jobs
  // shadcn TabsContent 要求 value 是 string, 这里跟 TabsTrigger 的 value 用同一个 String(catId).
  const jobsForCategory = useCallback(
    (key: string): SchedulerJobItem[] => {
      if (key === ALL_TAB) return jobs
      const catId = Number(key)
      if (!Number.isFinite(catId)) return jobs
      const filtered = jobs.filter((job) => (job.categories || []).includes(catId))
      // 按 categorySortOrders 排序 (market_sentiment 等按执行顺序), 无 sortOrder 的放最后
      filtered.sort((a, b) => {
        const sa = (a as any).categorySortOrders?.[catId] ?? 999
        const sb = (b as any).categorySortOrders?.[catId] ?? 999
        return sa - sb
      })
      return filtered
    },
    [jobs],
  )

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

      {/* 每日运行统计 */}
      {dailyStats.length > 0 ? (
        <Card className="overflow-hidden border-0 bg-muted/60 shadow-none py-0">
          <div className="flex items-center justify-between gap-4 px-4 pt-4 pb-2">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <BarChart3 className="size-4 text-muted-foreground" />
              运行统计
            </div>
            {dailyStatsSummary ? (
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <span className="inline-block size-2 rounded-full bg-emerald-500/80" />
                  成功 {dailyStatsSummary.total - dailyStatsSummary.failed}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="inline-block size-2 rounded-full bg-red-500/80" />
                  失败 {dailyStatsSummary.failed}
                </span>
                <span>
                  {dailyStatsSummary.success_rate >= 1
                    ? "100"
                    : (dailyStatsSummary.success_rate * 100).toFixed(1)}
                  %
                </span>
                <span className="text-muted-foreground/60">· {dailyStatsSummary.total} 次</span>
              </div>
            ) : null}
          </div>
          <CardContent className="px-4 pb-3">
            <DailyStatsChart items={dailyStats} />
          </CardContent>
        </Card>
      ) : null}

      {/* shadcn Tabs: 按 category 切换. 默认 variant (bg-muted) 保证 trigger 可见,
          每个 tab 一个 <TabsContent> 渲染对应 jobs. 不传 forceMount, 让 shadcn
          按 active tab 自动 mount/unmount. */}
      <Tabs value={activeCategory} onValueChange={setActiveCategory} className="w-full">
        <TabsList>
          {/* "全部" tab 固定第一个, 不来自 API */}
          <TabsTrigger value={ALL_TAB}>
            <LayoutGrid className="size-3.5" />
            全部
            <Badge
              variant={activeCategory === ALL_TAB ? "default" : "secondary"}
              className="ml-1 px-1.5 py-0 text-[10px]"
            >
              {categoryCounts[ALL_TAB] ?? 0}
            </Badge>
          </TabsTrigger>
          {categories.map((cat) => {
            const Icon = iconFor(cat.icon_hint)
            const count = categoryCounts[cat.id] ?? cat.count
            const value = String(cat.id)
            return (
              <TabsTrigger
                key={cat.id}
                value={value}
                disabled={count === 0}
                title={cat.description}
              >
                <Icon className="size-3.5" />
                {cat.label}
                <Badge
                  variant={activeCategory === value ? "default" : "secondary"}
                  className="ml-1 px-1.5 py-0 text-[10px]"
                >
                  {count}
                </Badge>
              </TabsTrigger>
            )
          })}
        </TabsList>

        {error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>拉取调度任务失败</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {loading && jobs.length === 0 ? (
          <DogLoader overlay size={25} label="正在加载调度任务..." />
        ) : jobs.length === 0 ? (
          <Card className="border-0 bg-muted/60 shadow-none py-0">
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
          <>
            <TabsContent value={ALL_TAB}>
              <JobsGrid
                jobs={jobsForCategory(ALL_TAB)}
                pending={pending}
                onAction={handleAction}
                emptyState={
                  <Card className="border-0 bg-muted/60 shadow-none py-0">
                    <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
                      <BarChart3 className="size-8 text-muted-foreground" />
                      <div className="text-sm font-medium text-foreground">
                        还没有注册任何调度任务
                      </div>
                    </CardContent>
                  </Card>
                }
              />
            </TabsContent>

            {categories.map((cat) => {
              const value = String(cat.id)
              return (
                <TabsContent key={cat.id} value={value}>
                  <JobsGrid
                    jobs={jobsForCategory(value)}
                    pending={pending}
                    onAction={handleAction}
                    emptyState={
                      <Card className="border-0 bg-muted/60 shadow-none py-0">
                        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
                          <BarChart3 className="size-8 text-muted-foreground" />
                          <div className="text-sm font-medium text-foreground">
                            "{cat.label}" category 没有 job
                          </div>
                        </CardContent>
                      </Card>
                    }
                  />
                </TabsContent>
              )
            })}
          </>
        )}
      </Tabs>
    </WorkspaceShell>
  )
}

/** 一个 tab 的 jobs 网格: jobs 非空时渲染 2 列 JobCard 网格, 空时显示传入的 emptyState.
 *  "全部" tab + 每个 category tab 共用. */
function JobsGrid({
  jobs,
  pending,
  onAction,
  emptyState,
}: {
  jobs: SchedulerJobItem[]
  pending: ActionState
  onAction: (jobId: string, action: ActionKey) => void
  emptyState: React.ReactNode
}) {
  if (jobs.length === 0) return <>{emptyState}</>
  return (
    <div className="columns-1 gap-4 md:columns-2 2xl:columns-3">
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          pending={pending[job.id] ?? null}
          onAction={onAction}
        />
      ))}
    </div>
  )
}

function DailyStatsChart({ items }: { items: SchedulerDailyStatItem[] }) {
  const maxTotal = Math.max(1, ...items.map((item) => item.total || 0))

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-7 gap-2 md:grid-cols-14">
        {items.map((item) => {
          const totalHeight = Math.max(10, Math.round((item.total / maxTotal) * 100))
          const failedHeight =
            item.total > 0
              ? Math.max(
                  item.failed > 0 ? 6 : 0,
                  Math.round((item.failed / maxTotal) * 100),
                )
              : 0
          const skippedHeight =
            item.total > 0
              ? Math.max(
                  item.skipped > 0 ? 6 : 0,
                  Math.round((item.skipped / maxTotal) * 100),
                )
              : 0
          const successHeight = Math.max(0, totalHeight - failedHeight - skippedHeight)

          return (
            <div key={item.date} className="space-y-1">
              <div className="group flex h-36 flex-col justify-end rounded-2xl border border-border/30 bg-background/70 px-2 py-2">
                <div className="relative mx-auto flex h-24 w-full max-w-[18px] flex-col justify-end overflow-hidden rounded-full bg-muted">
                  {successHeight > 0 ? (
                    <div
                      className="w-full bg-emerald-500/85 transition-opacity group-hover:opacity-90"
                      style={{ height: `${successHeight}px` }}
                    />
                  ) : null}
                  {skippedHeight > 0 ? (
                    <div
                      className="w-full bg-amber-400/90 transition-opacity group-hover:opacity-95"
                      style={{ height: `${skippedHeight}px` }}
                    />
                  ) : null}
                  {failedHeight > 0 ? (
                    <div
                      className="w-full bg-red-500/90 transition-opacity group-hover:opacity-95"
                      style={{ height: `${failedHeight}px` }}
                    />
                  ) : null}
                </div>
                <div className="mt-2 space-y-1 text-center">
                  <div className="text-[11px] font-semibold tabular-nums text-foreground">
                    {item.total}
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {item.date.slice(5)}
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-border/20 bg-muted/20 px-2 py-1 text-[10px] leading-4 text-muted-foreground">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1">
                    <CalendarDays className="size-2.5" />
                    成功
                  </span>
                  <span className="tabular-nums">{item.success}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span>失败</span>
                  <span className="tabular-nums text-red-600">{item.failed}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span>跳过</span>
                  <span className="tabular-nums text-amber-600">{item.skipped}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block size-2 rounded-full bg-emerald-500/85" />
          成功
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block size-2 rounded-full bg-amber-400/90" />
          跳过
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block size-2 rounded-full bg-red-500/90" />
          失败
        </span>
      </div>
    </div>
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
    <Card className="border-0 bg-muted/60 shadow-none py-0">
      <CardContent className="flex items-center gap-3 px-4 py-4">
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
