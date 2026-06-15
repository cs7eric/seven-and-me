interface QaItem {
  id: string;
  question: string;
  answerHtml?: string;
  loading?: boolean;
}

function AskAnswerSkeleton() {
  return (
    <div className="space-y-3 p-1">
      <div className="flex items-center gap-2">
        <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-16 animate-pulse rounded bg-slate-100" />
      </div>
      <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
      <div className="h-4 w-11/12 animate-pulse rounded bg-slate-200" />
      <div className="h-4 w-4/5 animate-pulse rounded bg-slate-200" />
      <div className="h-4 w-3/5 animate-pulse rounded bg-slate-100" />
    </div>
  );
}

interface AskSectionProps {
  qaItems: QaItem[];
  collapsed: boolean;
  collapsedQaItems: Record<string, boolean>;
  onToggleSection: () => void;
  onToggleItem: (id: string) => void;
  onFollowupClick?: (question: string) => void;
}

/**
 * Ask AI 问答折叠列表
 *
 * 来源: 之前仅在 mp4-to-word 内部用, 已经被 Mp4ToWordPage / Mp4HistoryPage
 *        跨文件复用. 抽到 src/components/ 公共目录后, 其他 page
 *        (例如未来个股复盘 / 行业分析的 Ask AI) 也能直接使用.
 *
 * 行为:
 *   - 整段可折叠 (collapsed prop)
 *   - 每条问答可单独折叠 (collapsedQaItems[qaId] 控制)
 *   - 通过事件代理捕获 `.qa-followup-chip` 的 `data-followup`,
 *     调用 onFollowupClick 实现"追问" (不强制用 onClick, 兼容 history DOM 结构)
 */
export function AskSection({
  qaItems,
  collapsed,
  collapsedQaItems,
  onToggleSection,
  onToggleItem,
  onFollowupClick,
}: AskSectionProps) {
  return (
    <div className="qa-section">
      <div className="result-box qa-box">
        <div className="result-header" onClick={onToggleSection}>
          <span className="result-title">
            <span className="icon">💬</span>Ask AI
          </span>
          <div className="result-meta">
            <span className="char-count">{qaItems.length} answers</span>
            <svg
              className={`result-toggle ${collapsed ? "" : "open"}`}
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
            >
              <polyline
                points="6 9 12 15 18 9"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>
        <div className={`result-body-wrap ${collapsed ? "collapsed" : "open"}`}>
          <div className="qa-body">
            <div className="qa-list">
              {qaItems.map((item) => {
                const isCollapsed = collapsedQaItems[item.id] ?? false;
                return (
                  <div key={item.id} className="qa-item">
                    <div className="qa-item-header" onClick={() => onToggleItem(item.id)}>
                      <div className={`qa-item-q-text ${isCollapsed ? "" : "expanded"}`}>
                        <div className="flex items-center gap-2">
                          <span>{item.question}</span>
                          {item.loading ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">Loading</span> : null}
                        </div>
                      </div>
                      <svg
                        className={`qa-item-toggle ${isCollapsed ? "" : "open"}`}
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                      >
                        <polyline
                          points="6 9 12 15 18 9"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                    <div className={`qa-item-body ${isCollapsed ? "" : "open"}`}>
                      <div className="qa-answer-body">
                        {item.loading ? (
                          <AskAnswerSkeleton />
                        ) : (
                          <div
                            className="qa-answer"
                            onClick={(event) => {
                              const target = event.target as HTMLElement | null;
                              const button = target?.closest(".qa-followup-chip") as HTMLElement | null;
                              const followup = button?.getAttribute("data-followup")?.trim();
                              if (followup) {
                                event.preventDefault();
                                event.stopPropagation();
                                onFollowupClick?.(followup);
                              }
                            }}
                            dangerouslySetInnerHTML={{ __html: item.answerHtml || "" }}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {!qaItems.length && (
                <div className="qa-empty">
                  Ask a question about the transcript or summary to get a structured answer.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="qa-floating-anchor" />
    </div>
  );
}
