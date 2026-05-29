interface ReaderModalProps {
  show: boolean;
  title: string;
  text: string;
  onClose: () => void;
}

export function ReaderModal({ show, title, text, onClose }: ReaderModalProps) {
  if (!show) return null;

  return (
    <div className="reader-overlay" onClick={onClose}>
      <div className="reader-modal" onClick={(e) => e.stopPropagation()}>
        <div className="reader-header">
          <div className="reader-title">{title}</div>
          <button className="reader-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="reader-content">{text}</div>
      </div>
    </div>
  );
}
