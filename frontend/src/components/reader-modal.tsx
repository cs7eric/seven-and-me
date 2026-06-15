interface ReaderModalProps {
  show: boolean;
  title: string;
  text: string;
  onClose: () => void;
}

/**
 * 阅读模式弹窗 · 黑底 + 文字 + 关闭按钮
 *
 * 来源: 抽到 src/components/ 公共目录, 主要给 mp4-to-word 复用,
 *       其他长文阅读场景也能直接用.
 */
export function ReaderModal({ show, title, text, onClose }: ReaderModalProps) {
  if (!show) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-title">{title}</div>
          <button className="modal-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-content">{text}</div>
      </div>
    </div>
  );
}
