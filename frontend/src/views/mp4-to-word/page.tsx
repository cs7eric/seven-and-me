import { useRef, useState, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import type { Phase, SSEEvent } from "../../lib/types";
import { uploadFile, createSSEConnection, askQuestion, exportMarkdown } from "../../lib/api";
import { STEPS } from "./constants";
import { QA_STYLE_FIX } from "./styles";
import { buildSummaryCards } from "./lib/summary-renderer";
import { renderQaAnswer } from "./lib/qa-renderer";
import { StepBar } from "./components/StepBar";
import { AskSection } from "./components/AskSection";
import { FloatingAskBar } from "./components/FloatingAskBar";
import { ReaderModal } from "./components/ReaderModal";

interface QaItem {
  id: string;
  question: string;
  answerHtml: string;
}

export default function Mp4ToWordPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState("");
  const [polished, setPolished] = useState("");
  const [summary, setSummary] = useState("");
  const [taskId, setTaskId] = useState("");
  const [error, setError] = useState("");
  const [isRawView, setIsRawView] = useState(false);
  const [qaInput, setQaInput] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaItems, setQaItems] = useState<QaItem[]>([]);
  const [showReader, setShowReader] = useState(false);
  const [readerText, setReaderText] = useState("");
  const [readerTitle, setReaderTitle] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [collapsedQaItems, setCollapsedQaItems] = useState<Record<string, boolean>>({});

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

  const toggleCollapse = useCallback((name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  const toggleQaItemCollapse = useCallback((id: string) => {
    setCollapsedQaItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    setPhase("converting");
    setTranscript("");
    setPolished("");
    setSummary("");
    setError("");
    setTaskId("");
    setQaItems([]);
    setIsRawView(false);
    setCollapsed({});
    setCollapsedQaItems({});

    try {
      const id = await uploadFile(file);
      setTaskId(id);

      const es = createSSEConnection(id, {
        onEvent: (event: SSEEvent) => {
          switch (event.type) {
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
              setPhase("done");
              break;
            case "error":
              setError(event.error || "Unknown error");
              setPhase("error");
              break;
          }
        },
        onError: (err) => {
          setError(err);
          setPhase("error");
        },
        onDone: () => {
          setPhase("done");
        },
      });

      esRef.current = es;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, []);

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
        const text = copyBtn.dataset.copy || "";
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
    return () => {
      esRef.current?.close();
    };
  }, []);

  const progressPct =
    phase === "idle"
      ? 0
      : phase === "converting"
        ? 15
        : phase === "transcribing"
          ? 40
          : phase === "polishing"
            ? 65
            : phase === "summarizing"
              ? 85
              : 100;

  const phaseLabel =
    phase === "idle"
      ? "Waiting for upload"
      : phase === "converting"
        ? "Converting media..."
        : phase === "transcribing"
          ? "Transcribing..."
          : phase === "polishing"
            ? "AI polishing..."
            : phase === "summarizing"
              ? "AI summarizing..."
              : phase === "done"
                ? "Done"
                : "Error";

  const summaryCardsHtml = phase !== "idle" && phase !== "error" && summary ? buildSummaryCards(summary) : "";
  const showResults = phase !== "idle" && phase !== "error";
  const showError = phase === "error";

  return (
    <div className="container">
      <style>{QA_STYLE_FIX}</style>
      <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: "12px" }}>
        <Link
          to="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            borderRadius: "999px",
            padding: "10px 14px",
            background: "rgba(255,255,255,0.72)",
            border: "1px solid rgba(15,23,42,0.08)",
            color: "#111827",
            textDecoration: "none",
            fontSize: "13px",
            fontWeight: 600,
            boxShadow: "0 8px 24px rgba(15,23,42,0.06)",
          }}
        >
          <span>←</span>
          <span>Back Home</span>
        </Link>
      </div>
      <h1>MP4 to Text</h1>
      <p className="subtitle">
        Upload video, transcribe automatically, polish with AI, and generate a clean
        summary for trading and investing content.
      </p>

      <StepBar steps={STEPS} currentStep={currentStep} />

      {phase === "idle" && (
        <div
          className="upload-box"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <div className="upload-icon">📁</div>
          <div className="upload-text">Choose a media file or drag it here</div>
          <div className="upload-hint">
            Supports MP4, MOV, AVI, MP3, WAV, M4A and other audio/video formats
          </div>
        </div>
      )}
      <input
        type="file"
        ref={fileInputRef}
        accept="video/*,audio/mpeg,audio/wav,audio/mp3,.mp3"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      {phase !== "idle" && (
        <div
          id="progressInfo"
          style={{
            display: "block",
            marginBottom: "16px",
            fontSize: "13px",
            color: "#71767b",
          }}
        >
          <span className="phase">{phaseLabel}</span>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progressPct}%` }}></div>
          </div>
        </div>
      )}

      {showError && (
        <div
          style={{
            background: "rgba(255,255,255,0.76)",
            border: "1px solid rgba(245,30,30,0.2)",
            borderRadius: "24px",
            padding: "24px",
            marginBottom: "16px",
            color: "#f4212e",
            fontSize: "14px",
          }}
        >
          ❌ Error: {error}
          <br />
          <button
            onClick={() => setPhase("idle")}
            style={{
              marginTop: "12px",
              background: "rgba(0,113,227,0.08)",
              color: "#0071e3",
              border: "1px solid rgba(0,113,227,0.2)",
              borderRadius: "999px",
              padding: "8px 16px",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {showResults && (
        <div id="resultsArea">
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
                    title="Copy transcript"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(transcript);
                    }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
                      <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75" />
                    </svg>
                  </button>
                  <svg className={`result-toggle ${collapsed.transcript ? "" : "open"}`} width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.transcript ? "collapsed" : "open"}`}>
                <div className="result-body">{transcript}</div>
              </div>
            </div>

            <div className="result-box">
              <div className="result-header" onClick={() => toggleCollapse("polish")}>
                <span className="result-title">
                  <span className="icon">✨</span>AI Polish
                </span>
                <div className="result-meta">
                  <span className="char-count">{polished.length} chars</span>
                  <button
                    className="expand-btn"
                    title="Open in reading mode"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleOpenReader(polished, "Reading Mode");
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                      <polyline points="15 3 21 3 21 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <polyline points="9 21 3 21 3 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <line x1="21" y1="3" x2="14" y2="10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                      <line x1="3" y1="21" x2="10" y2="14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Read
                  </button>
                  <button
                    className="copy-btn"
                    title="Copy polished text"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(polished);
                    }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
                      <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75" />
                    </svg>
                  </button>
                  <svg className={`result-toggle ${collapsed.polish ? "" : "open"}`} width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.polish ? "collapsed" : "open"}`}>
                <div className="result-body">{polished}</div>
              </div>
            </div>
          </div>

          <div className="summary-box">
            <div className="result-header" onClick={() => toggleCollapse("summary")}>
              <span className="result-title">
                <span className="icon">🧠</span>AI Summary
              </span>
              <div className="result-meta">
                <button
                  className={`toggle-view-btn ${isRawView ? "active" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsRawView((v) => !v);
                  }}
                >
                  {isRawView ? "Cards" : "Raw"}
                </button>
                <button
                  className="copy-btn summary-master-copy"
                  title="Copy full summary"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopyText(summary);
                  }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
                    <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75" />
                  </svg>
                </button>
                <button
                  className="export-btn"
                  disabled={phase !== "done"}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleExport();
                  }}
                >
                  Export MD
                </button>
                <svg className={`result-toggle ${collapsed.summary ? "" : "open"}`} width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
            <div className={`result-body-wrap ${collapsed.summary ? "collapsed" : "open"}`}>
              <div className={`summary-stage ${isRawView ? "raw-mode" : ""}`}>
                <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryCardsHtml }} />
                <div className="summary-raw-view">{summary}</div>
              </div>
            </div>
          </div>

          <AskSection
            qaItems={qaItems}
            collapsed={Boolean(collapsed.qa)}
            collapsedQaItems={collapsedQaItems}
            onToggleSection={() => toggleCollapse("qa")}
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
  );
}
