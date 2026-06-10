import type { Phase, SSEEvent, QAResponse, TransferProgress } from "./types";
import type { MP4HistoryListItem, MP4HistoryRecord } from "./history-types";
import type { StockAdjust, StockAnnotation, StockAuctionSnapshot, StockIntradayResponse, StockKlineBar, StockPeriod, StockSearchItem, StockTargetType, StockWorkspace, ApplicationAnalysisResponse } from "@/views/stock-chart/lib/types";
import type { ApplicationAnalysisDailySnapshot } from "@/views/application-analysis/lib/types";
import type {
  IndustryApplicationConfig,
  IndustryApplicationIndicators,
  IndustryApplicationIndexBar,
  IndustryApplicationKlinePayload,
  IndustryApplicationOverviewResponse,
  IndustryApplicationTargetCode,
  MarketHeatmapResponse,
} from "@/views/industry-application/lib/types";

const API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) || "http://localhost:5000";
const DOWNLOADER_API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_DOWNLOADER_API_BASE) || "https://downloader-api.bhwa233.com";

export type { MP4HistoryListItem, MP4HistoryRecord } from "./history-types";

export interface DownloaderPageInfo {
  page: number;
  cid: string;
  part: string;
  duration: number;
  downloadAudioUrl: string | null;
  downloadVideoUrl: string | null;
}

export interface DownloaderEmbeddedVideoInfo {
  id: string;
  title: string;
  cover?: string | null;
  duration?: number;
  downloadVideoUrl?: string | null;
  downloadAudioUrl?: string | null;
}

export interface DownloaderParseData {
  title: string;
  desc?: string;
  cover?: string | null;
  platform: string;
  downloadAudioUrl: string | null;
  downloadVideoUrl: string | null;
  originDownloadAudioUrl?: string | null;
  originDownloadVideoUrl?: string | null;
  url: string;
  duration?: number;
  isMultiPart?: boolean;
  currentPage?: number;
  pages?: DownloaderPageInfo[];
  noteType?: "video" | "image" | "audio";
  images?: Array<string | { index?: number; url?: string | null; downloadUrl?: string | null }>;
  videos?: DownloaderEmbeddedVideoInfo[];
}

export interface RemoteParsePayload {
  downloadUrl: string;
  title?: string;
  sourceUrl?: string;
  metadata?: Record<string, unknown>;
}

export interface TaskSnapshot {
  task_id: string;
  status: Phase | string;
  transcript: string;
  polished: string;
  summary: string;
  metadata: Record<string, unknown>;
  file_name: string;
  error?: string | null;
  download_progress: TransferProgress;
  intake_progress: TransferProgress;
}

interface DownloaderParseResponse {
  success: boolean;
  data?: DownloaderParseData;
  error?: string;
  message?: string;
}

export async function uploadFile(file: File): Promise<string> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/transcribe`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "上传失败" }));
    throw new Error(err.error || "上传失败");
  }

  const data = await res.json();
  return data.task_id as string;
}

export function uploadFileWithProgress(file: File, onProgress: (progress: TransferProgress) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    const startedAt = Date.now();

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const elapsed = Math.max((Date.now() - startedAt) / 1000, 0.001);
      const speed = event.loaded / elapsed;
      onProgress({
        phase: "uploading",
        progress: Math.round((event.loaded / event.total) * 100),
        processed_bytes: event.loaded,
        total_bytes: event.total,
        eta_seconds: speed > 0 ? Math.round((event.total - event.loaded) / speed) : null,
        speed_bytes_per_sec: Math.round(speed),
      });
    };

    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300 && data.task_id) {
        onProgress({
          phase: "done",
          progress: 100,
          processed_bytes: file.size,
          total_bytes: file.size,
          eta_seconds: 0,
        });
        resolve(data.task_id);
        return;
      }
      reject(new Error(data.error || "上传失败"));
    };

    xhr.onerror = () => reject(new Error("上传失败"));
    xhr.open("POST", `${API_BASE}/api/transcribe`);
    xhr.send(formData);
  });
}

export function createSSEConnection(
  taskId: string,
  callbacks: {
    onEvent: (event: SSEEvent) => void;
    onError?: (err: string) => void;
    onDone?: () => void;
  }
): EventSource {
  const es = new EventSource(`${API_BASE}/api/stream/${taskId}`);

  es.onmessage = (e) => {
    try {
      const event: SSEEvent = JSON.parse(e.data);
      callbacks.onEvent(event);

      if (event.type === "done") {
        callbacks.onDone?.();
        es.close();
      }
    } catch {
      return;
    }
  };

  es.onerror = () => {
    callbacks.onError?.("SSE disconnected");
    es.close();
  };

  return es;
}

export async function fetchTaskSnapshot(taskId: string): Promise<TaskSnapshot> {
  const res = await fetch(`${API_BASE}/api/task/${taskId}`, {
    method: "GET",
    cache: "no-store",
  });

  const data = (await res.json().catch(() => null)) as TaskSnapshot | { error?: string } | null;

  if (!res.ok || !data || !("task_id" in data)) {
    throw new Error((data && "error" in data && data.error) || "获取任务状态失败");
  }

  return data;
}

export async function searchStockChart(query: string): Promise<StockSearchItem[]> {
  const res = await fetch(`${API_BASE}/api/stock-chart/search?q=${encodeURIComponent(query)}`);
  const data = (await res.json().catch(() => null)) as { items?: StockSearchItem[] } | null;
  if (!res.ok || !data) throw new Error("搜索股票失败");
  return data.items || [];
}

export async function fetchStockKlines(params: {
  targetType: StockTargetType;
  symbol: string;
  name?: string;
  period: StockPeriod;
  adjust: StockAdjust;
}): Promise<{ symbol: string; target_type: StockTargetType; period: StockPeriod; adjust: StockAdjust; items: StockKlineBar[] }> {
  const query = new URLSearchParams({
    target_type: params.targetType,
    symbol: params.symbol,
    name: params.name || params.symbol,
    period: params.period,
    adjust: params.adjust,
  });
  const res = await fetch(`${API_BASE}/api/stock-chart/klines?${query.toString()}`);
  const data = (await res.json().catch(() => null)) as { symbol: string; target_type: StockTargetType; period: StockPeriod; adjust: StockAdjust; items: StockKlineBar[] } | null;
  if (!res.ok || !data) throw new Error("获取K线失败");
  return data;
}

export async function fetchStockWorkspace(targetType: StockTargetType, symbol: string, name?: string): Promise<StockWorkspace> {
  const query = new URLSearchParams({ target_type: targetType, symbol, name: name || symbol });
  const res = await fetch(`${API_BASE}/api/stock-chart/workspace?${query.toString()}`);
  const data = (await res.json().catch(() => null)) as StockWorkspace | null;
  if (!res.ok || !data) throw new Error("获取图表工作区失败");
  return data;
}

export async function saveStockWorkspace(payload: Omit<StockWorkspace, "id" | "updated_at"> & { name?: string }): Promise<StockWorkspace> {
  const res = await fetch(`${API_BASE}/api/stock-chart/workspace`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => null)) as StockWorkspace | null;
  if (!res.ok || !data) throw new Error("保存图表工作区失败");
  return data;
}

export async function listStockAnnotations(targetType: StockTargetType, symbol: string, period: string): Promise<StockAnnotation[]> {
  const query = new URLSearchParams({ target_type: targetType, symbol, period });
  const res = await fetch(`${API_BASE}/api/stock-chart/annotations?${query.toString()}`);
  const data = (await res.json().catch(() => null)) as { items?: StockAnnotation[] } | null;
  if (!res.ok || !data) throw new Error("获取标记失败");
  return data.items || [];
}

export async function createStockAnnotation(payload: {
  target_type: StockTargetType;
  symbol: string;
  period: string;
  overlay_type: string;
  points: Array<{ timestamp: number; value: number }>;
  styles?: Record<string, unknown>;
  text?: string;
}): Promise<StockAnnotation> {
  const res = await fetch(`${API_BASE}/api/stock-chart/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => null)) as StockAnnotation | null;
  if (!res.ok || !data) throw new Error("创建标记失败");
  return data;
}

export async function deleteStockAnnotation(targetType: StockTargetType, symbol: string, period: string, annotationId: string): Promise<void> {
  const query = new URLSearchParams({ target_type: targetType, symbol, period });
  const res = await fetch(`${API_BASE}/api/stock-chart/annotations/${encodeURIComponent(annotationId)}?${query.toString()}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("删除标记失败");
}

export async function fetchStockAuction(symbol: string): Promise<StockAuctionSnapshot> {
  const res = await fetch(`${API_BASE}/api/stock-chart/auction?symbol=${encodeURIComponent(symbol)}`);
  const data = (await res.json().catch(() => null)) as StockAuctionSnapshot | null;
  if (!res.ok || !data) throw new Error("获取竞价数据失败");
  return data;
}

export async function fetchStockIntraday(params: {
  targetType: StockTargetType
  symbol: string
  name?: string
  adjust: StockAdjust
  tradeDate?: string
  periods?: StockPeriod[]
}): Promise<StockIntradayResponse> {
  const query = new URLSearchParams({
    target_type: params.targetType,
    symbol: params.symbol,
    name: params.name || params.symbol,
    adjust: params.adjust,
  })
  if (params.tradeDate) query.set("trade_date", params.tradeDate)
  if (params.periods && params.periods.length) {
    query.set("periods", params.periods.join(","))
  }
  const res = await fetch(`${API_BASE}/api/stock-chart/intraday?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as StockIntradayResponse | null
  if (!res.ok || !data?.ok) {
    throw new Error(data?.error || "获取当日分时失败")
  }
  return data
}

export interface AuctionAiAnalysisResponse {
  analysis_input: Record<string, unknown>
  analysis_result: Record<string, unknown>
  raw_result?: Record<string, unknown>
  raw_root_keys?: string[] | null
  dump_paths?: Record<string, string>
}

export async function runAuctionAiAnalysis(params: {
  targetType: StockTargetType
  symbol: string
  name: string
  adjust: StockAdjust
  maxChars?: number
}): Promise<AuctionAiAnalysisResponse> {
  const res = await fetch(`${API_BASE}/api/stock-chart/auction-ai-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_type: params.targetType,
      symbol: params.symbol,
      name: params.name,
      adjust: params.adjust,
      max_chars: params.maxChars || 1000000,
    }),
  })
  const data = (await res.json().catch(() => null)) as AuctionAiAnalysisResponse | { error?: string } | null
  if (!res.ok || !data || !("analysis_result" in data)) {
    throw new Error((data && "error" in data && data.error) || "竞价 AI 分析失败")
  }
  return data
}

export async function fetchAuctionAiAnalysisSnapshot(params: {
  targetType: StockTargetType
  symbol: string
  date?: string
}): Promise<AuctionAiAnalysisResponse & { ok?: boolean; has_snapshot?: boolean; date?: string; updated_at?: string }> {
  const query = new URLSearchParams({
    target_type: params.targetType,
    symbol: params.symbol,
  })
  if (params.date) query.set("date", params.date)
  const res = await fetch(`${API_BASE}/api/stock-chart/auction-ai-analysis?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as (AuctionAiAnalysisResponse & { error?: string; ok?: boolean; has_snapshot?: boolean }) | null
  if (!res.ok || !data || !("analysis_result" in data)) {
    throw new Error(data?.error || "读取竞价 AI 分析结果失败")
  }
  return data
}

export async function triggerAuctionAiAnalysisScheduler(): Promise<{
  ok?: boolean
  status?: string
  date?: string
  succeeded?: number
  failed?: number
  items?: Array<Record<string, unknown>>
  error?: string
}> {
  const res = await fetch(`${API_BASE}/api/stock-chart/auction-ai-analysis/scheduler/trigger`, {
    method: "POST",
  })
  return (await res.json().catch(() => ({}))) as {
    ok?: boolean
    status?: string
    date?: string
    succeeded?: number
    failed?: number
    items?: Array<Record<string, unknown>>
    error?: string
  }
}

export interface StockMetaResponse {
  symbol: string
  name: string
  totalMarketCap: number
  circMarketCap: number
  industry: string
  capStyle: "large" | "mid" | "small" | "micro" | null
  sectorIndexSymbol?: string | null
  sectorIndexName?: string | null
}

export async function fetchStockMeta(params: {
  targetType: StockTargetType
  symbol: string
}): Promise<StockMetaResponse> {
  const query = new URLSearchParams({
    target_type: params.targetType,
    symbol: params.symbol,
  })
  const res = await fetch(`${API_BASE}/api/stock-chart/stock-meta?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as StockMetaResponse | null
  if (!res.ok || !data) throw new Error("获取股票元数据失败")
  return data
}

export async function fetchMarketBreadth(): Promise<{
  upCount: number | null
  downCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  breakRate: number | null
  maxLianBan: number | null
  yesterdayLimitUpReturn: number | null
  totalTurnover: number | null
  downOver5Count: number | null
  new20HighCount: number | null
  new20LowCount: number | null
}> {
  const res = await fetch(`${API_BASE}/api/stock-chart/market-breadth`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取市场情绪数据失败")
  return {
    upCount: (data.upCount as number) ?? null,
    downCount: (data.downCount as number) ?? null,
    limitUpCount: (data.limitUpCount as number) ?? null,
    limitDownCount: (data.limitDownCount as number) ?? null,
    breakRate: (data.breakRate as number) ?? null,
    maxLianBan: (data.maxLianBan as number) ?? null,
    yesterdayLimitUpReturn: (data.yesterdayLimitUpReturn as number) ?? null,
    totalTurnover: (data.totalTurnover as number) ?? null,
    downOver5Count: (data.downOver5Count as number) ?? null,
    new20HighCount: (data.new20HighCount as number) ?? null,
    new20LowCount: (data.new20LowCount as number) ?? null,
  }
}

export async function fetchMarketBreadthSeries(): Promise<Array<{
  upCount: number | null
  downCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  totalCount: number | null
  breakRate: number | null
  maxLianBan: number | null
  yesterdayLimitUpReturn: number | null
  totalTurnover: number | null
  downOver5Count: number | null
  new20HighCount: number | null
  new20LowCount: number | null
  date: string
}>> {
  const res = await fetch(`${API_BASE}/api/stock-chart/market-breadth-series`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取市场情绪序列数据失败")
  return ((data.items as Array<Record<string, unknown>>) ?? []).map((item) => ({
    upCount: (item.upCount as number) ?? null,
    downCount: (item.downCount as number) ?? null,
    limitUpCount: (item.limitUpCount as number) ?? null,
    limitDownCount: (item.limitDownCount as number) ?? null,
    totalCount: (item.totalCount as number) ?? null,
    breakRate: (item.breakRate as number) ?? null,
    maxLianBan: (item.maxLianBan as number) ?? null,
    yesterdayLimitUpReturn: (item.yesterdayLimitUpReturn as number) ?? null,
    totalTurnover: (item.totalTurnover as number) ?? null,
    downOver5Count: (item.downOver5Count as number) ?? null,
    new20HighCount: (item.new20HighCount as number) ?? null,
    new20LowCount: (item.new20LowCount as number) ?? null,
    date: String(item.date ?? ""),
  }))
}

export async function runApplicationAnalysis(params: {
  targetType: StockTargetType
  symbol: string
  name: string
  adjust: StockAdjust
}): Promise<ApplicationAnalysisResponse> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_type: params.targetType,
      symbol: params.symbol,
      name: params.name,
      adjust: params.adjust,
    }),
  })
  const data = (await res.json().catch(() => null)) as ApplicationAnalysisResponse | { error?: string } | null
  if (!res.ok || !data || !("analysis_result" in data)) {
    throw new Error((data && "error" in data && data.error) || "Application Analysis 失败")
  }
  return data
}

export interface ApplicationAnalysisTarget {
  id: string
  target_type: StockTargetType | string
  symbol: string
  name: string
  adjust: string
  enabled: boolean
  interval_minutes: number
  tags?: string[]
  last_updated_at?: string | null
  last_result_path?: string | null
}

export interface ApplicationAnalysisSchedulerStatus {
  running: boolean
  started_at?: string | null
  tick_count?: number
  runs_count?: number
  enabled_target_count?: number
  total_target_count?: number
  inflight?: Record<string, string>
  last_run?: Record<string, { status: string; finished_at?: string; elapsed_seconds?: number; overlay_count?: number; error?: string }>
}

export interface ApplicationAnalysisResultFile {
  filename: string
  path: string
  size_bytes: number
  updated_at: string
}

export async function fetchApplicationAnalysisTargets(): Promise<{ items: ApplicationAnalysisTarget[]; config: Record<string, unknown> }> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/targets`)
  return (await res.json()) as { items: ApplicationAnalysisTarget[]; config: Record<string, unknown> }
}

export async function saveApplicationAnalysisTargets(payload: { horizon: Record<string, number>; items: ApplicationAnalysisTarget[] }): Promise<{ ok: boolean; config: Record<string, unknown> }> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/targets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  return (await res.json()) as { ok: boolean; config: Record<string, unknown> }
}

export async function fetchApplicationAnalysisResult(targetId: string): Promise<ApplicationAnalysisResponse & { _meta_result_path: string; _meta_history: ApplicationAnalysisResultFile[] }> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/results/${encodeURIComponent(targetId)}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取分析结果失败")
  }
  return (await res.json()) as ApplicationAnalysisResponse & { _meta_result_path: string; _meta_history: ApplicationAnalysisResultFile[] }
}

export async function triggerApplicationAnalysis(targetId: string | null): Promise<{ ok: boolean; target_id?: string; error?: string; items?: unknown[] }> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: targetId || null }),
  })
  return (await res.json()) as { ok: boolean; target_id?: string; error?: string; items?: unknown[] }
}

export async function fetchApplicationAnalysisSchedulerStatus(): Promise<ApplicationAnalysisSchedulerStatus> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/scheduler`)
  return (await res.json()) as ApplicationAnalysisSchedulerStatus
}

export interface ApplicationAnalysisDailySnapshotFile {
  filename: string
  path: string
  date: string
  size_bytes: number
  updated_at: string
}

export interface ApplicationAnalysisDailySnapshotResponse {
  ok: boolean
  error?: string
  target_id?: string
  date?: string
  snapshot_path?: string
  short_term_trend?: Record<string, unknown> | null
  current_situation?: Record<string, unknown> | null
  snapshots?: ApplicationAnalysisDailySnapshotFile[]
  snapshot?: {
    target: Record<string, unknown>
    date: string
    updated_at: string
    short_term_trend?: Record<string, unknown> | null
    current_situation?: Record<string, unknown> | null
    summary?: Record<string, unknown> | null
  }
}

export async function refreshApplicationAnalysisRecent30(
  targetId: string,
  date?: string,
): Promise<ApplicationAnalysisDailySnapshotResponse> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/recent30/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(date ? { target_id: targetId, date } : { target_id: targetId }),
  })
  return (await res.json()) as ApplicationAnalysisDailySnapshotResponse
}

export async function listApplicationAnalysisRecent30(
  targetId: string,
  limit = 60,
): Promise<ApplicationAnalysisDailySnapshotResponse> {
  const res = await fetch(
    `${API_BASE}/api/stock-chart/application-analysis/recent30/${encodeURIComponent(targetId)}?limit=${encodeURIComponent(String(limit))}`,
  )
  return (await res.json()) as ApplicationAnalysisDailySnapshotResponse
}

export async function readApplicationAnalysisRecent30(
  targetId: string,
  date: string,
): Promise<ApplicationAnalysisDailySnapshotResponse> {
  const res = await fetch(
    `${API_BASE}/api/stock-chart/application-analysis/recent30/${encodeURIComponent(targetId)}/${encodeURIComponent(date)}`,
  )
  return (await res.json()) as ApplicationAnalysisDailySnapshotResponse
}

export async function controlApplicationAnalysisScheduler(action: "start" | "stop"): Promise<{ ok: boolean; status: ApplicationAnalysisSchedulerStatus }> {
  const res = await fetch(`${API_BASE}/api/stock-chart/application-analysis/scheduler/${action}`, { method: "POST" })
  return (await res.json()) as { ok: boolean; status: ApplicationAnalysisSchedulerStatus }
}

export async function fetchMarketOverview(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/api/stock-chart/market-overview`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取市场概览失败")
  return data
}

// =============================================================================
// Stock Overview · Market Pulse
// =============================================================================
export type MarketPulseOptions = {
  /** 刷新今日轮动快照并落盘 (其它历史日期不动). */
  refreshRotation?: boolean
  /** 行业轮动返回的交易日数. 默认 10. */
  days?: number
  /** 强势板块 / 行业轮动 Top N. 默认 10. */
  topN?: number
}

export async function fetchMarketPulse(
  options: MarketPulseOptions = {}
): Promise<Record<string, unknown>> {
  const params = new URLSearchParams()
  if (options.refreshRotation) params.set("refresh", "1")
  if (options.days)            params.set("days", String(options.days))
  if (options.topN)            params.set("topN", String(options.topN))
  const qs = params.toString()
  const url = `${API_BASE}/api/stock-chart/market-pulse/all${qs ? `?${qs}` : ""}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取 Market Pulse 失败")
  return data
}

export interface StyleSectorItem {
  name: string
  change_pct: number | null
  valid_size: number
  sample_size: number
}

export interface StyleSectorListResponse {
  ok: boolean
  items: StyleSectorItem[]
  count: number
  names: string[]
  error?: string
}

export async function fetchStyleSectors(): Promise<StyleSectorListResponse> {
  const url = `${API_BASE}/api/stock-chart/style-sectors`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as StyleSectorListResponse | null
  if (!res.ok || !data) throw new Error("获取风格板块失败")
  return data
}

export async function fetchMarketPulseRotationTrend(
  days = 10,
  topN = 10
): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/rotation-trend?days=${days}&topN=${topN}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取轮动趋势失败")
  return data
}

export async function fetchIndustryDetail(
  name: string,
  topN = 30
): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/industry-detail?name=${encodeURIComponent(name)}&topN=${topN}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error(`获取行业 ${name} 详情失败`)
  return data
}

export interface IndustryFundFlowRow {
  /** 排名 (1..N, 按净额 desc 重排) */
  "序号": number
  /** 行业名称, e.g. "半导体" */
  "行业": string
  /**
   * 行业 code (6 位, e.g. "881121")
   * 后端 fund-flow 端点 enrich 进去的, 前端 drawer 拿它直接调 constituents 接口,
   * 不再走 name → code 解析
   */
  "code"?: string | null
  /** 行业指数涨跌幅 % */
  "行业指数涨跌幅": number | string | null
  /** 流入资金(亿) */
  "流入资金(亿)": number | string | null
  /** 流出资金(亿) */
  "流出资金(亿)": number | string | null
  /** 净额(亿), 正=净流入 */
  "净额(亿)": number | string | null
  /** 公司家数 */
  "公司家数": number | string | null
  /** 领涨股名称 */
  "领涨股": string | null
  /** 领涨股涨跌幅 % */
  "领涨股涨跌幅": number | string | null
  /** 领涨股当前价(元) */
  "当前价(元)": number | string | null
}

export interface IndustryFundFlowResponse {
  ok: boolean
  rowCount: number
  totalPages: number | null
  pageRowCounts: number[]
  fetchedAt: string | null
  rows: IndustryFundFlowRow[]
  stale?: boolean
  staleReason?: string
  error?: string
}

export async function fetchIndustryFundFlow(
  options: { refresh?: boolean; top?: number } = {}
): Promise<IndustryFundFlowResponse> {
  const params: string[] = []
  if (options.refresh) params.push("refresh=1")
  if (options.top) params.push(`top=${options.top}`)
  const query = params.length ? `?${params.join("&")}` : ""
  const url = `${API_BASE}/api/stock-chart/ths-industry/fund-flow${query}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as IndustryFundFlowResponse | null
  if (!res.ok || !data) throw new Error("获取同花顺行业资金失败")
  return data
}

export async function refreshIndustryFundFlow(): Promise<IndustryFundFlowResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/fund-flow/refresh`
  const res = await fetch(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as IndustryFundFlowResponse | null
  if (!res.ok || !data) throw new Error("刷新同花顺行业资金失败")
  return data
}

export async function fetchIndustryFundFlowHistory(date?: string): Promise<Record<string, unknown>> {
  const url = date
    ? `${API_BASE}/api/stock-chart/ths-industry/fund-flow/history?date=${encodeURIComponent(date)}`
    : `${API_BASE}/api/stock-chart/ths-industry/fund-flow/history`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取行业资金历史失败")
  return data
}

// ---------------------------------------------------------------------------
// 同花顺行业成分股 (hexin-v 破解, q.10jqka 翻全页)  14 列定义见下面 ``IndustryConstituentRow``
// ---------------------------------------------------------------------------
export interface IndustryConstituentsResponse {
  ok: boolean
  code: string
  totalPages: number
  pageRowCounts: number[]
  fetchedAt: string
  rowCount: number
  rows: IndustryConstituentRow[]
  stale?: boolean
  staleReason?: string
  error?: string
}

export async function fetchIndustryConstituentsByCode(
  code: string,
  options: { refresh?: boolean } = {},
): Promise<IndustryConstituentsResponse> {
  const params: string[] = []
  if (options.refresh) params.push("refresh=1")
  const query = params.length ? `?${params.join("&")}` : ""
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-by-code?code=${encodeURIComponent(code)}${query}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as IndustryConstituentsResponse | null
  if (!res.ok || !data) throw new Error(`获取行业 ${code} 成分股失败`)
  return data
}

export async function refreshIndustryConstituentsByCode(code: string): Promise<IndustryConstituentsResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-by-code/refresh?code=${encodeURIComponent(code)}`
  const res = await fetch(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as IndustryConstituentsResponse | null
  if (!res.ok || !data) throw new Error(`刷新行业 ${code} 成分股失败`)
  return data
}

export async function fetchCachedIndustryConstituentsCodes(): Promise<{ ok: boolean; codes: string[] }> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-by-code/cached`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as { ok: boolean; codes: string[] } | null
  if (!res.ok || !data) throw new Error("获取已落盘行业 code 失败")
  return data
}

// ---------------------------------------------------------------------------
// 同花顺行业成分股 (按 name 查, 内部走 hexin-v 破解新版)
// 路由: GET /api/stock-chart/ths-industry/constituents?name=...
// 返回: { ok, name, code, totalPages, pageRowCounts, count, rows, fetchedAt }
// rows 跟上面 IndustryConstituentRow 14 列一致
// ---------------------------------------------------------------------------
export interface IndustryConstituentsByNameResponse {
  ok: boolean
  name: string
  code: string
  totalPages: number
  pageRowCounts: number[]
  count: number
  rows: IndustryConstituentRow[]
  fetchedAt: string | null
  error?: string
  stale?: boolean
  staleReason?: string
}

export async function fetchIndustryConstituentsByName(
  name: string,
  options: { refresh?: boolean } = {},
): Promise<IndustryConstituentsByNameResponse> {
  const params: string[] = []
  if (options.refresh) params.push("refresh=1")
  const query = params.length ? `?${params.join("&")}` : ""
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents?name=${encodeURIComponent(name)}${query}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as IndustryConstituentsByNameResponse | null
  if (!res.ok || !data) throw new Error(`获取行业 ${name} 成分股失败`)
  return data
}

export async function refreshIndustryConstituentsByName(
  name: string
): Promise<IndustryConstituentsByNameResponse> {
  return fetchIndustryConstituentsByName(name, { refresh: true })
}

// ---------------------------------------------------------------------------
// 同花顺行业成分股 (纯读磁盘 join 视图, 不爬网络)
// 路由: GET /api/stock-chart/ths-industry/constituents-file?code=...&name=...
//   - 传 code: ?code=881157  (推荐, 6 位数字, 无 name→code 解析)
//   - 传 name: ?name=半导体   (内部 name→code 解析一次)
// 数据源 (server 端 join):
//   - membership: reference/ths-industry/constituents_index.json (50 只 code)
//   - 14 列行情:  reference/stock-universe/ths_industry/constituents/{code}.json
// 适用: drawer 打开默认 (高频), 避免每次都打 q.10jqka
// 返回 404 表示索引里没这个 industry, 不 fallback 爬网络
// ---------------------------------------------------------------------------
export interface IndustryConstituentRow {
  "序号": number
  "代码": string
  "名称": string | null
  "现价": number | string | null
  "涨跌幅(%)": number | string | null
  "涨跌": number | string | null
  "涨速(%)": number | string | null
  "换手(%)": number | string | null
  "量比": number | string | null
  "振幅(%)": number | string | null
  "成交额": string | number | null
  "流通股": string | number | null
  "流通市值": string | number | null
  "市盈率": string | number | null
}

export interface IndustryConstituentsIndexResponse {
  ok: boolean
  name: string
  code: string
  /** index 里这个 industry 的 code 总数 */
  count: number
  /** 在 stock-universe 里实际命中行情的行数 */
  matched: number
  /** 索引文件自身的抓取时间 */
  indexFetchedAt: string | null
  /** 行情文件 (per-industry) 的抓取时间 */
  rowsFetchedAt: string | null
  rows: IndustryConstituentRow[]
  error?: string
}

/** 按 6 位 code 查 (推荐, URL 用 ?code=, 无 name→code 解析) */
export async function fetchIndustryConstituentsFromIndexByCode(
  code: string
): Promise<IndustryConstituentsIndexResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-file?code=${encodeURIComponent(code)}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as IndustryConstituentsIndexResponse | null
  if (!res.ok || !data) {
    const errMsg = (data && data.error) || `读取行业 ${code} 成分股失败`
    const err = new Error(errMsg) as Error & { code?: string }
    err.code = res.status === 404 ? "NOT_CACHED" : "FETCH_FAILED"
    throw err
  }
  return data
}

/** 按中文名查 (URL 用 ?name=, server 端 name→code 解析一次) */
export async function fetchIndustryConstituentsFromIndexByName(
  name: string
): Promise<IndustryConstituentsIndexResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-file?name=${encodeURIComponent(name)}`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as IndustryConstituentsIndexResponse | null
  if (!res.ok || !data) {
    const errMsg = (data && data.error) || `读取行业 ${name} 成分股失败`
    const err = new Error(errMsg) as Error & { code?: string }
    err.code = res.status === 404 ? "NOT_CACHED" : "FETCH_FAILED"
    throw err
  }
  return data
}

export async function fetchMarketPulseSchedulerStatus(): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse-scheduler/status`
  const res = await fetch(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取 scheduler 状态失败")
  return data
}

export async function triggerMarketPulseSnapshot(): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse-scheduler/trigger`
  const res = await fetch(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("手动触发 snapshot 失败")
  return data
}

export async function askQuestion(
  taskId: string,
  question: string
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, question }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "请求失败" }));
    throw new Error(err.error || "请求失败");
  }

  const data: QAResponse = await res.json();
  return data.answer;
}

export async function exportMarkdown(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/export-markdown/${taskId}`);
  if (!res.ok) throw new Error("导出失败");

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "transcription.md";
  a.click();
  URL.revokeObjectURL(url);
}

export async function checkStatus(): Promise<{
  api_configured: boolean;
  gpu_available: boolean;
  model_loaded: boolean;
  status: string;
}> {
  const res = await fetch(`${API_BASE}/api/status`);
  return res.json();
}

export async function parseDownloaderUrl(url: string): Promise<DownloaderParseData> {
  const params = new URLSearchParams({ url });
  const res = await fetch(`${DOWNLOADER_API_BASE}/api/parse?${params.toString()}`, {
    method: "GET",
    cache: "no-store",
  });

  const data = (await res.json().catch(() => null)) as DownloaderParseResponse | null;

  if (!data) {
    throw new Error("解析服务返回异常");
  }

  if (!res.ok || !data?.success || !data.data) {
    throw new Error(data?.error || data?.message || "解析失败");
  }

  return data.data;
}

export async function saveMP4History(taskId: string): Promise<MP4HistoryListItem> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });

  const data = (await res.json().catch(() => null)) as MP4HistoryListItem | { error?: string } | null;
  if (!res.ok || !data || !("id" in data)) {
    throw new Error((data && "error" in data && data.error) || "保存历史记录失败");
  }
  return data;
}

export async function listMP4History(): Promise<MP4HistoryListItem[]> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history`, { cache: "no-store" });
  const data = (await res.json().catch(() => null)) as { items?: MP4HistoryListItem[] } | null;
  if (!res.ok || !data) {
    throw new Error("获取历史记录失败");
  }
  return data.items || [];
}

export async function reorderMP4History(orderedIds: string[]): Promise<MP4HistoryListItem[]> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history/reorder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
  const data = (await res.json().catch(() => null)) as { items?: MP4HistoryListItem[]; error?: string } | null;
  if (!res.ok || !data) {
    throw new Error((data && data.error) || "更新历史顺序失败");
  }
  return data.items || [];
}

export async function deleteMP4History(historyId: string): Promise<{ id: string; title?: string }> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history/${historyId}`, {
    method: "DELETE",
  });
  const data = (await res.json().catch(() => null)) as { id?: string; title?: string; error?: string } | null;
  if (!res.ok || !data?.id) {
    throw new Error((data && data.error) || "删除历史记录失败");
  }
  return { id: data.id, title: data.title };
}

export async function askHistoryQuestion(historyId: string, question: string): Promise<{ id: string; question: string; answer: string; created_at: string }> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history/${historyId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const data = (await res.json().catch(() => null)) as { item?: { id: string; question: string; answer: string; created_at: string }; error?: string } | null;
  if (!res.ok || !data?.item) {
    throw new Error((data && data.error) || "历史记录 Ask AI 失败");
  }
  return data.item;
}

export async function getMP4History(id: string): Promise<MP4HistoryRecord> {
  const res = await fetch(`${API_BASE}/api/reference/mp4-history/${id}`, { cache: "no-store" });
  const data = (await res.json().catch(() => null)) as MP4HistoryRecord | { error?: string } | null;
  if (!res.ok || !data || !("task" in data)) {
    throw new Error((data && "error" in data && data.error) || "获取历史详情失败");
  }
  return data;
}

export async function sendDownloaderResultToParse(payload: RemoteParsePayload): Promise<{ task_id: string; file_name: string }> {
  const res = await fetch(`${API_BASE}/api/parse-video`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      download_url: payload.downloadUrl,
      title: payload.title,
      source_url: payload.sourceUrl,
      metadata: payload.metadata,
    }),
  });

  const data = (await res.json().catch(() => null)) as { task_id?: string; file_name?: string; error?: string } | null;

  if (!res.ok || !data?.task_id || !data.file_name) {
    throw new Error(data?.error || "Send to parse 失败");
  }

  return {
    task_id: data.task_id,
    file_name: data.file_name,
  };
}


export type ApplicationAnalysisRecent30FullItem = ApplicationAnalysisDailySnapshotFile & {
  snapshot: ApplicationAnalysisDailySnapshot
}

export type ApplicationAnalysisRecent30FullResponse = {
  ok: boolean
  target_id?: string
  items?: ApplicationAnalysisRecent30FullItem[]
  error?: string
}

export async function listApplicationAnalysisRecent30Full(
  targetId: string,
  limit = 60,
): Promise<ApplicationAnalysisRecent30FullResponse> {
  const res = await fetch(
    `${API_BASE}/api/stock-chart/application-analysis/recent30/${encodeURIComponent(targetId)}/full?limit=${encodeURIComponent(String(limit))}`,
  )
  return (await res.json()) as ApplicationAnalysisRecent30FullResponse
}

// ---------------------------------------------------------------------------
// Scheduler Management（/settings/scheduler 页面用）
// ---------------------------------------------------------------------------

export interface SchedulerJobItem {
  id: string
  name: string
  description?: string
  config_file?: string
  service_module?: string
  service_class?: string
  registered_at?: string
  supports_enable: boolean
  enabled: boolean
  config_enabled: boolean
  config: Record<string, unknown>
  live: Record<string, unknown>
}

export interface SchedulerJobsResponse {
  ok: boolean
  items: SchedulerJobItem[]
  count: number
  error?: string
}

export async function fetchSchedulerJobs(): Promise<SchedulerJobsResponse> {
  const res = await fetch(`${API_BASE}/api/scheduler/jobs`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as SchedulerJobsResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务列表失败")
  return data
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

async function postSchedulerAction(
  jobId: string,
  action: "enable" | "disable" | "trigger" | "start" | "stop",
): Promise<SchedulerJobActionResponse> {
  const res = await fetch(`${API_BASE}/api/scheduler/jobs/${encodeURIComponent(jobId)}/${action}`, {
    method: "POST",
  })
  const data = (await res.json().catch(() => null)) as SchedulerJobActionResponse | null
  if (!res.ok || !data) {
    throw new Error(data?.error || `调度任务 ${action} 失败`)
  }
  return data
}

export const enableSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "enable")
export const disableSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "disable")
export const triggerSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "trigger")
export const startSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "start")
export const stopSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "stop")

// ---------------------------------------------------------------------------
// Self-Selected（/stock-overview/self-selected 页面用）
// ---------------------------------------------------------------------------

export interface SelfSelectedGroup {
  id: string
  name: string
  description?: string | null
  color?: string
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

async function selfSelectedJson<T>(res: Response): Promise<T> {
  const data = (await res.json().catch(() => null)) as T | null
  if (!res.ok || !data) {
    const message =
      (data && typeof (data as { error?: string }).error === "string"
        ? (data as { error?: string }).error
        : null) || `request failed: ${res.status}`
    throw new Error(message)
  }
  return data
}

// group
export async function fetchSelfSelectedGroups(): Promise<SelfSelectedGroupListResponse> {
  return selfSelectedJson<SelfSelectedGroupListResponse>(
    await fetch(`${API_BASE}/api/self-selected/groups`, { cache: "no-store" }),
  )
}

export async function createSelfSelectedGroup(
  payload: { name: string; description?: string; color?: string },
): Promise<SelfSelectedGroupActionResponse> {
  return selfSelectedJson<SelfSelectedGroupActionResponse>(
    await fetch(`${API_BASE}/api/self-selected/groups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function updateSelfSelectedGroup(
  groupId: string,
  payload: Partial<Pick<SelfSelectedGroup, "name" | "description" | "color" | "sort_order">>,
): Promise<SelfSelectedGroupActionResponse> {
  return selfSelectedJson<SelfSelectedGroupActionResponse>(
    await fetch(`${API_BASE}/api/self-selected/groups/${encodeURIComponent(groupId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function deleteSelfSelectedGroup(groupId: string): Promise<SelfSelectedGroupActionResponse> {
  return selfSelectedJson<SelfSelectedGroupActionResponse>(
    await fetch(`${API_BASE}/api/self-selected/groups/${encodeURIComponent(groupId)}`, {
      method: "DELETE",
    }),
  )
}

// item
export async function fetchSelfSelectedItems(
  groupId?: string,
): Promise<SelfSelectedItemListResponse> {
  const url = groupId
    ? `${API_BASE}/api/self-selected/items?group_id=${encodeURIComponent(groupId)}`
    : `${API_BASE}/api/self-selected/items`
  return selfSelectedJson<SelfSelectedItemListResponse>(
    await fetch(url, { cache: "no-store" }),
  )
}

export async function createSelfSelectedItem(
  payload: { group_id: string; symbol: string; market?: string; name?: string; notes?: string },
): Promise<SelfSelectedItemActionResponse> {
  return selfSelectedJson<SelfSelectedItemActionResponse>(
    await fetch(`${API_BASE}/api/self-selected/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function deleteSelfSelectedItem(itemId: string): Promise<SelfSelectedItemActionResponse> {
  return selfSelectedJson<SelfSelectedItemActionResponse>(
    await fetch(`${API_BASE}/api/self-selected/items/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    }),
  )
}

// =============================================================================
// 行业 / 概念 应用面分析（独立于 application-analysis）
// =============================================================================

export async function fetchIndustryApplicationTargets(): Promise<IndustryApplicationConfig> {
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/targets`)
  return (await res.json()) as IndustryApplicationConfig
}

export async function saveIndustryApplicationTargets(payload: {
  horizon: { days: number; segments: number }
  items: IndustryApplicationConfig["items"]
}): Promise<IndustryApplicationConfig> {
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/targets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  return (await res.json()) as IndustryApplicationConfig
}

export async function fetchIndustryApplicationTargetCodes(): Promise<{
  items: IndustryApplicationTargetCode[]
  count: number
  source: string
}> {
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/target-codes`)
  return (await res.json()) as { items: IndustryApplicationTargetCode[]; count: number; source: string }
}

export async function fetchIndustryApplicationKline(
  target_type: "industry" | "concept",
  symbol: string,
  opts: { period?: string; count?: number } = {},
): Promise<IndustryApplicationKlinePayload> {
  const params = new URLSearchParams({ target_type, symbol })
  if (opts.period) params.set("period", opts.period)
  if (opts.count) params.set("count", String(opts.count))
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/kline?${params.toString()}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取行业 K 线失败")
  }
  return (await res.json()) as IndustryApplicationKlinePayload
}

export async function refreshIndustryApplication(targetId: string | null): Promise<{
  ok: boolean
  items?: { id: string; ok: boolean; kline_count?: number; error?: string }[]
  count?: number
  error?: string
}> {
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: targetId || null }),
  })
  return (await res.json()) as { ok: boolean; items?: { id: string; ok: boolean; kline_count?: number; error?: string }[]; count?: number; error?: string }
}

export async function fetchIndustryApplicationResult(targetId: string): Promise<{
  target: { id?: string; target_type?: string; symbol?: string; name?: string; tags?: string[] }
  updated_at: string
  kline: IndustryApplicationIndexBar[]
  indicators: IndustryApplicationIndicators
  meta?: Record<string, unknown>
}> {
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/results/${encodeURIComponent(targetId)}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取行业结果失败")
  }
  return (await res.json()) as { target: { id?: string; target_type?: string; symbol?: string; name?: string; tags?: string[] }; updated_at: string; kline: IndustryApplicationIndexBar[]; indicators: IndustryApplicationIndicators; meta?: Record<string, unknown> }
}

export async function fetchIndustryApplicationOverview(
  opts: { sort_by?: string; ascending?: boolean; count?: number } = {},
): Promise<IndustryApplicationOverviewResponse> {
  const params = new URLSearchParams()
  if (opts.sort_by) params.set("sort_by", opts.sort_by)
  if (opts.ascending != null) params.set("ascending", String(opts.ascending))
  if (opts.count) params.set("count", String(opts.count))
  const qs = params.toString()
  const res = await fetch(
    `${API_BASE}/api/stock-chart/industry-application/overview${qs ? `?${qs}` : ""}`,
  )
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取板块总览失败")
  }
  return (await res.json()) as IndustryApplicationOverviewResponse
}

export type HeatmapKind = "industries" | "concepts" | "styles"

export async function fetchMarketHeatmap(
  kind: HeatmapKind = "industries",
  top_n = 200
): Promise<MarketHeatmapResponse> {
  const params = new URLSearchParams({ kind, top_n: String(top_n) })
  const res = await fetch(`${API_BASE}/api/stock-chart/industry-application/heatmap?${params.toString()}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取市场热力图失败")
  }
  return (await res.json()) as MarketHeatmapResponse
}
