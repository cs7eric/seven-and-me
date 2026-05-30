import type { Phase, SSEEvent, QAResponse, TransferProgress } from "./types";

const API_BASE = "http://localhost:5000";
const DOWNLOADER_API_BASE = "https://downloader-api.bhwa233.com";

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
