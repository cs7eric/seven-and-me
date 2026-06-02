import type { Phase, SSEEvent, QAResponse, TransferProgress } from "./types";
import type { MP4HistoryListItem, MP4HistoryRecord } from "./history-types";
import type { StockAdjust, StockAnnotation, StockAuctionSnapshot, StockKlineBar, StockPeriod, StockSearchItem, StockTargetType, StockWorkspace, ApplicationAnalysisResponse } from "@/views/stock-chart/lib/types";

const API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) || "http://localhost:5000";
const DOWNLOADER_API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_DOWNLOADER_API_BASE) || "https://downloader-api.bhwa233.com";

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
