import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { FileText, Search } from "lucide-react";
import { getMP4History, listMP4History } from "@/lib/api";
import type { MP4HistoryListItem, MP4HistoryRecord } from "@/lib/history-types";
import { MP4HistoryDataTable } from "@/components/mp4-history-data-table";
import { WorkspaceShell } from "@/components/workspace-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { buildSummaryCards } from "./lib/summary-renderer";

function formatDate(value?: string) {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

function HistoryContent({ record }: { record: MP4HistoryRecord }) {
  const task = record.task;
  const transcriptHtml = `<pre>${task.transcript || ""}</pre>`;
  const polishedHtml = `<pre>${task.polished || ""}</pre>`;
  const summaryHtml = buildSummaryCards(task.summary || "");

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{record.title}</CardTitle>
              <CardDescription>{formatDate(record.created_at)}</CardDescription>
            </div>
            <Badge>{record.type}</Badge>
          </div>
        </CardHeader>
      </Card>

      <div className="columns">
        <div className="result-box">
          <div className="result-header">
            <span className="result-title">📝 Transcript</span>
          </div>
          <div className="result-body" dangerouslySetInnerHTML={{ __html: transcriptHtml }} />
        </div>
        <div className="result-box">
          <div className="result-header">
            <span className="result-title">✨ AI Polish</span>
          </div>
          <div className="result-body" dangerouslySetInnerHTML={{ __html: polishedHtml }} />
        </div>
      </div>

      <div className="summary-box">
        <div className="result-header">
          <span className="result-title">🧠 AI Summary</span>
        </div>
        <div className="summary-stage">
          <div className="summary-workspace" dangerouslySetInnerHTML={{ __html: summaryHtml }} />
        </div>
      </div>
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
    void load();
  }, [load]);

  return (
    <WorkspaceShell sectionLabel="MP4 to Word" pageTitle="History">
      <div className="container space-y-5">
        <Card className="border-white/70 bg-white/80 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-2xl">
                  <FileText className="size-5" /> MP4 History
                </CardTitle>
                <CardDescription>从 reference JSON 索引中读取已导出的结构化历史记录。</CardDescription>
              </div>
              {id && (
                <Button asChild variant="outline">
                  <Link to="/mp4-to-word/history">Back to list</Link>
                </Button>
              )}
            </div>
          </CardHeader>
        </Card>

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
