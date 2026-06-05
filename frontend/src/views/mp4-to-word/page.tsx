import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Phase, PostMetadata, SSEEvent, TransferProgress } from "../../lib/types";
import { askQuestion, createSSEConnection, exportMarkdown, fetchTaskSnapshot, saveMP4History, sendDownloaderResultToParse, uploadFile, uploadFileWithProgress } from "../../lib/api";
import { toast } from "sonner";
import { QA_STYLE_FIX } from "./styles";
import { buildSummaryCards } from "./lib/summary-renderer";
import { renderQaAnswer } from "./lib/qa-renderer";
import { AskSection } from "./components/AskSection";
import { FloatingAskBar } from "./components/FloatingAskBar";
import { ReaderModal } from "./components/ReaderModal";
import { WorkspaceShell } from "@/layout/workspace-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, BookOpen, Captions, CheckCircle2, Code2, Copy, Download, ExternalLink, FileAudio, FileText, Info, ListChecks, Sparkles, UploadCloud } from "lucide-react";

interface QaItem {
  id: string;
  question: string;
  answerHtml?: string;
  loading?: boolean;
}

interface RemoteTaskDraft {
  downloadUrl: string;
  title: string;
  sourceUrl: string;
  platform: string;
  duration?: number;
  noteType: string;
  audioUrl: string;
}

function formatBytes(value?: number) {
  if (!value || value <= 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let current = value;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current >= 100 || index === 0 ? current.toFixed(0) : current.toFixed(1)} ${units[index]}`;
}

function formatDurationSeconds(value?: number | null) {
  if (value == null || Number.isNaN(value) || value < 0) return "--";
  const total = Math.floor(value);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function formatMediaDuration(value?: number) {
  if (!value || Number.isNaN(value)) return "--";
  const total = Math.max(0, Math.floor(value));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return [h, m, s].map((part, index) => (index === 0 ? String(part) : String(part).padStart(2, "0"))).join(":");
  }
  return [m, s].map((part) => String(part).padStart(2, "0")).join(":");
}

function compactUrl(value: string) {
  if (!value) return "--";
  try {
    const url = new URL(value);
    const tail = url.pathname.split("/").filter(Boolean).pop() || "";
    return `${url.hostname}${tail ? ` / ${tail.slice(0, 36)}` : ""}`;
  } catch {
    return value.length > 56 ? `${value.slice(0, 56)}...` : value;
  }
}

function TextSkeletonBlock({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-1">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton
          key={index}
          className={`h-4 ${index % 4 === 3 ? "w-2/3" : index % 3 === 2 ? "w-4/5" : "w-full"}`}
        />
      ))}
    </div>
  );
}

function ProgressCard({
  title,
  description,
  progress,
  transferred,
  total,
  eta,
  speed,
}: {
  title: string;
  description: string;
  progress: TransferProgress;
  transferred: number;
  total: number;
  eta?: number | null;
  speed?: number;
}) {
  const percent = Math.max(0, Math.min(100, Math.round(progress.progress || 0)));
  const status = percent >= 100 ? "Done" : progress.phase || "Running";

  return (
    <Card className="overflow-hidden border-white/70 bg-white/75 shadow-[0_24px_70px_rgba(15,23,42,0.08)] backdrop-blur-xl">
      <CardHeader className="gap-3 pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="inline-flex size-8 items-center justify-center rounded-full bg-slate-950 text-xs text-white">
                {title.slice(0, 1)}
              </span>
              {title}
            </CardTitle>
            <CardDescription className="leading-6">{description}</CardDescription>
          </div>
          <Badge variant={percent >= 100 ? "default" : "secondary"}>{status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span className="text-3xl font-semibold tracking-tight text-slate-950">{percent}%</span>
            <span className="text-xs text-muted-foreground">{formatBytes(transferred)} / {formatBytes(total)}</span>
          </div>
          <Progress value={percent} className="h-2.5" />
        </div>
        <div className="grid grid-cols-3 gap-3 rounded-2xl bg-slate-50/80 p-3">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Speed</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{speed ? `${formatBytes(speed)}/s` : "--"}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">ETA</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{formatDurationSeconds(eta)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Total</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{formatBytes(total)}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Mp4ToWordPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const remoteStartKeyRef = useRef("");
  const transcriptTargetRef = useRef("");
  const transcriptFrameRef = useRef<number | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTaskId = searchParams.get("task") || "";

  const remoteDraft = useMemo<RemoteTaskDraft | null>(() => {
    const mode = searchParams.get("mode");
    const downloadUrl = searchParams.get("downloadUrl") || "";
    if (mode !== "remote" || !downloadUrl) return null;
    const durationParam = searchParams.get("duration");
    return {
      downloadUrl,
      title: searchParams.get("title") || "未命名视频",
      sourceUrl: searchParams.get("sourceUrl") || downloadUrl,
      platform: searchParams.get("platform") || "Downloader",
      duration: durationParam ? Number(durationParam) : undefined,
      noteType: searchParams.get("noteType") || "video",
      audioUrl: searchParams.get("audioUrl") || "",
    };
  }, [searchParams]);

  const [phase, setPhase] = useState<Phase>(initialTaskId || remoteDraft ? "converting" : "idle");
  const [transcript, setTranscript] = useState("");
  const [displayedTranscript, setDisplayedTranscript] = useState("");
  const [polished, setPolished] = useState("");
  const [summary, setSummary] = useState("");
  const [taskId, setTaskId] = useState(initialTaskId);
  const [error, setError] = useState("");
  const [qaInput, setQaInput] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaItems, setQaItems] = useState<QaItem[]>([]);
  const [showReader, setShowReader] = useState(false);
  const [readerText, setReaderText] = useState("");
  const [readerTitle, setReaderTitle] = useState("");
  const [summaryRawMode, setSummaryRawMode] = useState(false);
  const [historySaving, setHistorySaving] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [collapsedQaItems, setCollapsedQaItems] = useState<Record<string, boolean>>({});
  const [remoteStarting, setRemoteStarting] = useState(false);
  const [remoteMeta, setRemoteMeta] = useState<PostMetadata | null>(null);
  const [remoteFileName, setRemoteFileName] = useState("");
  const [downloadProgress, setDownloadProgress] = useState<TransferProgress>({ progress: 0, phase: "pending" });
  const [intakeProgress, setIntakeProgress] = useState<TransferProgress>({ progress: 0, phase: "pending" });

  const currentStep =
    phase === "idle"
      ? 0
      : phase === "converting"
        ? 1
        : phase === "transcribing"
          ? 2
          : phase === "polishing"
            ? 3
            : 4;

  const resetProcessingState = useCallback((nextPhase: Phase) => {
    setPhase(nextPhase);
    setTranscript("");
    setDisplayedTranscript("");
    transcriptTargetRef.current = "";
    if (transcriptFrameRef.current) {
      cancelAnimationFrame(transcriptFrameRef.current);
      transcriptFrameRef.current = null;
    }
    setPolished("");
    setSummary("");
    setError("");
    setQaItems([]);
    setCollapsed({});
    setCollapsedQaItems({});
    setSummaryRawMode(false);
    setDownloadProgress({ progress: 0, phase: "pending" });
    setIntakeProgress({ progress: 0, phase: "pending" });
  }, []);

  const animateTranscriptTo = useCallback((nextText: string) => {
    setTranscript(nextText);
    transcriptTargetRef.current = nextText;

    if (transcriptFrameRef.current) return;

    const tick = () => {
      setDisplayedTranscript((current) => {
        const target = transcriptTargetRef.current;
        if (current === target) {
          transcriptFrameRef.current = null;
          return current;
        }

        if (!target.startsWith(current)) {
          return target;
        }

        const remaining = target.length - current.length;
        const step = Math.max(1, Math.min(18, Math.ceil(remaining / 8)));
        return target.slice(0, current.length + step);
      });

      if (transcriptFrameRef.current !== null) {
        transcriptFrameRef.current = requestAnimationFrame(tick);
      }
    };

    transcriptFrameRef.current = requestAnimationFrame(tick);
  }, []);

  const applyTaskSnapshot = useCallback((snapshot: Awaited<ReturnType<typeof fetchTaskSnapshot>>) => {
    const status = snapshot.status as Phase;
    animateTranscriptTo(snapshot.transcript || "");
    setPolished(snapshot.polished || "");
    setSummary(snapshot.summary || "");
    setRemoteFileName(snapshot.file_name || "");
    setDownloadProgress(snapshot.download_progress || { progress: 0, phase: "pending" });
    setIntakeProgress(snapshot.intake_progress || { progress: 0, phase: "pending" });

    if (snapshot.metadata) {
      setRemoteMeta(snapshot.metadata as unknown as PostMetadata);
    }

    if (snapshot.error) {
      setError(snapshot.error);
    }

    if (["downloading", "converting"].includes(String(snapshot.status))) {
      setPhase("converting");
      return;
    }

    if (["transcribing", "polishing", "summarizing", "done", "error"].includes(String(snapshot.status))) {
      setPhase(status);
    }
  }, [animateTranscriptTo]);

  const refreshTaskSnapshot = useCallback(async (id: string) => {
    try {
      const snapshot = await fetchTaskSnapshot(id);
      applyTaskSnapshot(snapshot);
    } catch {
      return;
    }
  }, [applyTaskSnapshot]);

  const downloadRemoteFileInBrowser = useCallback(async (draft: RemoteTaskDraft): Promise<File> => {
    const response = await fetch(draft.downloadUrl, { cache: "no-store" });
    if (!response.ok || !response.body) {
      throw new Error("浏览器下载远程文件失败");
    }

    const totalBytes = Number(response.headers.get("Content-Length") || 0);
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let downloadedBytes = 0;
    const startedAt = Date.now();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;

      chunks.push(value);
      downloadedBytes += value.byteLength;
      const elapsed = Math.max((Date.now() - startedAt) / 1000, 0.001);
      const speed = downloadedBytes / elapsed;
      const progress = totalBytes ? Math.round((downloadedBytes / totalBytes) * 100) : Math.min(95, Math.round(downloadedBytes / (4 * 1024 * 1024)));

      setDownloadProgress({
        phase: "browser-downloading",
        progress,
        downloaded_bytes: downloadedBytes,
        total_bytes: totalBytes,
        eta_seconds: totalBytes && speed > 0 ? Math.round((totalBytes - downloadedBytes) / speed) : null,
        speed_bytes_per_sec: Math.round(speed),
      });
    }

    const blob = new Blob(chunks.map((chunk) => chunk.slice().buffer), { type: response.headers.get("Content-Type") || "video/mp4" });
    const safeTitle = draft.title.replace(/[\\/:*?"<>|]/g, "_").trim() || "remote-video";
    const fileName = /\.[a-z0-9]{2,6}$/i.test(safeTitle) ? safeTitle : `${safeTitle}.mp4`;

    setDownloadProgress({
      phase: "done",
      progress: 100,
      downloaded_bytes: blob.size,
      total_bytes: totalBytes || blob.size,
      eta_seconds: 0,
      speed_bytes_per_sec: 0,
    });

    return new File([blob], fileName, { type: blob.type || "video/mp4" });
  }, []);

  const startTaskMonitoring = useCallback((id: string) => {
    setTaskId(id);
    void refreshTaskSnapshot(id);

    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const es = createSSEConnection(id, {
      onEvent: (event: SSEEvent) => {
        switch (event.type) {
          case "download_start":
            setRemoteFileName(event.file_name || "");
            setRemoteMeta(event.metadata || null);
            setDownloadProgress({
              progress: event.progress || 0,
              downloaded_bytes: event.downloaded_bytes || 0,
              total_bytes: event.total_bytes || 0,
              eta_seconds: event.eta_seconds,
              speed_bytes_per_sec: event.speed_bytes_per_sec || 0,
              phase: event.phase || "running",
            });
            setPhase("converting");
            break;
          case "download_progress":
            setDownloadProgress({
              progress: event.progress || 0,
              downloaded_bytes: event.downloaded_bytes || 0,
              total_bytes: event.total_bytes || 0,
              eta_seconds: event.eta_seconds,
              speed_bytes_per_sec: event.speed_bytes_per_sec || 0,
              phase: event.phase || "running",
            });
            setPhase("converting");
            break;
          case "ingest_progress":
            setIntakeProgress({
              progress: event.progress || 0,
              processed_bytes: event.processed_bytes || 0,
              total_bytes: event.total_bytes || 0,
              eta_seconds: event.eta_seconds,
              phase: event.phase || "preparing",
            });
            break;
          case "download_done":
            setDownloadProgress({
              progress: 100,
              downloaded_bytes: event.downloaded_bytes || 0,
              total_bytes: event.total_bytes || 0,
              eta_seconds: 0,
              speed_bytes_per_sec: event.speed_bytes_per_sec || 0,
              phase: "done",
            });
            break;
          case "ingest_done":
            setIntakeProgress({
              progress: event.progress || 100,
              processed_bytes: event.processed_bytes || 0,
              total_bytes: event.total_bytes || 0,
              eta_seconds: 0,
              phase: "done",
            });
            break;
          case "transcribe_start":
            setPhase("transcribing");
            break;
          case "chunk":
            animateTranscriptTo(event.text || "");
            setPhase("transcribing");
            break;
          case "transcribe_done":
            setPhase("polishing");
            break;
          case "polish_start":
            setPhase("polishing");
            break;
          case "polish_char":
            setPolished(event.text || "");
            setPhase("polishing");
            break;
          case "polish_done":
            setPolished((prev) => event.polished_text || event.text || prev);
            setPhase("summarizing");
            break;
          case "summary_start":
            setPhase("summarizing");
            break;
          case "summary_char":
            setSummary(event.text || "");
            setPhase("summarizing");
            break;
          case "summary_done":
            setSummary((prev) => event.summary_text || event.text || prev);
            setPolished((prev) => event.polished_text || prev);
            break;
          case "done":
            setPolished((prev) => event.polished_text || prev);
            setSummary((prev) => event.summary_text || prev);
            setRemoteMeta(event.metadata || remoteMeta);
            setPhase("done");
            setSearchParams({ task: id });
            break;
          case "error":
            setError(event.error || "Unknown error");
            setPhase("error");
            break;
        }
      },
      onError: () => {
        void refreshTaskSnapshot(id);
      },
      onDone: () => {
        setPhase("done");
      },
    });

    esRef.current = es;
  }, [animateTranscriptTo, remoteMeta, refreshTaskSnapshot, setSearchParams]);

  const startRemoteWorkflow = useCallback(async () => {
    if (!remoteDraft) return;
    const remoteStartKey = `${remoteDraft.downloadUrl}|${remoteDraft.title}|${remoteDraft.sourceUrl}`;
    if (remoteStarting || remoteStartKeyRef.current === remoteStartKey) return;
    remoteStartKeyRef.current = remoteStartKey;
    setRemoteStarting(true);
    resetProcessingState("converting");
    setRemoteMeta({
      title: remoteDraft.title,
      categories: [remoteDraft.platform],
      tags: [remoteDraft.noteType || "video"],
    });

    try {
      const file = await downloadRemoteFileInBrowser(remoteDraft);
      setRemoteFileName(file.name);
      const id = await uploadFileWithProgress(file, (progress) => {
        setIntakeProgress(progress);
      });
      startTaskMonitoring(id);
    } catch {
      try {
        const workflow = await sendDownloaderResultToParse({
          downloadUrl: remoteDraft.downloadUrl,
          title: remoteDraft.title,
          sourceUrl: remoteDraft.sourceUrl,
          metadata: {
            title: remoteDraft.title,
            platform: remoteDraft.platform,
            duration: remoteDraft.duration,
            noteType: remoteDraft.noteType,
            download_audio_url: remoteDraft.audioUrl,
            original_url: remoteDraft.sourceUrl,
          },
        });

        setRemoteFileName(workflow.file_name);
        startTaskMonitoring(workflow.task_id);
      } catch (fallbackError) {
        setError(fallbackError instanceof Error ? fallbackError.message : String(fallbackError));
        setPhase("error");
      }
    } finally {
      setRemoteStarting(false);
    }
  }, [downloadRemoteFileInBrowser, remoteDraft, remoteStarting, resetProcessingState, startTaskMonitoring]);

  const toggleCollapse = useCallback((name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  const toggleQaItemCollapse = useCallback((id: string) => {
    setCollapsedQaItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    setSearchParams({});
    remoteStartKeyRef.current = "";
    resetProcessingState("converting");
    setTaskId("");
    setRemoteMeta(null);
    setRemoteFileName("");

    try {
      const id = await uploadFile(file);
      startTaskMonitoring(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, [resetProcessingState, setSearchParams, startTaskMonitoring]);

  const handleRetryRemote = useCallback(() => {
    if (!remoteDraft) return;
    remoteStartKeyRef.current = "";
    startRemoteWorkflow();
  }, [remoteDraft, startRemoteWorkflow]);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelected(file);
    },
    [handleFileSelected]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelected(file);
    },
    [handleFileSelected]
  );

  const handleExport = useCallback(async () => {
    if (!taskId || phase !== "done") return;
    try {
      await exportMarkdown(taskId);
    } catch {
      setError("Export failed");
    }
  }, [taskId, phase]);

  const handleSaveHistory = useCallback(async () => {
    if (!taskId || phase !== "done" || historySaving) return;
    setHistorySaving(true);
    try {
      const record = await saveMP4History(taskId);
      toast.success(`已保存历史记录：${record.title}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存历史记录失败");
    } finally {
      setHistorySaving(false);
    }
  }, [historySaving, phase, taskId]);

  const handleQASubmit = useCallback(async (prefilledQuestion?: string) => {
    const question = (prefilledQuestion ?? qaInput).trim();
    if (!taskId || !question || qaLoading) return;

    const tempId = `qa-item-${Date.now()}`;
    setQaLoading(true);
    setQaInput("");
    setCollapsed((prev) => ({ ...prev, ask: false }));
    setCollapsedQaItems((prev) => ({ ...prev, [tempId]: false }));
    setQaItems((prev) => [{ id: tempId, question, loading: true }, ...prev]);
    toast.success("Ask AI 已发送");

    try {
      const answer = await askQuestion(taskId, question);
      const resolvedItem: QaItem = {
        id: tempId,
        question,
        answerHtml: renderQaAnswer(answer, question),
      };
      setQaItems((prev) => prev.map((item) => (item.id === tempId ? resolvedItem : item)));
    } catch {
      setQaItems((prev) => prev.filter((item) => item.id !== tempId));
      setError("Q&A request failed");
    } finally {
      setQaLoading(false);
    }
  }, [taskId, qaInput, qaLoading]);

  const handleQAKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleQASubmit();
      }
    },
    [handleQASubmit]
  );

  const handleQAChipClick = useCallback((prompt: string) => {
    void handleQASubmit(prompt);
  }, [handleQASubmit]);

  const handleCopyText = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
  }, []);

  const handleOpenReader = useCallback((text: string, title: string) => {
    setReaderText(text);
    setReaderTitle(title);
    setShowReader(true);
  }, []);

  const handleDocumentClick = useCallback(
    (e: MouseEvent) => {
      const target = e.target as HTMLElement;

      const chip = target.closest(".qa-followup-chip") as HTMLButtonElement | null;
      if (chip) {
        const prompt = chip.dataset.followup;
        if (prompt) handleQAChipClick(prompt);
        return;
      }

      const readBtn = target.closest(".read-full-qa") as HTMLButtonElement | null;
      if (readBtn) {
        const text = readBtn.dataset.text || "";
        const title = readBtn.dataset.title || "Ask AI Answer";
        handleOpenReader(text, title);
        return;
      }

      const copyBtn = target.closest(".copy-full-qa") as HTMLButtonElement | null;
      if (copyBtn) {
        const text = copyBtn.dataset.text || "";
        handleCopyText(text);
      }
    },
    [handleQAChipClick, handleOpenReader, handleCopyText]
  );

  useEffect(() => {
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, [handleDocumentClick]);

  useEffect(() => {
    if (initialTaskId && !esRef.current) {
      const timer = window.setTimeout(() => {
        startTaskMonitoring(initialTaskId);
      }, 0);
      return () => window.clearTimeout(timer);
    }

    if (!initialTaskId && remoteDraft && !taskId && !remoteStarting) {
      const timer = window.setTimeout(() => {
        startRemoteWorkflow();
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [initialTaskId, remoteDraft, remoteStarting, startRemoteWorkflow, startTaskMonitoring, taskId]);

  useEffect(() => {
    if (!taskId || phase === "done" || phase === "error") return;

    const timer = window.setInterval(() => {
      void refreshTaskSnapshot(taskId);
    }, 1000);

    return () => window.clearInterval(timer);
  }, [phase, refreshTaskSnapshot, taskId]);

  useEffect(() => {
    return () => {
      if (esRef.current) {
        esRef.current.close();
      }
      if (transcriptFrameRef.current) {
        cancelAnimationFrame(transcriptFrameRef.current);
      }
    };
  }, []);

  const transcriptHtml = `<pre>${displayedTranscript}</pre>`;
  const polishedHtml = `<pre>${polished}</pre>`;
  const summaryHtml = buildSummaryCards(summary);

  const showResults =
    phase === "done" ||
    phase === "polishing" ||
    phase === "summarizing" ||
    phase === "transcribing";
  const showProcessingPanel = phase === "converting" || phase === "transcribing";
  const activeAlert = (() => {
    if (error) {
      return {
        variant: "destructive" as const,
        icon: <AlertCircle className="size-4" />,
        title: "Workflow needs attention",
        description: error,
      };
    }

    if (phase === "done") {
      return {
        variant: "default" as const,
        icon: <CheckCircle2 className="size-4" />,
        title: "Workflow completed",
        description: "Transcript, polish and summary are ready. You can copy, read or export the result.",
      };
    }

    if (remoteDraft && phase === "converting") {
      return {
        variant: "default" as const,
        icon: <Info className="size-4" />,
        title: "Remote resource is being prepared",
        description: "The page is downloading the parsed video first, then uploading it to MP4 to Word automatically.",
      };
    }

    if (phase === "transcribing") {
      return {
        variant: "default" as const,
        icon: <Info className="size-4" />,
        title: "Transcription is streaming",
        description: "Transcript will render progressively while the backend keeps processing the media.",
      };
    }

    if (phase === "polishing" || phase === "summarizing") {
      return {
        variant: "default" as const,
        icon: <Info className="size-4" />,
        title: phase === "polishing" ? "AI polish is running" : "AI summary is running",
        description: "The transcript has been captured and AI post-processing is now updating the result panels.",
      };
    }

    return null;
  })();

  const processProgress = (() => {
    if (phase === "idle") return 0;
    if (phase === "converting") {
      const downloadPart = remoteDraft ? Math.min(downloadProgress.progress || 0, 100) * 0.22 : 12;
      const ingestPart = Math.min(intakeProgress.progress || 0, 100) * 0.18;
      return Math.round(Math.max(10, Math.min(38, downloadPart + ingestPart + 8)));
    }
    if (phase === "transcribing") return transcript ? 58 : 45;
    if (phase === "polishing") return 74;
    if (phase === "summarizing") return 88;
    if (phase === "done") return 100;
    return 100;
  })();

  const workflowSteps = [
    { label: "Upload", description: "Input source", icon: UploadCloud },
    { label: "Convert", description: "Audio ready", icon: FileAudio },
    { label: "Transcribe", description: "Text stream", icon: Captions },
    { label: "Polish", description: "AI rewrite", icon: Sparkles },
    { label: "Summary", description: "Final notes", icon: ListChecks },
  ];

  return (
    <WorkspaceShell sectionLabel="MP4 to Word" pageTitle="Workspace">
      <div className="container">
        <style>{QA_STYLE_FIX}</style>
        <Card className="mb-5 overflow-hidden border-white/70 bg-gradient-to-br from-white via-slate-50 to-indigo-50/70 shadow-[0_24px_90px_rgba(15,23,42,0.10)]">
          <CardContent className="space-y-6 p-6 sm:p-8">
            <div className="flex flex-wrap items-start justify-between gap-5">
              <div className="max-w-3xl space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">MP4 to Text</Badge>
                  <Badge variant="outline">AI Workspace</Badge>
                </div>
                <div>
                  <h1 className="text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">MP4 to Text</h1>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
                    Upload video, transcribe automatically, polish with AI, and generate a clean summary for trading and investing content.
                  </p>
                </div>
              </div>
              <div className="min-w-[180px] rounded-2xl border border-white/70 bg-white/75 px-4 py-3 text-right shadow-sm">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Overall Process</div>
                <div className="mt-1 text-3xl font-semibold tracking-tight text-slate-950">{processProgress}%</div>
              </div>
            </div>

            <div className="space-y-3">
              <Progress value={processProgress} className="h-2" />
              <div className="rounded-3xl border border-slate-200 bg-white/70 p-4 shadow-sm">
                <div className="flex items-center gap-0 overflow-x-auto pb-1">
                  {workflowSteps.map((step, index) => {
                    const Icon = step.icon;
                    const active = index === currentStep;
                    const completed = index < currentStep || phase === "done";
                    const pending = !active && !completed;
                    return (
                      <div key={step.label} className="flex min-w-[150px] flex-1 items-center">
                        <div
                          className={`relative flex min-w-[126px] items-center gap-3 rounded-2xl border px-3 py-3 transition ${
                            active
                              ? "border-slate-900 bg-slate-950 text-white shadow-lg shadow-slate-950/10"
                              : completed
                                ? "border-slate-200 bg-white text-slate-900"
                                : "border-slate-100 bg-slate-50/80 text-slate-400"
                          }`}
                        >
                          <div
                            className={`flex size-9 shrink-0 items-center justify-center rounded-xl border ${
                              active
                                ? "border-white/20 bg-white/10"
                                : completed
                                  ? "border-slate-200 bg-slate-50"
                                  : "border-slate-200 bg-white"
                            }`}
                          >
                            {completed ? <CheckCircle2 className="size-4" /> : <Icon className="size-4" />}
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{step.label}</div>
                            <div className={`mt-0.5 truncate text-[11px] ${active ? "text-white/65" : pending ? "text-slate-400" : "text-slate-500"}`}>
                              {step.description}
                            </div>
                          </div>
                        </div>
                        {index < workflowSteps.length - 1 && (
                          <div className="relative h-px min-w-8 flex-1 bg-slate-200">
                            <div className={`absolute inset-y-0 left-0 ${completed ? "w-full bg-slate-950" : "w-0 bg-slate-950"}`} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {activeAlert && (
          <Alert variant={activeAlert.variant} className="mb-5 border-white/70 bg-white/80 shadow-[0_14px_40px_rgba(15,23,42,0.06)] backdrop-blur">
            {activeAlert.icon}
            <AlertTitle>{activeAlert.title}</AlertTitle>
            <AlertDescription>{activeAlert.description}</AlertDescription>
          </Alert>
        )}

        {remoteDraft && (
          <Card className="mb-5 overflow-hidden border-white/70 bg-gradient-to-br from-white via-slate-50 to-sky-50/80 shadow-[0_24px_80px_rgba(15,23,42,0.10)]">
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">Remote Parse Intake</Badge>
                    <Badge variant="outline">{remoteDraft.platform}</Badge>
                    <Badge variant="outline">{remoteDraft.noteType || "video"}</Badge>
                  </div>
                  <CardTitle className="max-w-3xl truncate text-2xl tracking-tight">{remoteDraft.title}</CardTitle>
                  <CardDescription>资源已接管，页面会自动完成下载、上传与 MP4 to Word 处理。</CardDescription>
                </div>
                <div className="rounded-2xl border border-white/70 bg-white/70 px-4 py-3 text-right shadow-sm">
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Task</div>
                  <div className="mt-1 max-w-[180px] truncate font-mono text-xs text-slate-700">{taskId || "creating..."}</div>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-2xl bg-white/70 p-4 shadow-sm">
                  <div className="text-xs text-muted-foreground">Duration</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{formatMediaDuration(remoteDraft.duration)}</div>
                </div>
                <div className="rounded-2xl bg-white/70 p-4 shadow-sm">
                  <div className="text-xs text-muted-foreground">File</div>
                  <div className="mt-1 truncate text-sm font-medium text-slate-950">{remoteFileName || "Resolving..."}</div>
                </div>
                <div className="rounded-2xl bg-white/70 p-4 shadow-sm">
                  <div className="text-xs text-muted-foreground">Mode</div>
                  <div className="mt-1 text-sm font-medium text-slate-950">Browser first, server fallback</div>
                </div>
              </div>
              <Separator />
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-950 px-4 py-3 text-white">
                <div className="min-w-0">
                  <div className="text-xs text-white/55">Source</div>
                  <div className="max-w-[min(760px,70vw)] truncate text-sm font-medium" title={remoteDraft.sourceUrl}>
                    {compactUrl(remoteDraft.sourceUrl)}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="icon-sm" variant="secondary" title="Copy source" aria-label="Copy source" onClick={() => handleCopyText(remoteDraft.sourceUrl)}>
                    <Copy className="size-4" />
                  </Button>
                  <Button size="icon-sm" variant="secondary" title="Open source" aria-label="Open source" onClick={() => window.open(remoteDraft.sourceUrl, "_blank", "noopener,noreferrer")}>
                    <ExternalLink className="size-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        <Card
          className="mb-5 cursor-pointer overflow-hidden border-dashed border-slate-300/80 bg-white/70 shadow-[0_20px_60px_rgba(15,23,42,0.06)] transition hover:-translate-y-0.5 hover:border-sky-300 hover:bg-sky-50/40 hover:shadow-[0_24px_80px_rgba(14,165,233,0.12)]"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <CardContent className="flex flex-col items-center justify-center px-6 py-10 text-center">
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*,audio/*"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
            <div className="mb-4 inline-flex size-14 items-center justify-center rounded-2xl bg-slate-950 text-2xl text-white shadow-lg shadow-slate-950/15">🎧</div>
            <div className="text-lg font-semibold tracking-tight text-slate-950">Drop your file here, or click to browse</div>
            <div className="mt-2 text-sm text-muted-foreground">Supports MP4, MP3, WAV, M4A. Local upload and remote intake are independent flows.</div>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <Badge variant="secondary">Local Upload</Badge>
              <Badge variant="outline">Audio Extract</Badge>
              <Badge variant="outline">AI Polish</Badge>
              <Badge variant="outline">Summary</Badge>
            </div>
          </CardContent>
        </Card>

        {showProcessingPanel && (
          <div className="mb-5 grid gap-5 lg:grid-cols-2">
            {remoteDraft ? (
              <ProgressCard
                title="Download"
                description={remoteStarting ? "正在创建远程任务并准备下载资源。" : "正在拉取 Downloader 已解析出的远程视频资源。"}
                progress={downloadProgress}
                transferred={downloadProgress.downloaded_bytes || 0}
                total={downloadProgress.total_bytes || 0}
                eta={downloadProgress.eta_seconds}
                speed={downloadProgress.speed_bytes_per_sec}
              />
            ) : null}
            <ProgressCard
              title={remoteDraft ? "Upload / Fallback Ingest" : "Processing"}
              description={remoteDraft ? "优先由浏览器下载后上传到 MP4 to Word；如果浏览器受 CORS 限制，会自动回退到后端接管。" : "本地文件已上传，正在转换音频并接入转写流程。"}
              progress={remoteDraft ? intakeProgress : { ...intakeProgress, progress: Math.max(intakeProgress.progress || 0, phase === "transcribing" ? 100 : 15) }}
              transferred={remoteDraft ? intakeProgress.processed_bytes || 0 : intakeProgress.processed_bytes || 0}
              total={remoteDraft ? intakeProgress.total_bytes || 0 : intakeProgress.total_bytes || 0}
              eta={remoteDraft ? intakeProgress.eta_seconds : intakeProgress.eta_seconds}
              speed={0}
            />
          </div>
        )}

        {phase === "error" && remoteDraft && (
          <div className="result-box" style={{ marginBottom: 20 }}>
            <div className="result-header">
              <span className="result-title">Workflow Failed</span>
            </div>
            <div className="result-body" style={{ minHeight: 0 }}>
              <p style={{ marginBottom: 16 }}>远程处理链路发生异常，你可以直接重试当前任务接管流程。</p>
              <button className="action-btn" onClick={handleRetryRemote} disabled={remoteStarting}>
                {remoteStarting ? "Retrying..." : "Retry Remote Flow"}
              </button>
            </div>
          </div>
        )}

        {showResults && (
          <div id="resultsArea" style={{ display: "block" }}>
            <div className="columns">
              <div className="result-box">
                <div className="result-header" onClick={() => toggleCollapse("transcript")}>
                  <span className="result-title">
                    <span className="icon">📝</span>Transcript
                  </span>
                  <div className="result-meta">
                    <Badge variant="secondary">{transcript.length} chars</Badge>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title="Copy transcript"
                      aria-label="Copy transcript"
                      className="rounded-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyText(transcript);
                      }}
                    >
                      <Copy className="size-4" />
                    </Button>
                  </div>
                </div>
                <div className={`result-body-wrap ${collapsed.transcript ? "collapsed" : "open"}`}>
                  <div className="result-body">
                    {displayedTranscript ? <div dangerouslySetInnerHTML={{ __html: transcriptHtml }} /> : <TextSkeletonBlock rows={10} />}
                  </div>
                </div>
              </div>

              <div className="result-box">
                <div className="result-header" onClick={() => toggleCollapse("polished")}>
                  <span className="result-title">
                    <span className="icon">✨</span>AI Polish
                  </span>
                  <div className="result-meta">
                    <Badge variant="secondary">{polished.length} chars</Badge>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title="Read polish"
                      aria-label="Read polish"
                      className="rounded-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenReader(polished, "AI Polish");
                      }}
                    >
                      <BookOpen className="size-4" />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title="Copy polish"
                      aria-label="Copy polish"
                      className="rounded-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyText(polished);
                      }}
                    >
                      <Copy className="size-4" />
                    </Button>
                  </div>
                </div>
                <div className={`result-body-wrap ${collapsed.polished ? "collapsed" : "open"}`}>
                  <div className="result-body">
                    {polished ? <div dangerouslySetInnerHTML={{ __html: polishedHtml }} /> : <TextSkeletonBlock rows={10} />}
                  </div>
                </div>
              </div>
            </div>

            <div className="summary-box" style={{ marginBottom: 20 }}>
              <div className="result-header" onClick={() => toggleCollapse("summary")}>
                <span className="result-title">
                  <span className="icon">🧠</span>AI Summary
                </span>
                <div className="result-meta">
                  <Button
                    size="icon-sm"
                    variant={summaryRawMode ? "default" : "ghost"}
                    title="Toggle raw summary"
                    aria-label="Toggle raw summary"
                    className="rounded-full"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSummaryRawMode((prev) => !prev);
                    }}
                  >
                    <Code2 className="size-4" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    title="Copy summary"
                    aria-label="Copy summary"
                    className="rounded-full"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(summary);
                    }}
                  >
                    <Copy className="size-4" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    title="Export markdown"
                    aria-label="Export markdown"
                    className="rounded-full"
                    disabled={phase !== "done"}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleExport();
                    }}
                  >
                    <Download className="size-4" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    title="Export history"
                    aria-label="Export history"
                    className="rounded-full"
                    disabled={phase !== "done" || historySaving}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleSaveHistory();
                    }}
                  >
                    <FileText className="size-4" />
                  </Button>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.summary ? "collapsed" : "open"}`}>
                {summary ? (
                  <div className={`summary-stage ${summaryRawMode ? "raw-mode" : ""}`}>
                    <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryHtml }} />
                    <div className="summary-raw-view">{summary}</div>
                    <div className="summary-raw">{summary}</div>
                  </div>
                ) : (
                  <div className="result-body">
                    <TextSkeletonBlock rows={8} />
                  </div>
                )}
              </div>
            </div>

            <AskSection
              qaItems={qaItems}
              collapsed={!!collapsed.ask}
              collapsedQaItems={collapsedQaItems}
              onToggleSection={() => toggleCollapse("ask")}
              onToggleItem={toggleQaItemCollapse}
              onFollowupClick={handleQAChipClick}
            />
          </div>
        )}

        <FloatingAskBar
          visible={showResults}
          qaInput={qaInput}
          qaLoading={qaLoading}
          taskId={taskId}
          onChange={setQaInput}
          onKeyDown={handleQAKeyDown as (e: React.KeyboardEvent<HTMLInputElement>) => void}
        />

        <ReaderModal show={showReader} title={readerTitle} text={readerText} onClose={() => setShowReader(false)} />
      </div>
    </WorkspaceShell>
  );
}
