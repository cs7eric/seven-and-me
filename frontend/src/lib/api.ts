import type { SSEEvent, QAResponse } from "./types";

const API_BASE = "http://localhost:5000";

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

      if (event.type === "done" || event.type === "error") {
        if (event.type === "error") {
          callbacks.onError?.(event.error || "未知错误");
        } else {
          callbacks.onDone?.();
        }
        es.close();
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    callbacks.onError?.("连接断开，请稍后重试");
    es.close();
  };

  return es;
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