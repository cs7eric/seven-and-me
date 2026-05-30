interface ReaderModalProps {
  show: boolean;
  title: string;
  text: string;
  onClose: () => void;
}

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
