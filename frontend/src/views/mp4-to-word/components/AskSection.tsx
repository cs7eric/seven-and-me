interface QaItem {
  id: string;
  question: string;
  answerHtml?: string;
  loading?: boolean;
}

interface AskSectionProps {
  qaItems: QaItem[];
  collapsed: boolean;
  collapsedQaItems: Record<string, boolean>;
  onToggleSection: () => void;
  onToggleItem: (id: string) => void;
  onFollowupClick?: (question: string) => void;
}

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
                        {item.question}
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
                          <div className="space-y-3 p-1">
                            <div className="h-4 w-1/2 animate-pulse rounded bg-slate-200" />
                            <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
                            <div className="h-4 w-4/5 animate-pulse rounded bg-slate-200" />
                            <div className="h-4 w-3/5 animate-pulse rounded bg-slate-200" />
                          </div>
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
