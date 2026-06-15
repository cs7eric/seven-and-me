interface FloatingAskBarProps {
  visible: boolean;
  qaInput: string;
  qaLoading: boolean;
  taskId: string;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
}

/**
 * 浮动 Ask Bar · 任务可见时的底部输入条
 *
 * 来源: 抽到 src/components/ 公共目录, 跨 Mp4ToWordPage / Mp4HistoryPage 复用.
 *       "visible || taskId" 缺一就不渲染.
 */
export function FloatingAskBar({
  visible,
  qaInput,
  qaLoading,
  taskId,
  onChange,
  onKeyDown,
}: FloatingAskBarProps) {
  if (!visible || !taskId) return null;

  return (
    <div className="qa-floating-wrap">
      <div className="qa-floating-shell">
        <div className="qa-floating-inner">
          <div className="qa-search-box">
            <input
              placeholder={qaLoading ? "Thinking..." : "Ask about the transcript, summary, or logic..."}
              className="qa-search-input"
              name="search"
              type="search"
              value={qaInput}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <svg
              className="qa-search-icon"
              stroke="currentColor"
              strokeWidth="1.5"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
                strokeLinejoin="round"
                strokeLinecap="round"
              ></path>
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
