import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, Search } from "lucide-react";
import { askHistoryQuestion, getMP4History, listMP4History } from "@/lib/api";
import type { MP4HistoryListItem, MP4HistoryRecord } from "@/lib/history-types";
import { MP4HistoryDataTable } from "@/components/mp4-history-data-table";
import { WorkspaceShell } from "@/components/workspace-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { buildSummaryCards } from "./lib/summary-renderer";
import { renderQaAnswer } from "./lib/qa-renderer";
import { AskSection } from "./components/AskSection";
import { FloatingAskBar } from "./components/FloatingAskBar";
import { QA_STYLE_FIX } from "./styles";

function formatDate(value?: string) {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

function DetailPanel({ html, text }: { html: string; text: string }) {
  return (
    <div className="overflow-hidden rounded-3xl border border-white/70 bg-white/85 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
      <div className="result-body">{text ? <div dangerouslySetInnerHTML={{ __html: html }} /> : <div className="text-muted-foreground">暂无内容</div>}</div>
    </div>
  );
}

function AskHistoryPanel({
  qaItems,
  collapsed,
  collapsedQaItems,
  onToggleSection,
  onToggleItem,
  onFollowupClick,
}: {
  qaItems: Array<{ id: string; question: string; answerHtml?: string; loading?: boolean }>;
  collapsed: boolean;
  collapsedQaItems: Record<string, boolean>;
  onToggleSection: () => void;
  onToggleItem: (id: string) => void;
  onFollowupClick: (question: string) => void;
}) {
  return (
    <AskSection
      qaItems={qaItems}
      collapsed={collapsed}
      collapsedQaItems={collapsedQaItems}
      onToggleSection={onToggleSection}
      onToggleItem={onToggleItem}
      onFollowupClick={onFollowupClick}
    />
  );
}

function HistoryContent({ record }: { record: MP4HistoryRecord }) {
  const task = record.task;
  const transcriptHtml = `<pre>${task.transcript || ""}</pre>`;
  const polishedHtml = `<pre>${task.polished || ""}</pre>`;
  const summaryHtml = buildSummaryCards(task.summary || "");
  const metadata = task.metadata || {};
  const [qaItems, setQaItems] = useState<Array<{ id: string; question: string; answerHtml?: string; loading?: boolean }>>(() =>
    (task.qa_items || []).map((item) => ({
      id: item.id,
      question: item.question,
      answerHtml: renderQaAnswer(item.answer, item.question),
    }))
  );
  const [activeView, setActiveView] = useState<"transcript" | "polished" | "summary" | "ask">("summary");
  const [collapsedAsk, setCollapsedAsk] = useState(false);
  const [collapsedQaItems, setCollapsedQaItems] = useState<Record<string, boolean>>({});
  const [askInput, setAskInput] = useState("");
  const [askLoading, setAskLoading] = useState(false);

  const handleToggleQaItem = useCallback((id: string) => {
    setCollapsedQaItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleAsk = useCallback(async (prefilledQuestion?: string) => {
    const question = (prefilledQuestion ?? askInput).trim();
    if (!question || askLoading) return;

    const tempId = `temp-${Date.now()}`;
    setActiveView("ask");
    setCollapsedAsk(false);
    setCollapsedQaItems((prev) => ({ ...prev, [tempId]: false }));
    setQaItems((prev) => [{ id: tempId, question, loading: true }, ...prev]);
    setAskLoading(true);
    setAskInput("");
    toast.success("Ask AI 已发送");

    try {
      const item = await askHistoryQuestion(record.id, question);
      setQaItems((prev) => prev.map((qa) => qa.id === tempId ? {
        id: item.id,
        question: item.question,
        answerHtml: renderQaAnswer(item.answer, item.question),
      } : qa));
    } catch (e) {
      setQaItems((prev) => prev.filter((qa) => qa.id !== tempId));
      throw e;
    } finally {
      setAskLoading(false);
    }
  }, [askInput, askLoading, record.id]);

  const handleFollowupAsk = useCallback((question: string) => {
    setActiveView("ask");
    setCollapsedAsk(false);
    void handleAsk(question).catch(() => undefined);
  }, [handleAsk]);

  const detailContent = useMemo(() => {
    if (activeView === "transcript") return <DetailPanel html={transcriptHtml} text={task.transcript || ""} />;
    if (activeView === "polished") return <DetailPanel html={polishedHtml} text={task.polished || ""} />;
    if (activeView === "ask") {
      return (
        <div className="space-y-4">
          <AskHistoryPanel
            qaItems={qaItems}
            collapsed={collapsedAsk}
            collapsedQaItems={collapsedQaItems}
            onToggleSection={() => setCollapsedAsk((prev) => !prev)}
            onToggleItem={handleToggleQaItem}
            onFollowupClick={handleFollowupAsk}
          />
        </div>
      );
    }
    return (
      <div className="overflow-hidden rounded-3xl border border-white/70 bg-white/85 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="summary-stage">
          <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryHtml }} />
        </div>
      </div>
    );
  }, [activeView, collapsedAsk, collapsedQaItems, handleToggleQaItem, polishedHtml, qaItems, summaryHtml, task.polished, task.transcript, transcriptHtml]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm">
          <Link to="/mp4-to-word/history" className="inline-flex items-center gap-2">
            <ArrowLeft className="size-4" />
            Back to list
          </Link>
        </Button>
      </div>

      <Card className="overflow-hidden border-white/70 bg-gradient-to-br from-white via-slate-50 to-slate-100/80 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <CardContent className="space-y-5 p-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{record.type}</Badge>
              <Badge variant="outline">{task.status || "done"}</Badge>
            </div>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-950">{record.title}</h1>
              <p className="mt-2 text-sm text-muted-foreground">{formatDate(record.created_at)}</p>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">Task ID</div>
              <div className="mt-1 truncate font-mono text-sm text-slate-900">{task.task_id}</div>
            </div>
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">File</div>
              <div className="mt-1 truncate text-sm text-slate-900">{task.file_name || "--"}</div>
            </div>
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">Platform</div>
              <div className="mt-1 truncate text-sm text-slate-900">{String(metadata.platform || "--")}</div>
            </div>
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">Duration</div>
              <div className="mt-1 truncate text-sm text-slate-900">{metadata.duration ? `${metadata.duration}s` : "--"}</div>
            </div>
          </div>
          <div className="grid gap-3 xl:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">Source</div>
              <div className="mt-1 break-all text-sm text-slate-900">{String(metadata.source_url || metadata.download_url || "--")}</div>
            </div>
            <div className="rounded-2xl bg-white/80 p-4 shadow-sm">
              <div className="text-xs text-muted-foreground">Tags</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(metadata.tags as string[] | undefined)?.length ? (metadata.tags as string[]).map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>) : <span className="text-sm text-muted-foreground">--</span>}
              </div>
              <div className="mt-4 text-xs text-muted-foreground">Categories</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(metadata.categories as string[] | undefined)?.length ? (metadata.categories as string[]).map((category) => <Badge key={category} variant="secondary">{category}</Badge>) : <span className="text-sm text-muted-foreground">--</span>}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/70 bg-white/75 p-2 shadow-sm">
          {[
            { key: "summary", label: "Summary" },
            { key: "polished", label: "Polished" },
            { key: "transcript", label: "Transcript" },
            { key: "ask", label: "Ask AI" },
          ].map((item) => (
            <Button
              key={item.key}
              variant={activeView === item.key ? "default" : "ghost"}
              className="rounded-xl"
              onClick={() => setActiveView(item.key as "summary" | "polished" | "transcript" | "ask")}
            >
              {item.label}
            </Button>
          ))}
        </div>
        {detailContent}
      </div>

      <FloatingAskBar
        visible={true}
        qaInput={askInput}
        qaLoading={askLoading}
        taskId={record.id}
        onChange={setAskInput}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void handleAsk().catch(() => undefined);
          }
        }}
      />
    </div>
  );
}

export default function Mp4HistoryPage() {
  const { id } = useParams();
  const [items, setItems] = useState<MP4HistoryListItem[]>([]);
  const [record, setRecord] = useState<MP4HistoryRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (id) {
        setRecord(await getMP4History(id));
      } else {
        setItems(await listMP4History());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载历史记录失败");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <WorkspaceShell sectionLabel="MP4 to Word" pageTitle="History">
      <div className="container space-y-5">
        <style>{QA_STYLE_FIX}</style>
        {id ? null : (
          <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-2xl">
                    <FileText className="size-5" /> MP4 History
                  </CardTitle>
                  <CardDescription>从 reference JSON 索引中读取已导出的结构化历史记录。</CardDescription>
                </div>
              </div>
            </CardHeader>
          </Card>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTitle>Load failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {loading ? (
          <Card>
            <CardContent className="space-y-3 p-6">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </CardContent>
          </Card>
        ) : id && record ? (
          <HistoryContent record={record} />
        ) : items.length ? (
          <MP4HistoryDataTable data={items} />
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center text-muted-foreground">
              <Search className="size-8" />
              <div>暂无历史记录，请在 MP4 解析完成后点击导出历史记录。</div>
            </CardContent>
          </Card>
        )}
      </div>
    </WorkspaceShell>
  );
}
