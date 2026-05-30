import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Phase, PostMetadata, SSEEvent, TransferProgress } from "../../lib/types";
import { askQuestion, createSSEConnection, exportMarkdown, fetchTaskSnapshot, sendDownloaderResultToParse, uploadFile } from "../../lib/api";
import { STEPS } from "./constants";
import { QA_STYLE_FIX } from "./styles";
import { buildSummaryCards } from "./lib/summary-renderer";
import { renderQaAnswer } from "./lib/qa-renderer";
import { StepBar } from "./components/StepBar";
import { AskSection } from "./components/AskSection";
import { FloatingAskBar } from "./components/FloatingAskBar";
import { ReaderModal } from "./components/ReaderModal";
import { WorkspaceShell } from "@/components/workspace-shell";

interface QaItem {
  id: string;
  question: string;
  answerHtml: string;
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

  return (
    <div className="result-box" style={{ minWidth: 0 }}>
      <div className="result-header">
        <span className="result-title">{title}</span>
        <div className="result-meta">
          <span className="char-count">{percent}%</span>
        </div>
      </div>
      <div className="result-body" style={{ minHeight: 0 }}>
        <p style={{ marginBottom: 14 }}>{description}</p>
        <div className="progress-bar" style={{ marginBottom: 14 }}>
          <div className="progress-fill" style={{ width: `${percent}%` }} />
        </div>
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <div>
            <div className="char-count">Transferred</div>
            <div>{formatBytes(transferred)}</div>
          </div>
          <div>
            <div className="char-count">Total</div>
            <div>{formatBytes(total)}</div>
          </div>
          <div>
            <div className="char-count">ETA</div>
            <div>{formatDurationSeconds(eta)}</div>
          </div>
          <div>
            <div className="char-count">Speed</div>
            <div>{speed ? `${formatBytes(speed)}/s` : "--"}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Mp4ToWordPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);
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

  const applyTaskSnapshot = useCallback((snapshot: Awaited<ReturnType<typeof fetchTaskSnapshot>>) => {
    const status = snapshot.status as Phase;
    setTranscript(snapshot.transcript || "");
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
  }, []);

  const refreshTaskSnapshot = useCallback(async (id: string) => {
    try {
      const snapshot = await fetchTaskSnapshot(id);
      applyTaskSnapshot(snapshot);
    } catch {
      return;
    }
  }, [applyTaskSnapshot]);

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
            setTranscript(event.text || "");
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
  }, [remoteMeta, refreshTaskSnapshot, setSearchParams]);

  const startRemoteWorkflow = useCallback(async () => {
    if (!remoteDraft || remoteStarting) return;
    setRemoteStarting(true);
    resetProcessingState("converting");
    setRemoteMeta({
      title: remoteDraft.title,
      categories: [remoteDraft.platform],
      tags: [remoteDraft.noteType || "video"],
    });

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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    } finally {
      setRemoteStarting(false);
    }
  }, [remoteDraft, remoteStarting, resetProcessingState, startTaskMonitoring]);

  const toggleCollapse = useCallback((name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  const toggleQaItemCollapse = useCallback((id: string) => {
    setCollapsedQaItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    setSearchParams({});
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

  const handleQASubmit = useCallback(async () => {
    if (!taskId || !qaInput.trim() || qaLoading) return;
    setQaLoading(true);
    try {
      const answer = await askQuestion(taskId, qaInput.trim());
      const id = `qa-item-${Date.now()}`;
      const newItem: QaItem = {
        id,
        question: qaInput.trim(),
        answerHtml: renderQaAnswer(answer, qaInput.trim()),
      };
      setQaItems((prev) => [newItem, ...prev]);
      setCollapsedQaItems((prev) => ({ ...prev, [id]: false }));
      setQaInput("");
    } catch {
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
    setQaInput(prompt);
  }, []);

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
      startTaskMonitoring(initialTaskId);
      return;
    }

    if (!initialTaskId && remoteDraft && !taskId && !remoteStarting) {
      startRemoteWorkflow();
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
    };
  }, []);

  const transcriptHtml = `<pre>${transcript}</pre>`;
  const polishedHtml = `<pre>${polished}</pre>`;
  const summaryHtml = buildSummaryCards(summary);

  const showResults =
    phase === "done" ||
    phase === "polishing" ||
    phase === "summarizing" ||
    phase === "transcribing";
  const showProcessingPanel = phase === "converting" || phase === "transcribing";

  return (
    <WorkspaceShell sectionLabel="MP4 to Word" pageTitle="Workspace">
      <div className="container">
        <style>{QA_STYLE_FIX}</style>
        <h1>MP4 to Text</h1>
        <p className="subtitle">
          Upload video, transcribe automatically, polish with AI, and generate a clean
          summary for trading and investing content.
        </p>

        <StepBar steps={STEPS} currentStep={currentStep} />

        {error && <div className="error">{error}</div>}

        {remoteDraft && (
          <div className="result-box" style={{ marginBottom: 20 }}>
            <div className="result-header">
              <span className="result-title">Remote Parse Intake</span>
              <div className="result-meta">
                <span className="char-count">{taskId || "creating task..."}</span>
              </div>
            </div>
            <div className="result-body" style={{ minHeight: 0 }}>
              <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <div>
                  <div className="char-count">Title</div>
                  <div>{remoteDraft.title}</div>
                </div>
                <div>
                  <div className="char-count">Platform</div>
                  <div>{remoteDraft.platform}</div>
                </div>
                <div>
                  <div className="char-count">Type</div>
                  <div>{remoteDraft.noteType}</div>
                </div>
                <div>
                  <div className="char-count">Duration</div>
                  <div>{formatMediaDuration(remoteDraft.duration)}</div>
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <div className="char-count">Source</div>
                  <div style={{ wordBreak: "break-all" }}>{remoteDraft.sourceUrl}</div>
                </div>
                {remoteFileName && (
                  <div>
                    <div className="char-count">Resolved File</div>
                    <div>{remoteFileName}</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <div
          className="upload-box"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*,audio/*"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <div className="upload-icon">🎧</div>
          <div className="upload-text">Drop your file here, or click to browse</div>
          <div className="upload-hint">Supports MP4, MP3, WAV, M4A</div>
        </div>

        {showProcessingPanel && (
          <div style={{ display: "grid", gap: 20, gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", marginBottom: 20 }}>
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
              title={remoteDraft ? "Ingest" : "Processing"}
              description={remoteDraft ? "下载完成后会自动进入 MP4 to Word 处理模块，无需二次点击。" : "本地文件已上传，正在转换音频并接入转写流程。"}
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
                    <span className="char-count">{transcript.length} chars</span>
                    <button
                      className="copy-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyText(transcript);
                      }}
                    >
                      Copy
                    </button>
                  </div>
                </div>
                <div className={`result-body-wrap ${collapsed.transcript ? "collapsed" : "open"}`}>
                  <div className="result-body" dangerouslySetInnerHTML={{ __html: transcriptHtml }} />
                </div>
              </div>

              <div className="result-box">
                <div className="result-header" onClick={() => toggleCollapse("polished")}>
                  <span className="result-title">
                    <span className="icon">✨</span>AI Polish
                  </span>
                  <div className="result-meta">
                    <span className="char-count">{polished.length} chars</span>
                    <button
                      className="expand-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenReader(polished, "AI Polish");
                      }}
                    >
                      Read
                    </button>
                    <button
                      className="copy-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyText(polished);
                      }}
                    >
                      Copy
                    </button>
                  </div>
                </div>
                <div className={`result-body-wrap ${collapsed.polished ? "collapsed" : "open"}`}>
                  <div className="result-body" dangerouslySetInnerHTML={{ __html: polishedHtml }} />
                </div>
              </div>
            </div>

            <div className="summary-box" style={{ marginBottom: 20 }}>
              <div className="result-header" onClick={() => toggleCollapse("summary")}>
                <span className="result-title">
                  <span className="icon">🧠</span>AI Summary
                </span>
                <div className="result-meta">
                  <button
                    className={`toggle-view-btn ${summaryRawMode ? "active" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSummaryRawMode((prev) => !prev);
                    }}
                  >
                    Raw
                  </button>
                  <button
                    className="copy-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(summary);
                    }}
                  >
                    Copy
                  </button>
                  <button
                    className="export-btn"
                    disabled={phase !== "done"}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleExport();
                    }}
                  >
                    Export MD
                  </button>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.summary ? "collapsed" : "open"}`}>
                <div className={`summary-stage ${summaryRawMode ? "raw-mode" : ""}`}>
                  <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryHtml }} />
                  <div className="summary-raw-view">{summary}</div>
                  <div className="summary-raw">{summary}</div>
                </div>
              </div>
            </div>

            <AskSection
              qaItems={qaItems}
              collapsed={!!collapsed.ask}
              collapsedQaItems={collapsedQaItems}
              onToggleSection={() => toggleCollapse("ask")}
              onToggleItem={toggleQaItemCollapse}
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
