interface QaItem {
  id: string;
  question: string;
  answerHtml: string;
}

interface AskSectionProps {
  qaItems: QaItem[];
  collapsed: boolean;
  collapsedQaItems: Record<string, boolean>;
  onToggleSection: () => void;
  onToggleItem: (id: string) => void;
}

export function AskSection({
  qaItems,
  collapsed,
  collapsedQaItems,
  onToggleSection,
  onToggleItem,
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
                        <div
                          className="qa-answer"
                          dangerouslySetInnerHTML={{ __html: item.answerHtml }}
                        />
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
