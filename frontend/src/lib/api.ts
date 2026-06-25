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
import type {
  IndustryCompareResponse,
  IndustryFundFlowIndustryListResponse,
} from "@/views/stock-overview/market-pulse/lib/types";

const API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) || "";
const DOWNLOADER_API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_DOWNLOADER_API_BASE) || "https://downloader-api.bhwa233.com";

// ---------------------------------------------------------------------------
// 请求重试: 失败时最多重试 3 次 (1 初始 + 3 重试 = 4 次总尝试, 指数退避).
// 触发重试: 网络异常 (fetch 抛错) / 5xx / 408 / 429. 其它 4xx 不重试.
// AI 分析相关 request 请走 `fetchWithRetry(url, init, { retry: false })`.
// ---------------------------------------------------------------------------
const RETRY_MAX_RETRIES = 3
const RETRY_BASE_DELAY_MS = 400

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isRetryableStatus(status: number): boolean {
  return status >= 500 || status === 408 || status === 429
}

export async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: RequestInit,
  options: { retry?: boolean; maxRetries?: number; baseDelayMs?: number } = {},
): Promise<Response> {
  const { retry = true, maxRetries = RETRY_MAX_RETRIES, baseDelayMs = RETRY_BASE_DELAY_MS } = options
  const maxAttempts = retry ? maxRetries + 1 : 1
  let lastError: unknown = null

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(input, init)
      if (!isRetryableStatus(res.status) || attempt === maxAttempts) {
        return res
      }
    } catch (err) {
      lastError = err
      if (attempt === maxAttempts) throw err
    }
    // 指数退避: 400ms, 800ms, 1600ms
    await sleep(baseDelayMs * Math.pow(2, attempt - 1))
  }

  throw lastError instanceof Error ? lastError : new Error("fetch failed")
}

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

  const res = await fetchWithRetry(`${API_BASE}/api/transcribe`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/task/${taskId}`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/search?q=${encodeURIComponent(query)}`);
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/klines?${query.toString()}`);
  const data = (await res.json().catch(() => null)) as { symbol: string; target_type: StockTargetType; period: StockPeriod; adjust: StockAdjust; items: StockKlineBar[] } | null;
  if (!res.ok || !data) throw new Error("获取K线失败");
  return data;
}

export async function fetchStockWorkspace(targetType: StockTargetType, symbol: string, name?: string): Promise<StockWorkspace> {
  const query = new URLSearchParams({ target_type: targetType, symbol, name: name || symbol });
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/workspace?${query.toString()}`);
  const data = (await res.json().catch(() => null)) as StockWorkspace | null;
  if (!res.ok || !data) throw new Error("获取图表工作区失败");
  return data;
}

export async function saveStockWorkspace(payload: Omit<StockWorkspace, "id" | "updated_at"> & { name?: string }): Promise<StockWorkspace> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/workspace`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/annotations?${query.toString()}`);
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/annotations`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/annotations/${encodeURIComponent(annotationId)}?${query.toString()}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("删除标记失败");
}

export async function fetchStockAuction(symbol: string): Promise<StockAuctionSnapshot> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/auction?symbol=${encodeURIComponent(symbol)}`);
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/intraday?${query.toString()}`)
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/stock-meta?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as StockMetaResponse | null
  if (!res.ok || !data) throw new Error("获取股票元数据失败")
  return data
}

// ---------------------------------------------------------------------------
// 个股所属行业 + 概念板块
// 来源: backend stock_universe sectors 落盘快照 (scheduler 从 eltdx 同步)
// endpoint: /api/stock-chart/f10/stock-sectors?symbol=xxx
// ---------------------------------------------------------------------------

export interface StockSectorEntry {
  name: string | null
  topic_id: string | null
  category_raw: number | null
  /** 当日板块涨跌幅 (%). 从 heatmap 快照按 name 匹配得到; 匹配不上时 null. */
  changePercent: number | null
  /** 来源标记: sectors = 落盘快照 / eltdx = live helpers.stock_topics. */
  source?: "sectors" | "eltdx" | null
}

export interface StockSectorsResponse {
  code: string
  industries: StockSectorEntry[]
  concepts: StockSectorEntry[]
  styles: StockSectorEntry[]
  count: number
  source: string
}

export async function fetchStockSectors(code: string): Promise<StockSectorsResponse> {
  const query = new URLSearchParams({ symbol: code })
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/f10/stock-sectors?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as StockSectorsResponse | null
  if (!res.ok || !data) throw new Error("获取股票所属行业/概念失败")
  return data
}

// ---------------------------------------------------------------------------
// F10 财务 / 估值 / 主营构成
// 全部走 backend/api/stock/f10.py (Flask Blueprint, 已在 bootstrap.py 注册)
// ---------------------------------------------------------------------------

export interface StockValuationRow {
  date: string
  peTtm: number | null
  peBfw: number | null
  pbMrq: number | null
  pbBfw: number | null
  pcfOcfTtm: number | null
  pcfBfw: number | null
  psTtm: number | null
  psBfw: number | null
  peg: number | null
  avgMarketCap: number | null
  aliqMarketCap: number | null
}

export interface StockValuationResponse {
  symbol: string
  reqId: string
  /** 取 raw.ResultSets[*] 解析后的近 N 期序列 (默认最多 5 期), 第一项是最新 */
  rows: StockValuationRow[]
  fetchedAt: string | null
  source: string
}

export interface StockFinanceReportRow {
  /** 报告期 yyyy-mm-dd */
  rq: string | null
  /** 原始 T0xx 字段, 名称随 report_type 变化, 解析时按需映射 */
  fields: Record<string, number | string | null>
}

export interface StockFinanceReportResponse {
  symbol: string
  reportType: "zcfzb" | "lrb" | "xjllb"
  /** 已解析为 {rq, fields} 形式, 按报告期倒序 */
  rows: StockFinanceReportRow[]
  fetchedAt: string | null
  source: string
}

export interface StockBusinessCompositionItem {
  /** 第一列通常是分类口径 ("按产品(项目)" / "按地区" ...) */
  category: string | null
  /** 第二列通常是行业/分类编号 */
  subType: number | string | null
  /** 名称 (e.g. 茅台酒 / 系列酒 / 国内) */
  name: string | null
  /** 主营收入 (元) */
  revenue: number | null
  /** 收入占比 (%) */
  ratio: number | null
  /** 其它原始列, 名字随接口变化 */
  extras: Array<number | string | null>
}

export interface StockBusinessCompositionResponse {
  symbol: string
  reportDate: string | null
  items: StockBusinessCompositionItem[]
  fetchedAt: string | null
  source: string
}

export interface StockProfitForecastItem {
  year: string
  /** 净利润预测 (元/万股, 来源字段不同) */
  netProfit: number | null
  /** 每股收益预测 (元) */
  eps: number | null
  /** 营收预测 (元) */
  revenue: number | null
  /** 其它原始列 */
  extras: Array<number | string | null>
}

export interface StockProfitForecastResponse {
  symbol: string
  items: StockProfitForecastItem[]
  fetchedAt: string | null
  source: string
}

// ---------- 公告 / 新闻 / 路演 / 研报 ----------

export interface StockAnnouncementItem {
  issueDate: string | null
  title: string | null
  typecode: string | null
  typename: string | null
  recId: string | null
  tableid: string | null
  url: string | null
  redistime: string | null
  source: string | null
}

export interface StockAnnouncementsResponse {
  symbol: string
  items: StockAnnouncementItem[]
  count: number
  fetchedAt: string | null
}

export interface StockNewsItem {
  issueDate: string | null
  title: string | null
  recId: string | null
  tableid: string | null
  redistime: string | null
  source: string | null
  relatecolumn: string | null
}

export interface StockNewsResponse {
  symbol: string
  items: StockNewsItem[]
  count: number
  fetchedAt: string | null
}

export interface StockRoadshowItem {
  title: string | null
  roadshowType: string | null
  startDate: string | null
  startTime: string | null
  endTime: string | null
  summary: string | null
  url: string | null
}

export interface StockRoadshowsResponse {
  symbol: string
  items: StockRoadshowItem[]
  count: number
  fetchedAt: string | null
}

export interface StockCompanyNewsItem {
  rating: string | null
  analysts: string | null
  recId: string | null
  issueDate: string | null
  title: string | null
  nflag: string | null
  docHash: string | null
}

export interface StockCompanyNewsResponse {
  symbol: string
  section: string
  items: StockCompanyNewsItem[]
  count: number
  fetchedAt: string | null
}

const F10_REQ_TIMEOUT_MS = 8000

function withTimeout(ms: number): { signal: AbortSignal } {
  const ctrl = new AbortController()
  setTimeout(() => ctrl.abort(), ms)
  return { signal: ctrl.signal }
}

/**
 * 通用 helper: 安全地把 unknown 转 number / string / null, 失败回 null
 */
function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null
  if (typeof v === "number" && Number.isFinite(v)) return v
  if (typeof v === "string") {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function toStr(v: unknown): string | null {
  if (v === null || v === undefined) return null
  return String(v)
}

/**
 * 从 f10 响应的 raw.ResultSets[*] 里把 Content[] 配 ColName[] 解析为 dict 列表
 */
function parseF10ResultSets(raw: unknown): Record<string, Record<string, unknown>>[] {
  if (!raw || typeof raw !== "object") return []
  const rs = (raw as { ResultSets?: Array<{ ColName?: string[]; Content?: unknown[][] }> }).ResultSets
  if (!Array.isArray(rs)) return []
  return rs.flatMap((t) => {
    const cols = Array.isArray(t.ColName) ? t.ColName : []
    const content = Array.isArray(t.Content) ? t.Content : []
    return content.map((row) => {
      const out: Record<string, unknown> = {}
      cols.forEach((col, i) => {
        out[col] = Array.isArray(row) ? row[i] : null
      })
      return out
    })
  })
}

/**
 * F10 /valuation: PE / PB / PS / PCF / PEG + 总市值 / 流通市值
 * 拿第一个 ResultSet 的最近几期 (默认 5)
 */
export async function fetchStockValuation(
  symbol: string,
  options: { reqId?: string; limit?: number } = {},
): Promise<StockValuationResponse> {
  const params = new URLSearchParams({ symbol })
  if (options.reqId) params.set("req_id", options.reqId)
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/valuation?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取估值数据失败")

  const parsed = parseF10ResultSets(data.raw).filter((r) => "DATE" in r)
  const limit = options.limit ?? 5
  const rows: StockValuationRow[] = parsed.slice(0, limit).map((r) => ({
    date: toStr(r.DATE) ?? "",
    peTtm: toNum(r.PETTM),
    peBfw: toNum(r.PEBFW),
    pbMrq: toNum(r.PBMRQ),
    pbBfw: toNum(r.PBBFW),
    pcfOcfTtm: toNum(r.PCFOCFTTM),
    pcfBfw: toNum(r.PCFBFW),
    psTtm: toNum(r.PSTTM),
    psBfw: toNum(r.PSBFW),
    peg: toNum(r.PEG),
    avgMarketCap: toNum(r.AVGMVM),
    aliqMarketCap: toNum(r.ALIQMV),
  }))

  return {
    symbol: toStr(data.symbol) ?? symbol,
    reqId: toStr(data.req_id) ?? "200191",
    rows,
    fetchedAt: toStr(data.fetched_at),
    source: toStr(data.source) ?? "eltdx",
  }
}

/**
 * F10 /finance-report: 资产负债表 (zcfzb) / 利润表 (lrb) / 现金流量表 (xjllb)
 * 字段名是 T0xx, 直接给前端用, 字段名映射留给上层
 */
export async function fetchStockFinanceReport(
  symbol: string,
  reportType: "zcfzb" | "lrb" | "xjllb" = "zcfzb",
): Promise<StockFinanceReportResponse> {
  const params = new URLSearchParams({ symbol, report_type: reportType })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/finance-report?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取财务报表失败")

  const parsed = parseF10ResultSets(data.raw).filter((r) => "rq" in r)

  return {
    symbol: toStr(data.symbol) ?? symbol,
    reportType,
    rows: parsed.map((r) => ({
      rq: toStr(r.rq),
      fields: Object.fromEntries(
        Object.entries(r).map(([k, v]) => [k, v === null || v === undefined ? null : (typeof v === "number" || typeof v === "string" ? v : null)]),
      ),
    })),
    fetchedAt: toStr(data.fetched_at),
    source: toStr(data.source) ?? "eltdx",
  }
}

/**
 * F10 /business-composition: 主营业务构成 (按产品 / 按地区)
 * 接口返回 10 列, 但常用的是前 5 列 (口径/分类编号/名称/收入/占比)
 */
export async function fetchStockBusinessComposition(
  symbol: string,
  options: { reportDate?: string | null; limit?: number } = {},
): Promise<StockBusinessCompositionResponse> {
  const params = new URLSearchParams({ symbol })
  if (options.reportDate) params.set("report_date", options.reportDate)
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/business-composition?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取主营构成失败")

  const parsed = parseF10ResultSets(data.raw)
  const limit = options.limit ?? 8

  const items: StockBusinessCompositionItem[] = parsed.slice(0, limit).map((row) => {
    const vals = Object.values(row)
    return {
      category: toStr(row.N000),
      subType: vals[1] === undefined ? null : (typeof vals[1] === "number" || typeof vals[1] === "string" ? vals[1] : null),
      name: toStr(row.N002),
      revenue: toNum(row.N003),
      ratio: toNum(row.N004),
      extras: vals.slice(5).map((v) => (v === null || v === undefined ? null : (typeof v === "number" || typeof v === "string" ? v : null))),
    }
  })

  return {
    symbol: toStr(data.symbol) ?? symbol,
    reportDate: options.reportDate ?? null,
    items,
    fetchedAt: toStr(data.fetched_at),
    source: toStr(data.source) ?? "eltdx",
  }
}

/**
 * F10 /profit-forecast: 业绩预告 / 预测
 * 接口返回 ResultSets[0] = {nyear, flag}, ResultSets[1] = T 列预测数据
 * 这里只把 ResultSets[1] 解析出来, T036/T037/T038 视为净利润(年度/季度差异)
 */
export async function fetchStockProfitForecast(
  symbol: string,
): Promise<StockProfitForecastResponse> {
  const params = new URLSearchParams({ symbol })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/profit-forecast?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取业绩预测失败")

  const rs = (data.raw as { ResultSets?: Array<{ ColName?: string[]; Content?: unknown[][] }> } | undefined)?.ResultSets
  const yearRow = Array.isArray(rs?.[0]?.Content?.[0]) ? rs![0]!.Content![0] as unknown[] : []
  const yearBase = toStr(yearRow[0]) ?? ""
  const forecastTable = Array.isArray(rs?.[1]?.Content?.[0]) ? rs![1]!.Content![0] as unknown[] : []
  const forecastCols = Array.isArray(rs?.[1]?.ColName) ? rs![1]!.ColName! : []

  // 业绩预告通常是 3 列 (当年 / 明年 / 后年), 这里逐列展开为 items
  // 字段顺序假设: [eps3, eps2, eps1, ?netProfit3, ?netProfit2, ?netProfit1, ?rev3, ?rev2, ?rev1, ...]
  // 简化: 每列 -> 一个 item
  const items: StockProfitForecastItem[] = []
  const colsCount = forecastCols.length
  for (let i = 0; i < colsCount; i++) {
    const colName = forecastCols[i]
    const value = forecastTable[i]
    const offset = colsCount - 1 - i // 0 = 最新一年
    const year = yearBase && offset > 0 ? `${Number(yearBase) + offset}` : (yearBase || "")
    items.push({
      year,
      // 净利润预测: T027/T028/T029 一组 (高位数), 这里保守不假设
      netProfit: null,
      eps: toNum(value),
      revenue: null,
      extras: [colName, value ?? null],
    })
  }

  return {
    symbol: toStr(data.symbol) ?? symbol,
    items,
    fetchedAt: toStr(data.fetched_at),
    source: toStr(data.source) ?? "eltdx",
  }
}

/**
 * F10 /announcements: 个股公告列表 (按时间倒序)
 * 后端解析 { issue_date, title, typecode, typename, rec_id, tableid, url, ... }
 */
export async function fetchStockAnnouncements(
  symbol: string,
): Promise<StockAnnouncementsResponse> {
  const params = new URLSearchParams({ symbol })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/announcements?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取公告列表失败")
  const rawItems = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : []
  return {
    symbol: toStr(data.symbol) ?? symbol,
    count: typeof data.count === "number" ? data.count : rawItems.length,
    fetchedAt: toStr(data.fetched_at),
    items: rawItems.map((it) => ({
      issueDate: toStr(it.issue_date),
      title: toStr(it.title),
      typecode: toStr(it.typecode),
      typename: toStr(it.typename),
      recId: toStr(it.rec_id),
      tableid: toStr(it.tableid),
      url: toStr(it.url),
      redistime: toStr(it.redistime),
      source: toStr(it.source),
    })),
  }
}

/**
 * F10 /news: 个股新闻列表
 */
export async function fetchStockNews(
  symbol: string,
): Promise<StockNewsResponse> {
  const params = new URLSearchParams({ symbol })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/news?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取新闻列表失败")
  const rawItems = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : []
  return {
    symbol: toStr(data.symbol) ?? symbol,
    count: typeof data.count === "number" ? data.count : rawItems.length,
    fetchedAt: toStr(data.fetched_at),
    items: rawItems.map((it) => ({
      issueDate: toStr(it.issue_date),
      title: toStr(it.title),
      recId: toStr(it.rec_id),
      tableid: toStr(it.tableid),
      redistime: toStr(it.redistime),
      source: toStr(it.source),
      relatecolumn: toStr(it.relatecolumn),
    })),
  }
}

/**
 * F10 /roadshows: 路演 / 业绩说明会列表
 */
export async function fetchStockRoadshows(
  symbol: string,
): Promise<StockRoadshowsResponse> {
  const params = new URLSearchParams({ symbol })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/roadshows?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取路演列表失败")
  const rawItems = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : []
  return {
    symbol: toStr(data.symbol) ?? symbol,
    count: typeof data.count === "number" ? data.count : rawItems.length,
    fetchedAt: toStr(data.fetched_at),
    items: rawItems.map((it) => ({
      title: toStr(it.title),
      roadshowType: toStr(it.roadshow_type),
      startDate: toStr(it.start_date),
      startTime: toStr(it.start_time),
      endTime: toStr(it.end_time),
      summary: toStr(it.summary),
      url: toStr(it.url),
    })),
  }
}

/**
 * F10 /company-news: 公司研报 / 监管措施
 * section 默认 'gsyj' (公司研究); 其它常用: 'zqyj' (证券研究) / 'jgcs' (监管措施)
 */
export async function fetchStockCompanyNews(
  symbol: string,
  options: { section?: string } = {},
): Promise<StockCompanyNewsResponse> {
  const params = new URLSearchParams({ symbol })
  const section = options.section ?? "gsyj"
  params.set("section", section)
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/f10/company-news?${params.toString()}`,
    withTimeout(F10_REQ_TIMEOUT_MS),
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取公司研报失败")
  const rawItems = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : []
  return {
    symbol: toStr(data.symbol) ?? symbol,
    section,
    count: typeof data.count === "number" ? data.count : rawItems.length,
    fetchedAt: toStr(data.fetched_at),
    items: rawItems.map((it) => ({
      rating: toStr(it.rating),
      analysts: toStr(it.analysts),
      recId: toStr(it.rec_id),
      issueDate: toStr(it.issue_date),
      title: toStr(it.title),
      nflag: toStr(it.nflag),
      docHash: toStr(it.doc_hash),
    })),
  }
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-breadth`)
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-breadth-series`)
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

// ---------------------------------------------------------------------------
// 大盘成交额 / 主力净流入 (AKShare 双源, 独立于 K线技术分析的 market_overview)
// 后端: GET /api/stock-chart/market-overview-akshare
// 持久化: reference/market-overview/fund-flow/latest.json (独立)
// 数据源:
//   - 盘中: AKShare stock_market_fund_flow()
//   - 盘后: reference/market-overview/fund-flow/latest.json
// 字段单位: totalAmount=亿, totalVolume=万手, mainNetInflow=亿
// ---------------------------------------------------------------------------
// 市场概况 (eltdx): 全A成交额 / 涨跌家数
// 后端: GET /api/stock-chart/market-overview-eltdx
// 持久化: reference/market-overview/market-overview/latest.json (独立, 不跟 fund-flow 混用)
// 数据源: eltdx 通达信协议 (TCP 直连, 不走 HTTP)
// ---------------------------------------------------------------------------
export interface MarketOverviewEltdx {
  tradingDate: string | null
  fetchedAt: string | null
  totalAmount: number | null
  totalVolume: number | null
  risingCount: number | null
  fallingCount: number | null
  flatCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  stockCount: number | null
  /** 上一交易日 eltdx totalAmount (大盘成交额较昨日差额用). akshare 失败时
   *  overview.prevDayFlow.totalAmount 是 null, 这里兜底让 diff 仍能算. */
  prevDayTotalAmount?: number | null
  prevDayTradingDate?: string | null
}

export async function fetchMarketOverviewEltdx(): Promise<MarketOverviewEltdx> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-overview-eltdx`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取全A成交额/涨跌家数失败")
  return {
    tradingDate: (data.tradingDate as string) ?? null,
    fetchedAt: (data.fetchedAt as string) ?? null,
    totalAmount: (data.totalAmount as number) ?? null,
    totalVolume: (data.totalVolume as number) ?? null,
    risingCount: (data.risingCount as number) ?? null,
    fallingCount: (data.fallingCount as number) ?? null,
    flatCount: (data.flatCount as number) ?? null,
    limitUpCount: (data.limitUpCount as number) ?? null,
    limitDownCount: (data.limitDownCount as number) ?? null,
    stockCount: (data.stockCount as number) ?? null,
  }
}

export async function triggerMarketOverviewEltdxRefresh(): Promise<{
  ok: boolean
  snapshot?: MarketOverviewEltdx
  error?: string
}> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-overview-eltdx/refresh`, {
    method: "POST",
  })
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) return { ok: false, error: "refresh failed" }
  return {
    ok: Boolean(data.ok),
    snapshot: (data.snapshot as MarketOverviewEltdx | undefined) ?? undefined,
    error: (data.error as string | undefined) ?? undefined,
  }
}
// ---------------------------------------------------------------------------
export interface MarketOverview {
  tradingDate: string | null
  fetchedAt: string | null
  source: "akshare" | "archived" | string
  isTradeTime?: boolean
  totalAmount: number | null
  totalVolume: number | null
  stockCount: number | null
  risingCount: number | null
  fallingCount: number | null
  flatCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  mainNetInflow: number | null
  superLargeNetInflow: number | null
  largeNetInflow: number | null
  mediumNetInflow: number | null
  smallNetInflow: number | null
  /** 净比 (%), AKShare 自带 "-净占比" 字段, 本身就是 % */
  mainNetInflowRatio: number | null
  superLargeNetInflowRatio: number | null
  largeNetInflowRatio: number | null
  mediumNetInflowRatio: number | null
  smallNetInflowRatio: number | null
  /** 上一交易日资金流数据 (capture 时从 archive 读, 供前端算 vs-昨日差额) */
  prevDayFlow: {
    mainNetInflow: number | null
    superLargeNetInflow: number | null
    largeNetInflow: number | null
    mediumNetInflow: number | null
    smallNetInflow: number | null
    totalAmount: number | null
  } | null
  /** 上一交易日日期 YYYY-MM-DD */
  prevDayTradingDate: string | null
  error?: string
}

export async function fetchMarketOverviewAkshare(): Promise<MarketOverview> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-overview-akshare`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取大盘成交额/主力净流入失败")
  return {
    tradingDate: (data.tradingDate as string) ?? null,
    fetchedAt: (data.fetchedAt as string) ?? null,
    source: (data.source as string) ?? "archived",
    isTradeTime: (data.isTradeTime as boolean) ?? undefined,
    totalAmount: (data.totalAmount as number) ?? null,
    totalVolume: (data.totalVolume as number) ?? null,
    stockCount: (data.stockCount as number) ?? null,
    risingCount: (data.risingCount as number) ?? null,
    fallingCount: (data.fallingCount as number) ?? null,
    flatCount: (data.flatCount as number) ?? null,
    limitUpCount: (data.limitUpCount as number) ?? null,
    limitDownCount: (data.limitDownCount as number) ?? null,
    mainNetInflow: (data.mainNetInflow as number) ?? null,
    superLargeNetInflow: (data.superLargeNetInflow as number) ?? null,
    largeNetInflow: (data.largeNetInflow as number) ?? null,
    mediumNetInflow: (data.mediumNetInflow as number) ?? null,
    smallNetInflow: (data.smallNetInflow as number) ?? null,
    mainNetInflowRatio: (data.mainNetInflowRatio as number) ?? null,
    superLargeNetInflowRatio: (data.superLargeNetInflowRatio as number) ?? null,
    largeNetInflowRatio: (data.largeNetInflowRatio as number) ?? null,
    mediumNetInflowRatio: (data.mediumNetInflowRatio as number) ?? null,
    smallNetInflowRatio: (data.smallNetInflowRatio as number) ?? null,
    prevDayFlow: (data.prevDayFlow as Record<string, unknown> | null) ?? null,
    prevDayTradingDate: (data.prevDayTradingDate as string | null) ?? null,
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 手动粘贴的资金流 (东方财富资金流页面 copy-paste 兜底)
// 持久化: reference/market-overview/fund-flow/manual/YYYYMMDD.json
// 跟 akshare / eltdx overview 并行, 前端 manual 存在时优先用 manual 覆盖.
// ---------------------------------------------------------------------------
export interface ManualFundFlow {
  tradingDate: string
  savedAt?: string
  source?: "manual" | string
  mainNetInflow: number | null
  mainNetInflowRatio: number | null
  superLargeNetInflow: number | null
  superLargeNetInflowRatio: number | null
  largeNetInflow: number | null
  largeNetInflowRatio: number | null
  mediumNetInflow: number | null
  mediumNetInflowRatio: number | null
  smallNetInflow: number | null
  smallNetInflowRatio: number | null
}

export async function fetchManualFundFlow(tradingDate: string): Promise<ManualFundFlow | null> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-overview-manual-fund-flow?tradingDate=${encodeURIComponent(tradingDate)}`,
  )
  if (res.status === 404) return null
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data || data.ok !== true) return null
  return {
    tradingDate: (data.tradingDate as string) ?? tradingDate,
    savedAt: (data.savedAt as string) ?? undefined,
    source: (data.source as string) ?? "manual",
    mainNetInflow: (data.mainNetInflow as number) ?? null,
    mainNetInflowRatio: (data.mainNetInflowRatio as number) ?? null,
    superLargeNetInflow: (data.superLargeNetInflow as number) ?? null,
    superLargeNetInflowRatio: (data.superLargeNetInflowRatio as number) ?? null,
    largeNetInflow: (data.largeNetInflow as number) ?? null,
    largeNetInflowRatio: (data.largeNetInflowRatio as number) ?? null,
    mediumNetInflow: (data.mediumNetInflow as number) ?? null,
    mediumNetInflowRatio: (data.mediumNetInflowRatio as number) ?? null,
    smallNetInflow: (data.smallNetInflow as number) ?? null,
    smallNetInflowRatio: (data.smallNetInflowRatio as number) ?? null,
  }
}

export async function saveManualFundFlow(
  payload: Partial<ManualFundFlow> & { tradingDate: string },
): Promise<ManualFundFlow> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-overview-manual-fund-flow`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data || data.ok !== true) {
    throw new Error((data?.error as string) ?? `HTTP ${res.status}`)
  }
  return {
    tradingDate: (data.tradingDate as string) ?? payload.tradingDate,
    savedAt: (data.savedAt as string) ?? undefined,
    source: (data.source as string) ?? "manual",
    mainNetInflow: (data.mainNetInflow as number) ?? null,
    mainNetInflowRatio: (data.mainNetInflowRatio as number) ?? null,
    superLargeNetInflow: (data.superLargeNetInflow as number) ?? null,
    superLargeNetInflowRatio: (data.superLargeNetInflowRatio as number) ?? null,
    largeNetInflow: (data.largeNetInflow as number) ?? null,
    largeNetInflowRatio: (data.largeNetInflowRatio as number) ?? null,
    mediumNetInflow: (data.mediumNetInflow as number) ?? null,
    mediumNetInflowRatio: (data.mediumNetInflowRatio as number) ?? null,
    smallNetInflow: (data.smallNetInflow as number) ?? null,
    smallNetInflowRatio: (data.smallNetInflowRatio as number) ?? null,
  }
}

export async function fetchMarketOverviewAkshareArchive(tradingDate: string): Promise<MarketOverview> {
  // 接受 YYYY-MM-DD 或 YYYYMMDD
  const normalized = tradingDate.replace(/-/g, "")
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-overview-akshare/archive/${normalized}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error(`获取 ${tradingDate} 大盘归档失败`)
  return {
    tradingDate: (data.tradingDate as string) ?? null,
    fetchedAt: (data.fetchedAt as string) ?? null,
    source: (data.source as string) ?? "archived",
    isTradeTime: (data.isTradeTime as boolean) ?? undefined,
    totalAmount: (data.totalAmount as number) ?? null,
    totalVolume: (data.totalVolume as number) ?? null,
    stockCount: (data.stockCount as number) ?? null,
    risingCount: (data.risingCount as number) ?? null,
    fallingCount: (data.fallingCount as number) ?? null,
    flatCount: (data.flatCount as number) ?? null,
    limitUpCount: (data.limitUpCount as number) ?? null,
    limitDownCount: (data.limitDownCount as number) ?? null,
    mainNetInflow: (data.mainNetInflow as number) ?? null,
    superLargeNetInflow: (data.superLargeNetInflow as number) ?? null,
    largeNetInflow: (data.largeNetInflow as number) ?? null,
    mediumNetInflow: (data.mediumNetInflow as number) ?? null,
    smallNetInflow: (data.smallNetInflow as number) ?? null,
    mainNetInflowRatio: (data.mainNetInflowRatio as number) ?? null,
    superLargeNetInflowRatio: (data.superLargeNetInflowRatio as number) ?? null,
    largeNetInflowRatio: (data.largeNetInflowRatio as number) ?? null,
    mediumNetInflowRatio: (data.mediumNetInflowRatio as number) ?? null,
    smallNetInflowRatio: (data.smallNetInflowRatio as number) ?? null,
    prevDayFlow: (data.prevDayFlow as Record<string, unknown> | null) ?? null,
    prevDayTradingDate: (data.prevDayTradingDate as string | null) ?? null,
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 市场脉搏历史序列 (Market Pulse 趋势图用)
// 后端: GET /api/stock-chart/market-overview-akshare/history?range=60d
// 数据源: reference/market-overview/archive/*.json (日级别 archive)
// 单位: 资金流 / 成交额 = "亿"; 涨跌家数 = 整数
// ---------------------------------------------------------------------------
export type PulseRange = "20d" | "60d" | "120d" | "1y"

export interface MarketHistoryPoint {
  /** YYYY-MM-DD */
  date: string
  /** 全 A 成交额 (亿) */
  totalAmount: number | null
  totalVolume: number | null
  risingCount: number | null
  fallingCount: number | null
  flatCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  /** 主力净流入 (亿) */
  mainNetInflow: number | null
  superLargeNetInflow: number | null
  largeNetInflow: number | null
  mediumNetInflow: number | null
  smallNetInflow: number | null
  source: string
}

export interface MarketHistoryResponse {
  ok: boolean
  range: string
  source: string
  count: number
  items: MarketHistoryPoint[]
  error?: string
}

export async function fetchMarketPulseHistory(range: PulseRange = "60d"): Promise<MarketHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-overview-akshare/history?range=${encodeURIComponent(range)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取 Market Pulse 历史序列失败")
  const rawItems = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    range: (data.range as string) ?? range,
    source: (data.source as string) ?? "eastmoney",
    count: typeof data.count === "number" ? data.count : rawItems.length,
    items: rawItems.map((it) => ({
      date: String(it.date ?? ""),
      totalAmount: (it.totalAmount as number) ?? null,
      totalVolume: (it.totalVolume as number) ?? null,
      risingCount: (it.risingCount as number) ?? null,
      fallingCount: (it.fallingCount as number) ?? null,
      flatCount: (it.flatCount as number) ?? null,
      limitUpCount: (it.limitUpCount as number) ?? null,
      limitDownCount: (it.limitDownCount as number) ?? null,
      mainNetInflow: (it.mainNetInflow as number) ?? null,
      superLargeNetInflow: (it.superLargeNetInflow as number) ?? null,
      largeNetInflow: (it.largeNetInflow as number) ?? null,
      mediumNetInflow: (it.mediumNetInflow as number) ?? null,
      smallNetInflow: (it.smallNetInflow as number) ?? null,
      source: String(it.source ?? "eastmoney"),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Pulse · MA 计数 (上一交易日 close > MA20 / MA60 / both 的股票数量)
// 数据源: duckdb.daily_qfq (单次 SQL 窗口函数)
// ---------------------------------------------------------------------------
export interface MaCountBoardStat {
  total: number
  aboveMa20: number
  aboveMa60: number
  aboveBoth: number
  pctMa20: number
  pctMa60: number
  pctBoth: number
  /** 近 5 个交易日上涨 (close > close_5d_ago) 数量 */
  up5d?: number
  /** up5d / total * 100 */
  pctUp5d?: number
  /** 创 60 日新低 (close == 60日窗口内 min) 数量 */
  newLow60d?: number
  /** newLow60d / total * 100 */
  pctNewLow60d?: number
  /** 创 252 日新高 (close >= 252日窗口内 max, 满 252 行窗口) 数量 */
  newHigh252d?: number
  /** newHigh252d / total * 100 */
  pctNewHigh252d?: number
  /** 当日上涨 (close > prev close) 数量 */
  advancing?: number
  /** advancing / total * 100 */
  pctAdvancing?: number
}

export interface MaCountResponse {
  ok: boolean
  tradeDate: string
  totalEligible: number
  aboveMa20: number
  aboveMa60: number
  aboveBoth: number
  pctAboveMa20: number
  pctAboveMa60: number
  pctAboveBoth: number
  /** 近 5 日上涨股票数 (close > 5 个交易日前 close) */
  up5dCount: number
  /** up5dCount / totalEligible * 100 */
  pctUp5d: number
  /** 创 60 日新低股票数 (close == 60日窗口内 min, 满 60 行窗口) */
  newLow60dCount: number
  /** newLow60dCount / totalEligible * 100 */
  pctNewLow60d: number
  /** 创 252 日新高股票数 (close >= 252日窗口内 max, 满 252 行窗口) */
  newHigh252dCount: number
  /** newHigh252dCount / totalEligible * 100 */
  pctNewHigh252d: number
  /** 当日上涨股票数 (close > 前一日 close) */
  advancingCount: number
  /** advancingCount / totalEligible * 100 */
  pctAdvancing: number
  /** 252日新高 0-100 历史分位情绪得分 (基于过去 3 年) */
  newHigh252dScore?: number
  /** 原始 pctNewHigh252d 值 */
  newHigh252dRawValue?: number
  /** 市场广度 0-100 历史分位情绪得分 (breadth_raw = 40%上涨 + 35%MA20 + 25%MA60) */
  breadthScore?: number
  /** 原始 breadth_raw 值 */
  breadthRawValue?: number
  byBoard: Record<string, MaCountBoardStat>
  elapsedMs?: number
  source?: string
  error?: string
}

export async function fetchMarketSentimentMaCount(date?: string): Promise<MaCountResponse> {
  const url = date
    ? `${API_BASE}/api/stock-chart/market-sentiment/ma-count?date=${encodeURIComponent(date)}`
    : `${API_BASE}/api/stock-chart/market-sentiment/ma-count`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, tradeDate: date ?? "", totalEligible: 0,
             aboveMa20: 0, aboveMa60: 0, aboveBoth: 0,
             pctAboveMa20: 0, pctAboveMa60: 0, pctAboveBoth: 0,
             up5dCount: 0, pctUp5d: 0,
             newLow60dCount: 0, pctNewLow60d: 0,
             newHigh252dCount: 0, pctNewHigh252d: 0,
             advancingCount: 0, pctAdvancing: 0,
             byBoard: {}, error: `HTTP ${res.status}` }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? ""),
    totalEligible: (data.totalEligible as number) ?? 0,
    aboveMa20: (data.aboveMa20 as number) ?? 0,
    aboveMa60: (data.aboveMa60 as number) ?? 0,
    aboveBoth: (data.aboveBoth as number) ?? 0,
    pctAboveMa20: (data.pctAboveMa20 as number) ?? 0,
    pctAboveMa60: (data.pctAboveMa60 as number) ?? 0,
    pctAboveBoth: (data.pctAboveBoth as number) ?? 0,
    up5dCount: (data.up5dCount as number) ?? 0,
    pctUp5d: (data.pctUp5d as number) ?? 0,
    newLow60dCount: (data.newLow60dCount as number) ?? 0,
    pctNewLow60d: (data.pctNewLow60d as number) ?? 0,
    newHigh252dCount: (data.newHigh252dCount as number) ?? 0,
    pctNewHigh252d: (data.pctNewHigh252d as number) ?? 0,
    newHigh252dScore: (data.newHigh252dScore as number) ?? undefined,
    newHigh252dRawValue: (data.newHigh252dRawValue as number) ?? undefined,
    breadthScore: (data.breadthScore as number) ?? undefined,
    breadthRawValue: (data.breadthRawValue as number) ?? undefined,
    advancingCount: (data.advancingCount as number) ?? 0,
    pctAdvancing: (data.pctAdvancing as number) ?? 0,
    byBoard: (data.byBoard as Record<string, MaCountBoardStat>) ?? {},
    elapsedMs: (data.elapsedMs as number) ?? undefined,
    source: (data.source as string) ?? undefined,
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Pulse · 宽基指数近 N 日收益 (沪深300 / 中证1000)
// 数据源: duckdb.index_daily_raw
// ---------------------------------------------------------------------------
export interface IndexReturnDaily {
  date: string
  close: number
  dailyReturnPct: number | null
}

export interface IndexReturnItem {
  name: string
  code: string
  fullCode: string
  current: number | null
  currentDate: string | null
  baseClose: number | null
  baseDate: string | null
  returnPct: number | null
  daily: IndexReturnDaily[]
  available: boolean
}

export interface IndexReturnsResponse {
  ok: boolean
  days: number
  items: IndexReturnItem[]
  error?: string
}

export async function fetchMarketPulseIndexReturns(days: number = 5): Promise<IndexReturnsResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-pulse/index-returns?days=${days}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, days, items: [], error: `HTTP ${res.status}` }
  }
  const rawItems = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    days: (data.days as number) ?? days,
    items: rawItems.map((it) => ({
      name: String(it.name ?? ""),
      code: String(it.code ?? ""),
      fullCode: String(it.fullCode ?? ""),
      current: (it.current as number) ?? null,
      currentDate: (it.currentDate as string) ?? null,
      baseClose: (it.baseClose as number) ?? null,
      baseDate: (it.baseDate as string) ?? null,
      returnPct: (it.returnPct as number) ?? null,
      daily: Array.isArray(it.daily) ? (it.daily as Array<Record<string, unknown>>).map((d) => ({
        date: String(d.date ?? ""),
        close: (d.close as number) ?? 0,
        dailyReturnPct: (d.dailyReturnPct as number) ?? null,
      })) : [],
      available: Boolean(it.available),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// MA 计数 + 指数收益 历史趋势 (sparkline 用, 按日期范围查)
// 数据源: duckdb.ma_count_daily / index_returns_daily (持久化, 0.8ms 返回)
// ---------------------------------------------------------------------------
export interface MaCountHistoryItem {
  tradeDate: string
  totalEligible: number
  aboveMa20: number
  aboveMa60: number
  aboveBoth: number
  pctAboveMa20: number
  pctAboveMa60: number
  pctAboveBoth: number
  up5dCount: number
  pctUp5d: number
  newLow60dCount: number
  pctNewLow60d: number
  newHigh252dCount: number
  pctNewHigh252d: number
  advancingCount: number
  pctAdvancing: number
  /** 252日新高 0-100 历史分位情绪得分 */
  newHigh252dScore?: number
  /** 市场广度 0-100 历史分位情绪得分 */
  breadthScore?: number
  fromCache?: boolean
}

export interface MaCountHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: MaCountHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentMaCountHistory(
  start: string,
  end: string,
): Promise<MaCountHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/ma-count/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      totalEligible: (it.totalEligible as number) ?? 0,
      aboveMa20: (it.aboveMa20 as number) ?? 0,
      aboveMa60: (it.aboveMa60 as number) ?? 0,
      aboveBoth: (it.aboveBoth as number) ?? 0,
      pctAboveMa20: (it.pctAboveMa20 as number) ?? 0,
      pctAboveMa60: (it.pctAboveMa60 as number) ?? 0,
      pctAboveBoth: (it.pctAboveBoth as number) ?? 0,
      up5dCount: (it.up5dCount as number) ?? 0,
      pctUp5d: (it.pctUp5d as number) ?? 0,
      newLow60dCount: (it.newLow60dCount as number) ?? 0,
      pctNewLow60d: (it.pctNewLow60d as number) ?? 0,
      newHigh252dCount: (it.newHigh252dCount as number) ?? 0,
      pctNewHigh252d: (it.pctNewHigh252d as number) ?? 0,
      newHigh252dScore: (it.newHigh252dScore as number) ?? undefined,
      breadthScore: (it.breadthScore as number) ?? undefined,
      advancingCount: (it.advancingCount as number) ?? 0,
      pctAdvancing: (it.pctAdvancing as number) ?? 0,
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

export interface IndexReturnsHistoryItem {
  tradeDate: string
  code: string
  name: string
  current: number | null
  currentDate: string | null
  baseClose: number | null
  baseDate: string | null
  returnPct: number | null
}

export interface IndexReturnsHistoryResponse {
  ok: boolean
  window: number
  start: string
  end: string
  count: number
  items: IndexReturnsHistoryItem[]
  error?: string
}

export async function fetchMarketPulseIndexReturnsHistory(
  window: number = 5,
  start: string,
  end: string,
): Promise<IndexReturnsHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-pulse/index-returns/history?window=${window}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, window, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    window: (data.window as number) ?? window,
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      code: String(it.code ?? ""),
      name: String(it.name ?? ""),
      current: (it.current as number) ?? null,
      currentDate: (it.currentDate as string) ?? null,
      baseClose: (it.baseClose as number) ?? null,
      baseDate: (it.baseDate as string) ?? null,
      returnPct: (it.returnPct as number) ?? null,
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment · 板块扩散 (上涨行业数 / 有效行业数)
// 数据源: duckdb.market_pulse_sector_breadth_daily
//        (由 ths_industry_fund_flow_daily 聚合, 工作日 17:15 收盘后算)
// 归属: /market/sentiment 页面 (跟 ma-count / risk-appetite / limit-emotion-summary 同空间)
// ---------------------------------------------------------------------------
export interface SectorBreadthItem {
  tradeDate: string
  advancing: number        // 上涨行业数
  declining: number        // 下跌行业数
  flat: number             // 平盘行业数
  total: number            // 有效行业数
  advancePct: number       // 0-1, 上涨占比
  /** 0-100 情绪得分 = advancePct × 100 (天然百分比, 不需要百分位) */
  score?: number | null
  source: string | null
  elapsedMs: number | null
  fromCache?: boolean
}

export interface SectorBreadthResponse {
  ok: boolean
  tradeDate: string
  advancing: number
  declining: number
  flat: number
  total: number
  advancePct: number
  score?: number | null
  source: string | null
  elapsedMs: number | null
  fromCache?: boolean
  error?: string
}

export interface SectorBreadthHistoryResponse {
  ok: boolean
  start: string
  end: string
  days: number
  count: number
  items: SectorBreadthItem[]
  error?: string
}

export async function fetchMarketSentimentSectorBreadth(
  date?: string,
): Promise<SectorBreadthResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ""
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-sentiment/sector-breadth${q}`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false,
      tradeDate: date ?? "",
      advancing: 0, declining: 0, flat: 0, total: 0, advancePct: 0,
      score: 0,
      source: null, elapsedMs: null, error: `HTTP ${res.status}`,
    }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? date ?? ""),
    advancing: Number(data.advancing ?? 0),
    declining: Number(data.declining ?? 0),
    flat: Number(data.flat ?? 0),
    total: Number(data.total ?? 0),
    advancePct: Number(data.advancePct ?? 0),
    score: (data.score as number) ?? Number(data.advancePct ?? 0) * 100,
    source: (data.source as string) ?? null,
    elapsedMs: (data.elapsedMs as number) ?? null,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export async function fetchMarketSentimentSectorBreadthHistory(
  days: number = 30,
  end?: string,
): Promise<SectorBreadthHistoryResponse> {
  const params = new URLSearchParams({ days: String(days) })
  if (end) params.set("end", end)
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/sector-breadth?${params.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start: "", end: "", days, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? "",
    end: (data.end as string) ?? end ?? "",
    days: (data.days as number) ?? days,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      advancing: Number(it.advancing ?? 0),
      declining: Number(it.declining ?? 0),
      flat: Number(it.flat ?? 0),
      total: Number(it.total ?? 0),
      advancePct: Number(it.advancePct ?? 0),
      score: (it.score as number) ?? Number(it.advancePct ?? 0) * 100,
      source: (it.source as string) ?? null,
      elapsedMs: (it.elapsedMs as number) ?? null,
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment · 风险偏好 (沪深300 20日 - (511010 + 511090)/2 国债 ETF 20日)
// 数据源: duckdb.risk_appetite_daily (持久化, cache-aside)
// 归属: /market/sentiment 页面 (Market Sentiment 路由), 不是 market-pulse
// ---------------------------------------------------------------------------
export interface RiskAppetiteAsset {
  /** 当前收盘价 (前复权) */
  close: number | null
  /** 当前 bar 的实际日期 (可能滞后于请求日期) */
  currentDate: string | null
  /** 20 个交易日前的 close */
  baseClose: number | null
  /** 20 个交易日前的实际日期 */
  baseDate: string | null
  /** window 日累计收益 % */
  returnPct: number | null
  /** 511010 / 511090 才有: 在综合 treasury 里的权重 (默认 0.5 / 0.5) */
  weight?: number
  /** 实际用到的 bar 数 (调试用) */
  barsUsed?: number
}

export interface RiskAppetiteResponse {
  ok: boolean
  tradeDate: string
  windowDays: number
  hs300: RiskAppetiteAsset
  treasury: {
    "511010": RiskAppetiteAsset
    "511090": RiskAppetiteAsset
    weighted: { returnPct: number | null }
  }
  spread: {
    "511010": number | null   // hs300 - 511010
    "511090": number | null   // hs300 - 511090
    weighted: number | null   // hs300 - (511010+511090)/2  ← 主指标
  }
  /** 0-100 历史分位情绪得分 (基于过去 3 年 spread_weighted 的百分位) */
  score?: number
  /** 原始 spread_weighted 值 (百分比) */
  rawValue?: number
  elapsedMs?: number
  source?: string
  fromCache?: boolean
  error?: string
}

export async function fetchMarketSentimentRiskAppetite(date?: string): Promise<RiskAppetiteResponse> {
  const url = date
    ? `${API_BASE}/api/stock-chart/market-sentiment/risk-appetite?date=${encodeURIComponent(date)}`
    : `${API_BASE}/api/stock-chart/market-sentiment/risk-appetite`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false, tradeDate: date ?? "", windowDays: 20,
      hs300: { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null },
      treasury: {
        "511010": { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null, weight: 0.5 },
        "511090": { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null, weight: 0.5 },
        weighted: { returnPct: null },
      },
      spread: { "511010": null, "511090": null, weighted: null },
      error: `HTTP ${res.status}`,
    }
  }
  const t = (data.treasury as Record<string, unknown>) || {}
  const s = (data.spread as Record<string, unknown>) || {}
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? ""),
    windowDays: (data.windowDays as number) ?? 20,
    hs300: (data.hs300 as RiskAppetiteAsset) ?? { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null },
    treasury: {
      "511010": (t["511010"] as RiskAppetiteAsset) ?? { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null, weight: 0.5 },
      "511090": (t["511090"] as RiskAppetiteAsset) ?? { close: null, currentDate: null, baseClose: null, baseDate: null, returnPct: null, weight: 0.5 },
      weighted: (t.weighted as { returnPct: number | null }) ?? { returnPct: null },
    },
    spread: {
      "511010": (s["511010"] as number | null) ?? null,
      "511090": (s["511090"] as number | null) ?? null,
      weighted: (s.weighted as number | null) ?? null,
    },
    elapsedMs: (data.elapsedMs as number) ?? undefined,
    source: (data.source as string) ?? undefined,
    fromCache: Boolean(data.fromCache),
    score: (data.score as number) ?? undefined,
    rawValue: (data.rawValue as number) ?? undefined,
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 风险偏好 历史 (sparkline 用, 跟 ma-count history 同一模式)
// ---------------------------------------------------------------------------
export interface RiskAppetiteHistoryItem {
  tradeDate: string
  hs300ReturnPct: number | null
  treasury511010ReturnPct: number | null
  treasury511090ReturnPct: number | null
  treasuryWeightedReturnPct: number | null
  spread511010: number | null
  spread511090: number | null
  spreadWeighted: number | null
  /** 0-100 历史分位情绪得分 */
  score?: number
  fromCache?: boolean
}

export interface RiskAppetiteHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: RiskAppetiteHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentRiskAppetiteHistory(
  start: string,
  end: string,
): Promise<RiskAppetiteHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/risk-appetite/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => {
      const hs = (it.hs300 as Record<string, unknown>) || {}
      const t = (it.treasury as Record<string, unknown>) || {}
      const s = (it.spread as Record<string, unknown>) || {}
      const tw = (t.weighted as Record<string, unknown>) || {}
      return {
        tradeDate: String(it.tradeDate ?? ""),
        hs300ReturnPct: (hs.returnPct as number | null) ?? null,
        treasury511010ReturnPct: ((t["511010"] as Record<string, unknown>)?.returnPct as number | null) ?? null,
        treasury511090ReturnPct: ((t["511090"] as Record<string, unknown>)?.returnPct as number | null) ?? null,
        treasuryWeightedReturnPct: (tw.returnPct as number | null) ?? null,
        spread511010: (s["511010"] as number | null) ?? null,
        spread511090: (s["511090"] as number | null) ?? null,
        spreadWeighted: (s.weighted as number | null) ?? null,
        score: (it.score as number) ?? undefined,
        fromCache: Boolean(it.fromCache),
      }
    }),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment · 涨跌停情绪综合分 (短线情绪)
//
// 公式 (跟 backend/repositories/market/limit_repo.calc_limit_emotion_summary 一致):
//   涨跌停比    = limit_up / max(limit_down, 1)
//   炸板率      = broken / touched
//   昨日涨停收益 = AVG(今日 changePct) for codes where 昨日 isLimitUp
//   up_down_score       = clamp(50 + 25 * log2(ratio))            ∈ [0, 100]
//   break_board_score   = clamp(100 - 100 * rate)                 ∈ [0, 100]   (反向)
//   yesterday_return_score = clamp(50 + 10 * avg_return_pct)      ∈ [0, 100]
//   composite = 0.4 * A + 0.3 * B + 0.3 * C
//   level: hot (>=80) / active (>=60) / normal (>=40) / weak (>=20) / ice (<20)
//
// 归属: /market/sentiment 页面, 不是 market-pulse.
// 后端路径: /api/stock-chart/market-sentiment/limit-emotion-summary
// ---------------------------------------------------------------------------
export type LimitEmotionLevel = "hot" | "active" | "normal" | "weak" | "ice"

export interface LimitEmotionSummary {
  ok: boolean
  tradeDate: string
  prevTradeDate: string | null
  /** 今日涨停股数 */
  limitUpCount: number
  /** 今日跌停股数 */
  limitDownCount: number
  /** 今日盘中触板股数 (high >= 涨停价) */
  touchedCount: number
  /** 今日炸板股数 (触板但未封板) */
  brokenCount: number
  /** 炸板率 broken / touched, ∈ [0, 1], null when touched=0 */
  breakBoardRate: number | null
  /** 涨跌停比 = limitUp / max(limitDown, 1) */
  limitUpDownRatio: number
  /** 昨日涨停股数 */
  yesterdayLimitUpCount: number
  /** 昨日涨停股今日平均涨跌幅 (%) */
  yesterdayLimitUpAvgReturn: number | null
  components: {
    upDownScore: number
    breakBoardScore: number
    yesterdayReturnScore: number
  }
  compositeScore: number
  level: LimitEmotionLevel
  elapsedMs?: number
  source?: string
  fromCache?: boolean
  error?: string
}

export async function fetchMarketSentimentLimitEmotionSummary(
  date?: string,
): Promise<LimitEmotionSummary> {
  const url = date
    ? `${API_BASE}/api/stock-chart/market-sentiment/limit-emotion-summary?date=${encodeURIComponent(date)}`
    : `${API_BASE}/api/stock-chart/market-sentiment/limit-emotion-summary`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false, tradeDate: date ?? "", prevTradeDate: null,
      limitUpCount: 0, limitDownCount: 0, touchedCount: 0, brokenCount: 0,
      breakBoardRate: null, limitUpDownRatio: 0,
      yesterdayLimitUpCount: 0, yesterdayLimitUpAvgReturn: null,
      components: { upDownScore: 0, breakBoardScore: 50, yesterdayReturnScore: 50 },
      compositeScore: 0, level: "weak", error: `HTTP ${res.status}`,
    }
  }
  const comp = (data.components as Record<string, unknown>) || {}
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? ""),
    prevTradeDate: (data.prevTradeDate as string | null) ?? null,
    limitUpCount: (data.limitUpCount as number) ?? 0,
    limitDownCount: (data.limitDownCount as number) ?? 0,
    touchedCount: (data.touchedCount as number) ?? 0,
    brokenCount: (data.brokenCount as number) ?? 0,
    breakBoardRate: (data.breakBoardRate as number | null) ?? null,
    limitUpDownRatio: (data.limitUpDownRatio as number) ?? 0,
    yesterdayLimitUpCount: (data.yesterdayLimitUpCount as number) ?? 0,
    yesterdayLimitUpAvgReturn: (data.yesterdayLimitUpAvgReturn as number | null) ?? null,
    components: {
      upDownScore: (comp.upDownScore as number) ?? 0,
      breakBoardScore: (comp.breakBoardScore as number) ?? 50,
      yesterdayReturnScore: (comp.yesterdayReturnScore as number) ?? 50,
    },
    compositeScore: (data.compositeScore as number) ?? 0,
    level: (data.level as LimitEmotionLevel) ?? "weak",
    elapsedMs: (data.elapsedMs as number) ?? undefined,
    source: (data.source as string) ?? undefined,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export interface LimitEmotionSummaryHistoryItem {
  tradeDate: string
  limitUpCount: number
  limitDownCount: number
  touchedCount: number
  brokenCount: number
  breakBoardRate: number | null
  limitUpDownRatio: number
  yesterdayLimitUpCount: number
  yesterdayLimitUpAvgReturn: number | null
  compositeScore: number
  level: LimitEmotionLevel
  fromCache?: boolean
}

export interface LimitEmotionSummaryHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: LimitEmotionSummaryHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentLimitEmotionSummaryHistory(
  start: string,
  end: string,
): Promise<LimitEmotionSummaryHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/limit-emotion-summary/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      limitUpCount: (it.limitUpCount as number) ?? 0,
      limitDownCount: (it.limitDownCount as number) ?? 0,
      touchedCount: (it.touchedCount as number) ?? 0,
      brokenCount: (it.brokenCount as number) ?? 0,
      breakBoardRate: (it.breakBoardRate as number | null) ?? null,
      limitUpDownRatio: (it.limitUpDownRatio as number) ?? 0,
      yesterdayLimitUpCount: (it.yesterdayLimitUpCount as number) ?? 0,
      yesterdayLimitUpAvgReturn: (it.yesterdayLimitUpAvgReturn as number | null) ?? null,
      compositeScore: (it.compositeScore as number) ?? 0,
      level: (it.level as LimitEmotionLevel) ?? "weak",
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment · 波动率情绪 (情绪分项 ⑤)
//
// 公式 (跟 backend/repositories/market/volatility_sentiment_repo 一致):
//   realized_vol_20d = std(近 20 日日收益率) × √252 × 100   (%, 年化)
//   percentile_1y    = rank(近 252 个交易日的 vol, 含等于) / 252  ∈ [0, 1]
//   sentiment_score  = (1 - percentile_1y) × 100              ∈ [0, 100]
//                     高分=平静 (低波, 情绪好)  低分=波动 (高波, 情绪差)
//
// 数据源: duckdb.volatility_sentiment_daily (cache-aside, /api/.../volatility-sentiment)
// 归属: /market/sentiment 页面, 不是 market-pulse
// ---------------------------------------------------------------------------
export interface VolatilitySentimentItem {
  tradeDate: string
  /** 6 位 code (有 sh/sz/bj 前缀), 例 "sh000300" */
  underlyingCode: string
  /** 中文名, 例 "沪深300" */
  underlyingName: string
  /** 沪深300 当日收盘价 */
  close: number | null
  /** 当日日收益率 % */
  dailyReturnPct: number | null
  /** 20 日年化波动率 % */
  realizedVol20d: number | null
  volWindowDays: number
  volLookbackDays: number
  /** 历史分位 0-1, 越小=越平静 */
  percentile1y: number | null
  /** 情绪得分 0-100, 反向 (高分=情绪好) */
  sentimentScore: number | null
  sampleCount: number
  elapsedMs?: number
  source?: string
  fromCache?: boolean
}

export interface VolatilitySentimentResponse {
  ok: boolean
  tradeDate: string
  underlyingCode: string
  underlyingName: string
  close: number | null
  dailyReturnPct: number | null
  realizedVol20d: number | null
  volWindowDays: number
  volLookbackDays: number
  percentile1y: number | null
  sentimentScore: number | null
  sampleCount: number
  elapsedMs?: number
  source?: string
  fromCache?: boolean
  error?: string
}

export async function fetchMarketSentimentVolatilitySentiment(
  date?: string,
): Promise<VolatilitySentimentResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ""
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-sentiment/volatility-sentiment${q}`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false,
      tradeDate: date ?? "",
      underlyingCode: "sh000300",
      underlyingName: "沪深300",
      close: null,
      dailyReturnPct: null,
      realizedVol20d: null,
      volWindowDays: 20,
      volLookbackDays: 252,
      percentile1y: null,
      sentimentScore: null,
      sampleCount: 0,
      elapsedMs: null,
      source: null,
      error: `HTTP ${res.status}`,
    }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? date ?? ""),
    underlyingCode: String(data.underlyingCode ?? "sh000300"),
    underlyingName: String(data.underlyingName ?? "沪深300"),
    close: (data.close as number | null) ?? null,
    dailyReturnPct: (data.dailyReturnPct as number | null) ?? null,
    realizedVol20d: (data.realizedVol20d as number | null) ?? null,
    volWindowDays: Number(data.volWindowDays ?? 20),
    volLookbackDays: Number(data.volLookbackDays ?? 252),
    percentile1y: (data.percentile1y as number | null) ?? null,
    sentimentScore: (data.sentimentScore as number | null) ?? null,
    sampleCount: Number(data.sampleCount ?? 0),
    elapsedMs: (data.elapsedMs as number) ?? null,
    source: (data.source as string) ?? null,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export interface VolatilitySentimentHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: VolatilitySentimentItem[]
  error?: string
}

export async function fetchMarketSentimentVolatilitySentimentHistory(
  start: string,
  end: string,
): Promise<VolatilitySentimentHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/volatility-sentiment/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      underlyingCode: String(it.underlyingCode ?? "sh000300"),
      underlyingName: String(it.underlyingName ?? "沪深300"),
      close: (it.close as number | null) ?? null,
      dailyReturnPct: (it.dailyReturnPct as number | null) ?? null,
      realizedVol20d: (it.realizedVol20d as number | null) ?? null,
      volWindowDays: Number(it.volWindowDays ?? 20),
      volLookbackDays: Number(it.volLookbackDays ?? 252),
      percentile1y: (it.percentile1y as number | null) ?? null,
      sentimentScore: (it.sentimentScore as number | null) ?? null,
      sampleCount: Number(it.sampleCount ?? 0),
      elapsedMs: (it.elapsedMs as number) ?? null,
      source: (it.source as string) ?? null,
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 成交活跃度 (Turnover Activity · Market Sentiment)
// ---------------------------------------------------------------------------
export interface TurnoverActivityResponse {
  ok: boolean
  tradeDate: string
  totalAmount: number | null
  avg20dAmount: number | null
  ratio: number | null
  /** 0-100 历史分位情绪得分 (基于过去 3 年 ratio 的百分位) */
  score?: number
  /** 原始 ratio 值 */
  rawValue?: number
  elapsedMs: number | null
  source: string
  error?: string
}

export interface TurnoverActivityHistoryItem {
  tradeDate: string
  totalAmount: number | null
  avg20dAmount: number | null
  ratio: number | null
  /** 0-100 历史分位情绪得分 */
  score?: number
  elapsedMs: number | null
  source: string
  fromCache: boolean
}

export interface TurnoverActivityHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: TurnoverActivityHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentTurnoverActivity(
  date?: string,
): Promise<TurnoverActivityResponse> {
  const params = new URLSearchParams()
  if (date) params.set("date", date)
  const qs = params.toString()
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/turnover-activity${qs ? "?" + qs : ""}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, tradeDate: date ?? "", totalAmount: null, avg20dAmount: null, ratio: null, elapsedMs: null, source: "", error: `HTTP ${res.status}` }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? ""),
    totalAmount: (data.totalAmount as number | null) ?? null,
    avg20dAmount: (data.avg20dAmount as number | null) ?? null,
    ratio: (data.ratio as number | null) ?? null,
    score: (data.score as number) ?? undefined,
    rawValue: (data.rawValue as number) ?? undefined,
    elapsedMs: (data.elapsedMs as number | null) ?? null,
    source: (data.source as string) ?? "",
    error: data.error as string | undefined,
  }
}

export async function fetchMarketSentimentTurnoverActivityHistory(
  start: string,
  end: string,
): Promise<TurnoverActivityHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/turnover-activity/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      totalAmount: (it.totalAmount as number | null) ?? null,
      avg20dAmount: (it.avg20dAmount as number | null) ?? null,
      ratio: (it.ratio as number | null) ?? null,
      score: (it.score as number) ?? undefined,
      elapsedMs: (it.elapsedMs as number) ?? null,
      source: (it.source as string) ?? "",
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 风格风险偏好 (Style Risk Appetite) — Market Sentiment
// ---------------------------------------------------------------------------
// 风格强弱 = 中证1000 近5日收益率 - 沪深300 近5日收益率
// spread > 0: 小盘更强 (市场风险偏好积极)
// spread < 0: 大盘更强 (避险倾向)
// ---------------------------------------------------------------------------

export interface StyleRiskAppetiteIndex {
  name: string
  code: string
  returnPct: number | null
  current?: number | null
  baseClose?: number | null
}

export interface StyleRiskAppetiteResponse {
  ok: boolean
  tradeDate: string
  windowDays: number
  hs300: StyleRiskAppetiteIndex
  csi1000: StyleRiskAppetiteIndex
  spread: number | null
  /** 0-100 历史分位情绪得分 (基于过去 3 年 spread 的百分位) */
  score?: number
  /** 原始 spread 值 (百分比) */
  rawValue?: number
  elapsedMs?: number
  source?: string
  fromCache?: boolean
  error?: string
}

export async function fetchMarketSentimentStyleRiskAppetite(
  date?: string,
): Promise<StyleRiskAppetiteResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ""
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/style-risk-appetite${q}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false,
      tradeDate: date ?? "",
      windowDays: 5,
      hs300: { name: "沪深300", code: "sh000300", returnPct: null },
      csi1000: { name: "中证1000", code: "sh000852", returnPct: null },
      spread: null,
      error: `HTTP ${res.status}`,
    }
  }
  const hs300Raw = (data.hs300 as Record<string, unknown>) ?? {}
  const csi1000Raw = (data.csi1000 as Record<string, unknown>) ?? {}
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? date ?? ""),
    windowDays: (data.windowDays as number) ?? 5,
    hs300: {
      name: String(hs300Raw.name ?? "沪深300"),
      code: String(hs300Raw.code ?? "sh000300"),
      returnPct: (hs300Raw.returnPct as number | null) ?? null,
    },
    csi1000: {
      name: String(csi1000Raw.name ?? "中证1000"),
      code: String(csi1000Raw.code ?? "sh000852"),
      returnPct: (csi1000Raw.returnPct as number | null) ?? null,
    },
    spread: (data.spread as number | null) ?? null,
    score: (data.score as number) ?? undefined,
    rawValue: (data.rawValue as number) ?? undefined,
    elapsedMs: (data.elapsedMs as number) ?? undefined,
    source: (data.source as string) ?? undefined,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export interface StyleRiskAppetiteHistoryItem {
  tradeDate: string
  spread: number | null
  /** 0-100 历史分位情绪得分 */
  score?: number
  fromCache?: boolean
}

export interface StyleRiskAppetiteHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: StyleRiskAppetiteHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentStyleRiskAppetiteHistory(
  start: string,
  end: string,
): Promise<StyleRiskAppetiteHistoryResponse> {
  const params = new URLSearchParams({ start, end })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/style-risk-appetite/history?${params.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      spread: (it.spread as number | null) ?? null,
      score: (it.score as number) ?? undefined,
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// 赚钱效应 (Profit Effect) — Market Sentiment 分项④
// ---------------------------------------------------------------------------
// score = 60% × 近5日上涨占比 + 40% × (100 - 60日新低占比)
// score ≥ 60 → 赚钱面宽 (积极), ≥ 40 → 中性, < 40 → 亏钱效应
// ---------------------------------------------------------------------------

export interface ProfitEffectResponse {
  ok: boolean
  tradeDate: string
  up5dPct: number | null
  newLow60dPct: number | null
  score: number | null
  /** 原始 score (百分位之前的 raw 合成值) */
  rawValue?: number
  elapsedMs?: number
  source?: string
  fromCache?: boolean
  error?: string
}

export async function fetchMarketSentimentProfitEffect(
  date?: string,
): Promise<ProfitEffectResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ""
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/profit-effect${q}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false,
      tradeDate: date ?? "",
      up5dPct: null,
      newLow60dPct: null,
      score: null,
      error: `HTTP ${res.status}`,
    }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? date ?? ""),
    up5dPct: (data.up5dPct as number | null) ?? null,
    newLow60dPct: (data.newLow60dPct as number | null) ?? null,
    score: (data.score as number | null) ?? null,
    rawValue: (data.rawValue as number) ?? undefined,
    elapsedMs: (data.elapsedMs as number) ?? undefined,
    source: (data.source as string) ?? undefined,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export interface ProfitEffectHistoryItem {
  tradeDate: string
  score: number | null
  fromCache?: boolean
}

export interface ProfitEffectHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: ProfitEffectHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentProfitEffectHistory(
  start: string,
  end: string,
): Promise<ProfitEffectHistoryResponse> {
  const params = new URLSearchParams({ start, end })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/profit-effect/history?${params.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      score: (it.score as number | null) ?? null,
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

// ---------------------------------------------------------------------------
// Market Sentiment · 市场情绪指数 (9 张卡加权 composite, 顶部大卡)
// 数据源: duckdb.market_sentiment_index_daily (持久化, cache-aside)
//   公式: 15%×vol + 15%×turnover + 10%×priceStrength + 10%×riskAppetite
//       + 15%×breadth + 15%×limitEmotion + 10%×profitEffect
//       +  5%×sectorBreadth +  5%×styleRisk
// 归属: /market/sentiment 页面 (顶部 1 张大卡)
// ---------------------------------------------------------------------------
export interface MarketSentimentIndexComponents {
  vol: number | null
  turnover: number | null
  price_strength: number | null
  risk_appetite: number | null
  breadth: number | null
  limit_emotion: number | null
  profit_effect: number | null
  sector_breadth: number | null
  style_risk: number | null
}

export interface MarketSentimentIndexWeights {
  vol: number
  turnover: number
  price_strength: number
  risk_appetite: number
  breadth: number
  limit_emotion: number
  profit_effect: number
  sector_breadth: number
  style_risk: number
}

export interface MarketSentimentIndexResponse {
  ok: boolean
  tradeDate: string
  /** 9 个 component score, 缺失为 null (calc 内部视为 50 中性) */
  components: MarketSentimentIndexComponents
  /** 9 个权重, 合计 1.0 */
  weights: MarketSentimentIndexWeights
  /** 0-100 合成得分 */
  compositeScore: number | null
  /** 实际有数据的 component 数 (1-9), 9 = 全部 sub-card 都有 */
  componentCount: number
  /** 等级: hot / active / normal / weak / ice */
  level: string
  elapsedMs: number | null
  source: string | null
  fromCache?: boolean
  error?: string
}

export interface MarketSentimentIndexHistoryItem {
  tradeDate: string
  compositeScore: number | null
  level: string
  componentCount: number
  components: MarketSentimentIndexComponents
  fromCache?: boolean
}

export interface MarketSentimentIndexHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: MarketSentimentIndexHistoryItem[]
  error?: string
}

export async function fetchMarketSentimentIndex(
  date?: string,
): Promise<MarketSentimentIndexResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ""
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-sentiment/index${q}`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return {
      ok: false,
      tradeDate: date ?? "",
      components: emptyMsiComponents(),
      weights: emptyMsiWeights(),
      compositeScore: null,
      componentCount: 0,
      level: "normal",
      elapsedMs: null,
      source: null,
      error: `HTTP ${res.status}`,
    }
  }
  return {
    ok: Boolean(data.ok),
    tradeDate: String(data.tradeDate ?? date ?? ""),
    components: parseMsiComponents(data.components),
    weights: parseMsiWeights(data.weights),
    compositeScore: (data.compositeScore as number | null) ?? null,
    componentCount: Number(data.componentCount ?? 0),
    level: String(data.level ?? "normal"),
    elapsedMs: (data.elapsedMs as number) ?? null,
    source: (data.source as string) ?? null,
    fromCache: Boolean(data.fromCache),
    error: (data.error as string) ?? undefined,
  }
}

export async function fetchMarketSentimentIndexHistory(
  start: string,
  end: string,
): Promise<MarketSentimentIndexHistoryResponse> {
  const params = new URLSearchParams({ start, end })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-sentiment/index/history?${params.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start, end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: (data.start as string) ?? start,
    end: (data.end as string) ?? end,
    count: (data.count as number) ?? raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      compositeScore: (it.compositeScore as number | null) ?? null,
      level: String(it.level ?? "normal"),
      componentCount: Number(it.componentCount ?? 0),
      components: parseMsiComponents(it.components),
      fromCache: Boolean(it.fromCache),
    })),
    error: (data.error as string) ?? undefined,
  }
}

function emptyMsiComponents(): MarketSentimentIndexComponents {
  return {
    vol: null, turnover: null, price_strength: null, risk_appetite: null,
    breadth: null, limit_emotion: null, profit_effect: null,
    sector_breadth: null, style_risk: null,
  }
}

function emptyMsiWeights(): MarketSentimentIndexWeights {
  return {
    vol: 0.15, turnover: 0.15, price_strength: 0.10, risk_appetite: 0.10,
    breadth: 0.15, limit_emotion: 0.15, profit_effect: 0.10,
    sector_breadth: 0.05, style_risk: 0.05,
  }
}

function parseMsiComponents(raw: unknown): MarketSentimentIndexComponents {
  const c = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>
  return {
    vol: (c.vol as number | null) ?? null,
    turnover: (c.turnover as number | null) ?? null,
    price_strength: (c.price_strength as number | null) ?? null,
    risk_appetite: (c.risk_appetite as number | null) ?? null,
    breadth: (c.breadth as number | null) ?? null,
    limit_emotion: (c.limit_emotion as number | null) ?? null,
    profit_effect: (c.profit_effect as number | null) ?? null,
    sector_breadth: (c.sector_breadth as number | null) ?? null,
    style_risk: (c.style_risk as number | null) ?? null,
  }
}

function parseMsiWeights(raw: unknown): MarketSentimentIndexWeights {
  const w = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>
  return {
    vol: Number(w.vol ?? 0.15),
    turnover: Number(w.turnover ?? 0.15),
    price_strength: Number(w.price_strength ?? 0.10),
    risk_appetite: Number(w.risk_appetite ?? 0.10),
    breadth: Number(w.breadth ?? 0.15),
    limit_emotion: Number(w.limit_emotion ?? 0.15),
    profit_effect: Number(w.profit_effect ?? 0.10),
    sector_breadth: Number(w.sector_breadth ?? 0.05),
    style_risk: Number(w.style_risk ?? 0.05),
  }
}

// ---------------------------------------------------------------------------
// 三大指数 1m K (Market Pulse 顶部 3 张指数卡联动)
// ---------------------------------------------------------------------------
export interface IndexKlinePoint {
  /** "2026-06-12 09:31:00" */
  time: string
  /** 毫秒时间戳 (前端直接喂给 ChartPanel) */
  timestamp: number
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  /** 手 (1手=100股), klinecharts volumePrecision=0 */
  volume: number | null
  /** 元 (1手=100元) */
  turnover: number | null
}

export interface IndexKlineItem {
  ok: boolean
  /** 6 位纯数字, 例 "000001" (跟现有 target_type=index 约定一致) */
  code: string
  /** 中文名, 例 "上证指数" */
  name: string
  /** 交易日 YYYY-MM-DD */
  date: string
  interval: "1m"
  /** 上一交易日 1d K 的收盘 (用于卡片上"昨收"标签), 可能为 null (拉不到 1d 时) */
  previousClose: number | null
  source?: string
  points: IndexKlinePoint[]
  error?: string
}

export interface IndexKlineBatchResponse {
  ok: boolean
  date: string
  interval: string
  items: IndexKlineItem[]
  error?: string
}

export async function fetchIndexKlineBatch(params: {
  codes?: string[]
  date: string
  interval?: "1m"
}): Promise<IndexKlineBatchResponse> {
  const codes = (params.codes && params.codes.length > 0
    ? params.codes
    : ["000001", "399001", "399006"]
  ).join(",")
  const query = new URLSearchParams({
    codes,
    date: params.date,
    interval: params.interval ?? "1m",
  })
  const res = await fetchWithRetry(`${API_BASE}/api/index-kline/batch?${query.toString()}`)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    throw new Error((data?.error as string) || `获取指数K线失败: ${res.status}`)
  }
  const rawItems = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    date: String(data.date ?? params.date),
    interval: String(data.interval ?? params.interval ?? "1m"),
    items: rawItems.map((it) => ({
      ok: Boolean(it.ok),
      code: String(it.code ?? ""),
      name: String(it.name ?? it.code ?? ""),
      date: String(it.date ?? params.date),
      interval: (it.interval as "1m") ?? "1m",
      previousClose:
        typeof it.previousClose === "number" && Number.isFinite(it.previousClose)
          ? (it.previousClose as number)
          : null,
      source: typeof it.source === "string" ? (it.source as string) : undefined,
      points: Array.isArray(it.points)
        ? (it.points as Array<Record<string, unknown>>).map((p) => ({
            time: String(p.time ?? ""),
            timestamp: typeof p.timestamp === "number" ? (p.timestamp as number) : 0,
            open: (p.open as number) ?? null,
            high: (p.high as number) ?? null,
            low: (p.low as number) ?? null,
            close: (p.close as number) ?? null,
            volume: (p.volume as number) ?? null,
            turnover: (p.turnover as number) ?? null,
          }))
        : [],
      error: typeof it.error === "string" ? (it.error as string) : undefined,
    })),
    error: typeof data.error === "string" ? (data.error as string) : undefined,
  }
}

export interface IndexDailyItem {
  tradeDate: string
  close: number
  /** 成交额 (元). 后端 duckdb.index_daily_raw.amount 原值, 未做单位换算. */
  amount?: number
}

export interface IndexDailyResponse {
  ok: boolean
  code: string
  name: string
  start: string
  end: string
  count: number
  items: IndexDailyItem[]
  error?: string
}

/**
 * 拉单只宽基指数日线历史 (Market Sentiment 顶卡 / POC 叠加用).
 * 数据源: backend.api.stock_chart.index_daily_history → duckdb.index_daily_raw.
 */
export async function fetchIndexDailyHistory(params: {
  code: string
  start: string  // YYYY-MM-DD
  end: string    // YYYY-MM-DD
}): Promise<IndexDailyResponse> {
  const query = new URLSearchParams({
    code: params.code,
    start: params.start,
    end: params.end,
  })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/index/daily?${query.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    throw new Error((data?.error as string) || `获取指数日线失败: ${res.status}`)
  }
  const rawItems = Array.isArray(data.items)
    ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    code: String(data.code ?? params.code),
    name: String(data.name ?? params.code),
    start: String(data.start ?? params.start),
    end: String(data.end ?? params.end),
    count: typeof data.count === "number" ? data.count : rawItems.length,
    items: rawItems.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      close: typeof it.close === "number" ? it.close : Number(it.close ?? 0),
      amount: typeof it.amount === "number" ? it.amount : Number(it.amount ?? 0),
    })),
    error: typeof data.error === "string" ? (data.error as string) : undefined,
  }
}

export async function triggerMarketOverviewAkshareRefresh(): Promise<{
  ok: boolean
  snapshot?: MarketOverview
  error?: string
}> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-overview-akshare/refresh`, {
    method: "POST",
  })
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) return { ok: false, error: "refresh failed" }
  return {
    ok: Boolean(data.ok),
    snapshot: (data.snapshot as MarketOverview | undefined) ?? undefined,
    error: (data.error as string | undefined) ?? undefined,
  }
}

/** market_overview_daily 单日条目 (POC 等历史/对齐场景用).
 *  与 fetchMarketOverviewAkshare 同 shape 的核心字段, 加 tradeDate + fromCache.
 *  单位: totalAmount / mainNetInflow / 其余资金流字段一律 "亿元".
 */
export interface MarketOverviewHistoryItem {
  tradeDate: string
  totalAmount: number | null      // 亿
  totalVolume: number | null      // 万手
  risingCount: number | null
  fallingCount: number | null
  flatCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  stockCount: number | null
  mainNetInflow: number | null    // 亿 (主力 = 超大 + 大)
  superLargeNetInflow: number | null
  largeNetInflow: number | null
  mediumNetInflow: number | null
  smallNetInflow: number | null
  mainNetInflowRatio: number | null
  source?: string
  fromCache?: boolean
}

export interface MarketOverviewHistoryResponse {
  ok: boolean
  start: string
  end: string
  count: number
  items: MarketOverviewHistoryItem[]
  error?: string
}

const _parseNullableNumber = (v: unknown): number | null => {
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const _parseNullableInt = (v: unknown): number | null => {
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? Math.round(n) : null
}

/** 拉大盘概况历史区间 (大盘成交额 + 主力净流入 + 涨跌家数等).
 *  数据源: backend.api.stock_chart.stock_chart_market_overview_history → duckdb.market_overview_daily.
 *  返回 items 已是升序, 字段单位统一为 "亿" (资金流/成交额).
 */
export async function fetchMarketOverviewHistory(params: {
  start: string
  end: string
}): Promise<MarketOverviewHistoryResponse> {
  const query = new URLSearchParams({ start: params.start, end: params.end })
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/market-overview/history?${query.toString()}`,
  )
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) {
    return { ok: false, start: params.start, end: params.end, count: 0, items: [], error: `HTTP ${res.status}` }
  }
  const raw = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : []
  return {
    ok: Boolean(data.ok),
    start: String(data.start ?? params.start),
    end: String(data.end ?? params.end),
    count: typeof data.count === "number" ? data.count : raw.length,
    items: raw.map((it) => ({
      tradeDate: String(it.tradeDate ?? ""),
      totalAmount: _parseNullableNumber(it.totalAmount),
      totalVolume: _parseNullableNumber(it.totalVolume),
      risingCount: _parseNullableInt(it.risingCount),
      fallingCount: _parseNullableInt(it.fallingCount),
      flatCount: _parseNullableInt(it.flatCount),
      limitUpCount: _parseNullableInt(it.limitUpCount),
      limitDownCount: _parseNullableInt(it.limitDownCount),
      stockCount: _parseNullableInt(it.stockCount),
      mainNetInflow: _parseNullableNumber(it.mainNetInflow),
      superLargeNetInflow: _parseNullableNumber(it.superLargeNetInflow),
      largeNetInflow: _parseNullableNumber(it.largeNetInflow),
      mediumNetInflow: _parseNullableNumber(it.mediumNetInflow),
      smallNetInflow: _parseNullableNumber(it.smallNetInflow),
      mainNetInflowRatio: _parseNullableNumber(it.mainNetInflowRatio),
      source: typeof it.source === "string" ? it.source : undefined,
      fromCache: Boolean(it.fromCache),
    })),
    error: typeof data.error === "string" ? (data.error as string) : undefined,
  }
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/targets`)
  return (await res.json()) as { items: ApplicationAnalysisTarget[]; config: Record<string, unknown> }
}

export async function saveApplicationAnalysisTargets(payload: { horizon: Record<string, number>; items: ApplicationAnalysisTarget[] }): Promise<{ ok: boolean; config: Record<string, unknown> }> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/targets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  return (await res.json()) as { ok: boolean; config: Record<string, unknown> }
}

export async function fetchApplicationAnalysisResult(targetId: string): Promise<ApplicationAnalysisResponse & { _meta_result_path: string; _meta_history: ApplicationAnalysisResultFile[] }> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/results/${encodeURIComponent(targetId)}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取分析结果失败")
  }
  return (await res.json()) as ApplicationAnalysisResponse & { _meta_result_path: string; _meta_history: ApplicationAnalysisResultFile[] }
}

export async function triggerApplicationAnalysis(targetId: string | null): Promise<{ ok: boolean; target_id?: string; error?: string; items?: unknown[] }> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: targetId || null }),
  })
  return (await res.json()) as { ok: boolean; target_id?: string; error?: string; items?: unknown[] }
}

export async function fetchApplicationAnalysisSchedulerStatus(): Promise<ApplicationAnalysisSchedulerStatus> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/scheduler`)
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/recent30/refresh`, {
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
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/application-analysis/recent30/${encodeURIComponent(targetId)}?limit=${encodeURIComponent(String(limit))}`,
  )
  return (await res.json()) as ApplicationAnalysisDailySnapshotResponse
}

export async function readApplicationAnalysisRecent30(
  targetId: string,
  date: string,
): Promise<ApplicationAnalysisDailySnapshotResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/application-analysis/recent30/${encodeURIComponent(targetId)}/${encodeURIComponent(date)}`,
  )
  return (await res.json()) as ApplicationAnalysisDailySnapshotResponse
}

export async function controlApplicationAnalysisScheduler(action: "start" | "stop"): Promise<{ ok: boolean; status: ApplicationAnalysisSchedulerStatus }> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/application-analysis/scheduler/${action}`, { method: "POST" })
  return (await res.json()) as { ok: boolean; status: ApplicationAnalysisSchedulerStatus }
}

export async function fetchMarketOverview(): Promise<Record<string, unknown>> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/market-overview`)
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
  const res = await fetchWithRetry(url)
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
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as StyleSectorListResponse | null
  if (!res.ok || !data) throw new Error("获取风格板块失败")
  return data
}

// ---------------------------------------------------------------------------
// 单个风格板块的成分股 + 轻量行情
// 后端: GET /api/stock-chart/style-sectors/<name>/constituents
// 行情来源: 腾讯 qt.gtimg.cn 批量快照 (30s 进程内缓存)
// ---------------------------------------------------------------------------
export interface StyleSectorConstituent {
  /** 6 位 code, 已去除 sz/sh/bj 前缀 */
  code: string
  /** 原始带前缀 code (sz000048), 调试用, 平时前端不用 */
  raw_code?: string
  name: string
  last_price: number | null
  pre_close_price: number | null
  open: number | null
  high: number | null
  low: number | null
  change_pct: number | null
  change_amount: number | null
  /** 振幅 % = (high - low) / pre_close * 100 */
  amplitude: number | null
  /** 成交额 (元, tencent field[37]) */
  turnover_amount: number | null
  /** 换手率 % = volume(手) / (流通股/100) * 100 */
  turnover_rate: number | null
  /** 成交量 (手) */
  volume: number | null
  /** 流通市值 (元) */
  circulating_market_cap: number | null
  /** 流通股 (股) = 流通市值 / 现价 */
  circulating_shares: number | null
  valid: boolean
}

export interface StyleSectorConstituentsResponse {
  ok: boolean
  name: string
  codes: string[]
  constituents: StyleSectorConstituent[]
  sample_size: number
  valid_size: number | null
  change_pct: number | null
  fetched_at: string
  error?: string
}

export async function fetchStyleSectorConstituents(
  name: string,
): Promise<StyleSectorConstituentsResponse> {
  // 走 encodeURIComponent 处理中文
  const url = `${API_BASE}/api/stock-chart/style-sectors/${encodeURIComponent(name)}/constituents`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as StyleSectorConstituentsResponse | null
  if (!res.ok || !data) throw new Error(`获取 ${name} 成分股失败`)
  return data
}

export async function fetchMarketPulseRotationTrend(
  days = 10,
  topN = 10
): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/rotation-trend?days=${days}&topN=${topN}`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取轮动趋势失败")
  return data
}

export async function fetchMarketPulseIndustryCompare(
  industries: string[],
  days = 120,
): Promise<IndustryCompareResponse> {
  const params = new URLSearchParams()
  params.set("days", String(days))
  industries
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => params.append("industry", item))
  const url = `${API_BASE}/api/stock-chart/market-pulse/industry-compare?${params.toString()}`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as IndustryCompareResponse | null
  if (!res.ok || !data) throw new Error("获取行业对比历史失败")
  return data
}

export async function fetchIndustryFundFlowIndustryList(
  days = 365,
): Promise<IndustryFundFlowIndustryListResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/fund-flow/industry-series?days=${days}`
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as IndustryFundFlowIndustryListResponse | null
  if (!res.ok || !data) throw new Error("获取行业列表失败")
  return data
}

// ---------------------------------------------------------------------------
// 涨跌停情绪 (limitEmotion) 类型与请求
//
// 4 块语义: 涨停 / 跌停 / 炸板率 / 连板体系.
// 后端路径: /api/stock-chart/market-pulse/limit-emotion
// ---------------------------------------------------------------------------
export type LimitEmotionStreakSentimentLevel =
  | "ice"
  | "weak"
  | "normal"
  | "active"
  | "hot"

export type LimitEmotionMarketStatus =
  | "pre_open"
  | "trading"
  | "closed"
  | "unknown"

export type LimitEmotionDataStatus =
  | "normal"
  | "partial"
  | "stale"
  | "empty"

export type LimitEmotionBreakBoardStatus = "ready" | "unavailable"

export interface LimitEmotionLeader {
  code: string
  name: string
  streak: number
}

export interface LimitEmotionDistributionRow {
  streak: number
  count: number
  stocks: LimitEmotionStock[]
}

export interface LimitEmotionPromotionLevel {
  from: number
  to: number
  yesterdayCount: number
  todayPromotedCount: number
  rate: number | null
}

export interface LimitEmotionPromotion {
  overallRate: number | null
  levels: LimitEmotionPromotionLevel[]
}

export interface LimitEmotionBrokenStock {
  code: string
  name: string
  previousStreak: number
  changePct: number | null
}

export interface LimitEmotionBroken {
  count: number
  highStreakBrokenCount: number
  stocks: LimitEmotionBrokenStock[]
}

export interface LimitEmotionStreak {
  maxHeight: number | null
  label: "连板高度"
  leaders: LimitEmotionLeader[]
  distribution: LimitEmotionDistributionRow[]
  promotion: LimitEmotionPromotion
  broken: LimitEmotionBroken
  sentiment: {
    level: LimitEmotionStreakSentimentLevel
    text: string
  }
}

export interface LimitEmotionStock {
  code: string
  name: string
  changePct?: number | null
  industry?: string | null
  concepts?: string[]
  limitUpPrice?: number | null
  limitDownPrice?: number | null
}

export interface LimitEmotionPayload {
  limitUp: {
    count: number | null
    label: "涨停"
    stocks?: LimitEmotionStock[]
  }
  limitDown: {
    count: number | null
    label: "跌停"
    stocks?: LimitEmotionStock[]
  }
  breakBoard: {
    touchedCount: number | null
    brokenCount: number | null
    rate: number | null
    status: LimitEmotionBreakBoardStatus
    label: "炸板率"
    brokenStocks?: LimitEmotionStock[]
  }
  streak: LimitEmotionStreak
  tradeDate: string | null
  updateTime: string | null
  marketStatus: LimitEmotionMarketStatus | null
  dataStatus: LimitEmotionDataStatus
  ok?: boolean
  _meta?: Record<string, unknown>
}

export async function fetchMarketPulseLimitEmotion(): Promise<LimitEmotionPayload> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/limit-emotion`
  const res = await fetchWithRetry(url, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as
    | (LimitEmotionPayload & { ok: boolean; error?: string })
    | null
  if (!res.ok || !data) {
    throw new Error(data?.error || "获取涨跌停情绪失败")
  }
  return data
}

export async function refreshMarketPulseLimitEmotion(): Promise<LimitEmotionPayload> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/limit-emotion/refresh`
  const res = await fetchWithRetry(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as
    | (LimitEmotionPayload & { ok: boolean; error?: string })
    | null
  if (!res.ok || !data) throw new Error(data?.error || "刷新涨跌停情绪失败")
  return data
}

export async function fetchIndustryDetail(
  name: string,
  topN = 30
): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse/industry-detail?name=${encodeURIComponent(name)}&topN=${topN}`
  const res = await fetchWithRetry(url)
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
  tradeDate?: string | null
  rowCount: number
  totalPages: number | null
  pageRowCounts: number[]
  fetchedAt: string | null
  rows: IndustryFundFlowRow[]
  source?: string | null
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
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as IndustryFundFlowResponse | null
  if (!res.ok || !data) throw new Error("获取同花顺行业资金失败")
  return data
}

export async function refreshIndustryFundFlow(): Promise<IndustryFundFlowResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/fund-flow/refresh`
  const res = await fetchWithRetry(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as IndustryFundFlowResponse | null
  if (!res.ok || !data) throw new Error("刷新同花顺行业资金失败")
  return data
}

export async function fetchIndustryFundFlowHistory(date?: string): Promise<Record<string, unknown>> {
  const url = date
    ? `${API_BASE}/api/stock-chart/ths-industry/fund-flow/history?date=${encodeURIComponent(date)}`
    : `${API_BASE}/api/stock-chart/ths-industry/fund-flow/history`
  const res = await fetchWithRetry(url)
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
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as IndustryConstituentsResponse | null
  if (!res.ok || !data) throw new Error(`获取行业 ${code} 成分股失败`)
  return data
}

export async function refreshIndustryConstituentsByCode(code: string): Promise<IndustryConstituentsResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-by-code/refresh?code=${encodeURIComponent(code)}`
  const res = await fetchWithRetry(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as IndustryConstituentsResponse | null
  if (!res.ok || !data) throw new Error(`刷新行业 ${code} 成分股失败`)
  return data
}

export async function fetchCachedIndustryConstituentsCodes(): Promise<{ ok: boolean; codes: string[] }> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-by-code/cached`
  const res = await fetchWithRetry(url)
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
  const res = await fetchWithRetry(url)
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
  /** 端点永远从磁盘读 (ths_industry_constituents_daily_scheduler 17:00 收盘后落盘) */
  dataSource: "disk"
  /** 今天是不是 A 股交易日 */
  isTradingDay: boolean
  /** 当前是不是盘内 (9:30-11:30 / 13:00-15:00) */
  isMarketOpen: boolean
  /**
   * 交易时间窗状态:
   *   - "trading":                  盘内, 14 列数据是 "今天盘中" (来自上一交易日 17:00 持久化)
   *   - "trading_day_off_hours":     交易日但非盘内 (午休 / 收盘后), 数据同上
   *   - "non_trading_day":           非交易日 (周末 / 节假日)
   */
  tradingHoursMode: "trading" | "trading_day_off_hours" | "non_trading_day"
  /** 数据快照日期: 17:00 后 = 今日, 17:00 前 = 上一交易日 */
  snapshotDate: string | null
  error?: string
}

/** 按 6 位 code 查 (推荐, URL 用 ?code=, 无 name→code 解析) */
export async function fetchIndustryConstituentsFromIndexByCode(
  code: string
): Promise<IndustryConstituentsIndexResponse> {
  const url = `${API_BASE}/api/stock-chart/ths-industry/constituents-file?code=${encodeURIComponent(code)}`
  const res = await fetchWithRetry(url)
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
  const res = await fetchWithRetry(url)
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
  const res = await fetchWithRetry(url)
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("获取 scheduler 状态失败")
  return data
}

export async function triggerMarketPulseSnapshot(): Promise<Record<string, unknown>> {
  const url = `${API_BASE}/api/stock-chart/market-pulse-scheduler/trigger`
  const res = await fetchWithRetry(url, { method: "POST" })
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null
  if (!res.ok || !data) throw new Error("手动触发 snapshot 失败")
  return data
}

// AI Provider API docs:
//   design/frontend/ai-provider.md
// Keep that document in sync when changing these types or request helpers.

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

export async function fetchAiCapabilities(): Promise<AiCapability[]> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/capabilities`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as { items?: AiCapability[] } | null
  if (!res.ok || !data) throw new Error("获取 AI 能力列表失败")
  return data.items || []
}

export async function fetchAiProviderTypes(): Promise<AiProviderType[]> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/provider-types`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as { items?: AiProviderType[] } | null
  if (!res.ok || !data) throw new Error("获取 AI Provider 类型失败")
  return data.items || []
}

export async function fetchAiProviders(): Promise<AiProviderItem[]> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/providers`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as { items?: AiProviderItem[] } | null
  if (!res.ok || !data) throw new Error("获取 AI Provider 失败")
  return data.items || []
}

export async function createAiProvider(payload: Partial<AiProviderItem>): Promise<AiProviderItem> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  const data = (await res.json().catch(() => null)) as AiProviderItem | { error?: string } | null
  if (!res.ok || !data || !("id" in data)) {
    throw new Error((data && "error" in data && data.error) || "创建 AI Provider 失败")
  }
  return data
}

export async function updateAiProvider(id: string, payload: Partial<AiProviderItem>): Promise<AiProviderItem> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/providers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  const data = (await res.json().catch(() => null)) as AiProviderItem | { error?: string } | null
  if (!res.ok || !data || !("id" in data)) {
    throw new Error((data && "error" in data && data.error) || "更新 AI Provider 失败")
  }
  return data
}

export async function deleteAiProvider(id: string): Promise<void> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/providers/${id}`, { method: "DELETE" })
  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as { error?: string } | null
    throw new Error(data?.error || "删除 AI Provider 失败")
  }
}

export async function fetchAiBindings(): Promise<AiBindingItem[]> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/bindings`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as { items?: AiBindingItem[] } | null
  if (!res.ok || !data) throw new Error("获取 AI 绑定失败")
  return data.items || []
}

export async function upsertAiBinding(payload: Partial<AiBindingItem>): Promise<AiBindingItem> {
  const res = await fetchWithRetry(`${API_BASE}/api/ai/bindings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  const data = (await res.json().catch(() => null)) as AiBindingItem | { error?: string } | null
  if (!res.ok || !data || !("id" in data)) {
    throw new Error((data && "error" in data && data.error) || "保存 AI 绑定失败")
  }
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
  const res = await fetchWithRetry(`${API_BASE}/api/export-markdown/${taskId}`);
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
  const res = await fetchWithRetry(`${API_BASE}/api/status`);
  return res.json();
}

export async function parseDownloaderUrl(url: string): Promise<DownloaderParseData> {
  const params = new URLSearchParams({ url });
  const res = await fetchWithRetry(`${DOWNLOADER_API_BASE}/api/parse?${params.toString()}`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/reference/mp4-history`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/reference/mp4-history`, { cache: "no-store" });
  const data = (await res.json().catch(() => null)) as { items?: MP4HistoryListItem[] } | null;
  if (!res.ok || !data) {
    throw new Error("获取历史记录失败");
  }
  return data.items || [];
}

export async function reorderMP4History(orderedIds: string[]): Promise<MP4HistoryListItem[]> {
  const res = await fetchWithRetry(`${API_BASE}/api/reference/mp4-history/reorder`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/reference/mp4-history/${historyId}`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/reference/mp4-history/${id}`, { cache: "no-store" });
  const data = (await res.json().catch(() => null)) as MP4HistoryRecord | { error?: string } | null;
  if (!res.ok || !data || !("task" in data)) {
    throw new Error((data && "error" in data && data.error) || "获取历史详情失败");
  }
  return data;
}

export async function sendDownloaderResultToParse(payload: RemoteParsePayload): Promise<{ task_id: string; file_name: string }> {
  const res = await fetchWithRetry(`${API_BASE}/api/parse-video`, {
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
  const res = await fetchWithRetry(
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
  /** 后端按 JOB_CATEGORY_MAP 注入: job 属于的所有 category id (numeric, BIGSERIAL). 多对多, 已按 sort_order 排好. */
  categories?: number[]
  /** 每个 category 中该 job 的排序权重 (key: category_id, value: sort_order). 前端用于按执行顺序排列. */
  categorySortOrders?: Record<number, number>
  supports_enable: boolean
  enabled: boolean
  config_enabled: boolean
  config: Record<string, unknown>
  live: Record<string, unknown>
  /** 后端归一化的"上次运行"摘要, 前端只读这六个字段, 不用管各 scheduler 异构字段名. */
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

// ---------------------------------------------------------------------------
// Scheduler categories (从后端 /api/scheduler/categories 拉, 给 tab 用)
// ---------------------------------------------------------------------------

export interface SchedulerCategory {
  id: number
  label: string
  /** lucide 图标名, 前端 ICON_MAP 映射到组件 */
  icon_hint: string
  sort_order: number
  description?: string
  /** 该 category 下的 job 数 */
  count: number
}

export interface SchedulerCategoriesResponse {
  ok: boolean
  items: SchedulerCategory[]
  count: number
  error?: string
}

// ---------------------------------------------------------------------------
// Scheduler daily run statistics
// ---------------------------------------------------------------------------

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

export async function fetchSchedulerDailyStats(days = 14): Promise<SchedulerDailyStatsResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/scheduler/stats/daily?days=${encodeURIComponent(String(days))}`,
    { cache: "no-store" },
  )
  const data = (await res.json().catch(() => null)) as SchedulerDailyStatsResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务日统计失败")
  return data
}

export async function fetchSchedulerCategories(): Promise<SchedulerCategoriesResponse> {
  const res = await fetchWithRetry(`${API_BASE}/api/scheduler/categories`, { cache: "no-store" })
  const data = (await res.json().catch(() => null)) as SchedulerCategoriesResponse | null
  if (!res.ok || !data) throw new Error("获取调度任务分类失败")
  return data
}

export async function fetchSchedulerJobs(): Promise<SchedulerJobsResponse> {
  const res = await fetchWithRetry(`${API_BASE}/api/scheduler/jobs`, { cache: "no-store" })
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

/** 单条 job run history (来自 /api/scheduler/jobs/<id>/history). */
export interface SchedulerJobHistoryItem {
  id?: string
  start_at: string
  end_at: string
  /** 触发方式: "auto" = cron 自动 / "manual" = 手动点"立即触发" */
  trigger_type: "auto" | "manual" | string
  /** 运行结果: success / failed / skipped / running / processing */
  status: "success" | "failed" | "skipped" | "running" | "processing" | string
  /** 失败时的错误信息 (成功时为 null) */
  error: string | null
  /** 成功时的详情信息 (如 "ok, parsed 12236 files → daily_raw"), 失败时为 null */
  message?: string | null
  /** 耗时 (秒) */
  duration_seconds: number | null
  /** application_analysis 专用: 本次触发的标的数 / 成功数 */
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

export async function fetchSchedulerJobHistory(
  jobId: string,
  limit = 50,
): Promise<SchedulerJobHistoryResponse> {
  const res = await fetchWithRetry(
    `${API_BASE}/api/scheduler/jobs/${encodeURIComponent(jobId)}/history?limit=${encodeURIComponent(String(limit))}`,
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
  const res = await fetchWithRetry(`${API_BASE}/api/scheduler/jobs/${encodeURIComponent(jobId)}/${action}`, {
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
export const triggerSchedulerJob = (jobId: string, options?: { targetDate?: string | null }) =>
  postSchedulerAction(
    jobId,
    "trigger",
    options?.targetDate ? { target_date: options.targetDate } : undefined,
  )
export const startSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "start")
export const stopSchedulerJob = (jobId: string) => postSchedulerAction(jobId, "stop")

/** 从 jobs.json 注册表里删除一个 job (后端同时停掉运行中的线程) */
export async function deleteSchedulerJob(jobId: string): Promise<SchedulerJobActionResponse> {
  const res = await fetchWithRetry(`${API_BASE}/api/scheduler/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  })
  const data = (await res.json().catch(() => null)) as SchedulerJobActionResponse | null
  if (!res.ok || !data) {
    throw new Error(data?.error || `删除 job ${jobId} 失败`)
  }
  return data
}

// ---------------------------------------------------------------------------
// Self-Selected（/stock-overview/self-selected 页面用）
// ---------------------------------------------------------------------------

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
    await fetchWithRetry(`${API_BASE}/api/self-selected/groups`, { cache: "no-store" }),
  )
}

export async function createSelfSelectedGroup(
  payload: { name: string; description?: string; color?: string },
): Promise<SelfSelectedGroupActionResponse> {
  return selfSelectedJson<SelfSelectedGroupActionResponse>(
    await fetchWithRetry(`${API_BASE}/api/self-selected/groups`, {
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
    await fetchWithRetry(`${API_BASE}/api/self-selected/groups/${encodeURIComponent(groupId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function deleteSelfSelectedGroup(groupId: string): Promise<SelfSelectedGroupActionResponse> {
  return selfSelectedJson<SelfSelectedGroupActionResponse>(
    await fetchWithRetry(`${API_BASE}/api/self-selected/groups/${encodeURIComponent(groupId)}`, {
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
    await fetchWithRetry(url, { cache: "no-store" }),
  )
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
  return selfSelectedJson<SelfSelectedItemActionResponse>(
    await fetchWithRetry(`${API_BASE}/api/self-selected/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function updateSelfSelectedItem(
  itemId: string,
  payload: Partial<Pick<SelfSelectedItem, "group_id" | "symbol" | "market" | "name" | "notes" | "target_type" | "sort_order">>,
): Promise<SelfSelectedItemActionResponse> {
  return selfSelectedJson<SelfSelectedItemActionResponse>(
    await fetchWithRetry(`${API_BASE}/api/self-selected/items/${encodeURIComponent(itemId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )
}

export async function deleteSelfSelectedItem(itemId: string): Promise<SelfSelectedItemActionResponse> {
  return selfSelectedJson<SelfSelectedItemActionResponse>(
    await fetchWithRetry(`${API_BASE}/api/self-selected/items/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    }),
  )
}

// =============================================================================
// 行业 / 概念 应用面分析（独立于 application-analysis）
// =============================================================================

export async function fetchIndustryApplicationTargets(): Promise<IndustryApplicationConfig> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/targets`)
  return (await res.json()) as IndustryApplicationConfig
}

export async function saveIndustryApplicationTargets(payload: {
  horizon: { days: number; segments: number }
  items: IndustryApplicationConfig["items"]
}): Promise<IndustryApplicationConfig> {
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/targets`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/target-codes`)
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/kline?${params.toString()}`)
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/refresh`, {
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
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/results/${encodeURIComponent(targetId)}`)
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
  const res = await fetchWithRetry(
    `${API_BASE}/api/stock-chart/industry-application/overview${qs ? `?${qs}` : ""}`,
  )
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取板块总览失败")
  }
  return (await res.json()) as IndustryApplicationOverviewResponse
}

export type HeatmapKind = "industries" | "concepts" | "styles"

const YI_TO_YUAN = 1e8

export async function fetchMarketHeatmap(
  kind: HeatmapKind = "industries",
  top_n = 200
): Promise<MarketHeatmapResponse> {
  const params = new URLSearchParams({ kind, top_n: String(top_n) })
  const res = await fetchWithRetry(`${API_BASE}/api/stock-chart/industry-application/heatmap?${params.toString()}`)
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(data.error || "拉取市场热力图失败")
  }
  const raw = (await res.json()) as MarketHeatmapResponse
  // 统一单位: 后端 sector.amount / sector.circulatingMarketCap 是 **亿**, 转到 **元**
  // (跟 StockHeatmapItem.amount / circulatingMarketCap 一致, 便于 formatAmount / treemap 面积)
  if (raw?.items) {
    raw.items = raw.items.map((sector) => ({
      ...sector,
      amount: (sector.amount ?? 0) * YI_TO_YUAN,
      circulatingMarketCap: (sector.circulatingMarketCap ?? 0) * YI_TO_YUAN,
      children: [],  // 首屏不展开 children, 清空避免误用
    }))
  }
  return raw
}
