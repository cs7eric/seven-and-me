/**
 * Design entry:
 * - Data/API: mp4-history list/detail/ask-history
 * - Front design: design/front/mp4-to-word.md
 * - Backend design: design/backend/mp4-history-reference-flow.md
 * - Change rule: review design before edits; sync design if history storage, detail fields, or ask flow changes.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, Search } from "lucide-react";
import { askHistoryQuestion, deleteMP4History, getMP4History, listMP4History } from "@/lib/api";
import type { MP4HistoryListItem, MP4HistoryRecord } from "@/lib/history-types";
import { MP4HistoryDataTable } from "@/components/mp4-history-data-table";
import { WorkspaceShell } from "@/layout/workspace-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { notification } from "@/components/ui/notification";
import DogLoader from "@/components/loader/dog-loader";
import { buildSummaryCards } from "./lib/summary-renderer";
import { renderQaAnswer } from "./lib/qa-renderer";
import { AskSection } from "@/components/ask-section";
import { FloatingAskBar } from "@/components/floating-ask-bar";
import { QA_STYLE_FIX } from "./styles";

function formatDate(value?: string) {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

function DetailPanel({ html, text }: { html: string; text: string }) {
  return (
    <div className="max-w-full overflow-hidden rounded-3xl border border-white/70 bg-white/85 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
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

function MobileHistoryList({
  items,
  onDelete,
}: {
  items: MP4HistoryListItem[];
  onDelete: (item: MP4HistoryListItem) => void;
}) {
  const [query, setQuery] = useState("");

  const filteredItems = useMemo(() => {
    const nextQuery = query.trim().toLowerCase();
    if (!nextQuery) return items;
    return items.filter((item) => {
      return [item.title, item.file_name || "", item.task_id, item.status, item.data_file]
        .join(" ")
        .toLowerCase()
        .includes(nextQuery);
    });
  }, [items, query]);

  return (
    <div className="space-y-3 pb-3 sm:hidden">
      <div className="relative">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search history"
          className="h-11 w-full rounded-2xl border border-slate-200 bg-white pl-10 pr-4 text-[16px] text-slate-900 shadow-sm outline-none transition placeholder:text-muted-foreground focus:border-sky-400"
        />
      </div>

      <div className="space-y-3">
        {filteredItems.length ? filteredItems.map((item) => (
          <Card key={item.id} className="overflow-hidden border-white/70 bg-white/80 shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{item.status || "unknown"}</Badge>
                    <Badge variant="outline">{formatDate(item.created_at)}</Badge>
                  </div>
                  <Link
                    to={`/mp4-to-word/history/${item.id}`}
                    className="block break-words text-base font-semibold leading-6 tracking-tight text-slate-950"
                  >
                    {item.title}
                  </Link>
                </div>
              </div>

              <div className="space-y-2 rounded-2xl bg-slate-50/80 p-3 text-sm text-slate-700">
                <div className="space-y-0.5">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">File</div>
                  <div className="break-words text-sm text-slate-900">{item.file_name || "--"}</div>
                </div>
                <div className="space-y-0.5">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Task</div>
                  <div className="truncate font-mono text-xs text-slate-900">{item.task_id}</div>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <Button asChild className="h-11 w-full rounded-xl">
                  <Link to={`/mp4-to-word/history/${item.id}`}>View detail</Link>
                </Button>
                <Button
                  variant="outline"
                  className="h-11 w-full rounded-xl border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                  onClick={() => onDelete(item)}
                >
                  Delete
                </Button>
              </div>
            </CardContent>
          </Card>
        )) : (
          <Card className="border-dashed border-slate-200 bg-white/75">
            <CardContent className="flex flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
              <Search className="size-8" />
              <div>{query ? "No matching history records." : "暂无历史记录，请在 MP4 解析完成后点击导出历史记录。"}</div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
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
    notification.info({ title: "Ask AI 已发送", description: question });

    try {
      const item = await askHistoryQuestion(record.id, question);
      setQaItems((prev) => prev.map((qa) => qa.id === tempId ? {
        id: item.id,
        question: item.question,
        answerHtml: renderQaAnswer(item.answer, item.question),
      } : qa));
    } catch (e) {
      setQaItems((prev) => prev.filter((qa) => qa.id !== tempId));
      const msg = e instanceof Error ? e.message : "Ask AI 失败"
      notification.danger({ title: "Ask AI 失败", description: msg });
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
      <div className="max-w-full overflow-hidden rounded-3xl border border-white/70 bg-white/85 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="summary-stage">
          <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryHtml }} />
        </div>
      </div>
    );
  }, [activeView, collapsedAsk, collapsedQaItems, handleFollowupAsk, handleToggleQaItem, polishedHtml, qaItems, summaryHtml, task.polished, task.transcript, transcriptHtml]);

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
        <CardContent className="space-y-5 p-4 sm:p-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{record.type}</Badge>
              <Badge variant="outline">{task.status || "done"}</Badge>
            </div>
            <div>
              <h1 className="break-words text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">{record.title}</h1>
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
        <div className="grid grid-cols-2 gap-2 rounded-2xl border border-white/70 bg-white/75 p-2 shadow-sm sm:flex sm:flex-wrap sm:items-center">
          {[
            { key: "summary", label: "Summary" },
            { key: "polished", label: "Polished" },
            { key: "transcript", label: "Transcript" },
            { key: "ask", label: "Ask AI" },
          ].map((item) => (
            <Button
              key={item.key}
              variant={activeView === item.key ? "default" : "ghost"}
              className="w-full rounded-xl sm:w-auto"
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
      const msg = e instanceof Error ? e.message : "加载历史记录失败";
      setError(msg);
      notification.danger({ title: "加载历史记录失败", description: msg });
    } finally {
      setLoading(false);
    }
  }, [id]);

  const handleDelete = useCallback(async (item: MP4HistoryListItem) => {
    try {
      const deleted = await deleteMP4History(item.id);
      setItems((prev) => prev.filter((entry) => entry.id !== item.id));
      notification.success({
        title: "已删除历史记录",
        description: deleted.title || item.title,
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : "删除历史记录失败";
      notification.danger({ title: "删除历史记录失败", description: msg });
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <WorkspaceShell sectionLabel="MP4 to Word" pageTitle="History">
      <div className="container max-w-full space-y-5 px-3 sm:px-6">
        <style>{QA_STYLE_FIX}</style>
        {id ? null : (
          <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-xl sm:text-2xl">
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
          <DogLoader overlay size={25} label="正在加载历史记录..." />
        ) : id && record ? (
          <HistoryContent record={record} />
        ) : (
          <>
            <MobileHistoryList items={items} onDelete={handleDelete} />
            <div className="hidden sm:block">
              <MP4HistoryDataTable data={items} />
            </div>
          </>
        )}
      </div>
    </WorkspaceShell>
  );
}
