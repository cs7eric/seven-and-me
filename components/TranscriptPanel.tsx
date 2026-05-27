interface TranscriptPanelProps {
  text: string;
  fileName?: string;
}

export default function TranscriptPanel({ text, fileName }: TranscriptPanelProps) {
  return (
    <div style={{
      background: '#16181c',
      border: '1px solid #2f3336',
      borderRadius: '16px',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid #2f3336',
      }}>
        <div style={{ fontSize: '14px', fontWeight: '600', color: '#e7e9ea' }}>
          📝 原始转写
        </div>
        {fileName && (
          <div style={{ fontSize: '12px', color: '#71767b' }}>{fileName}</div>
        )}
      </div>
      <div style={{
        padding: '14px',
        minHeight: '300px',
        maxHeight: '500px',
        overflowY: 'auto',
        fontSize: '15px',
        lineHeight: '1.8',
        whiteSpace: 'pre-wrap',
        color: '#e7e9ea',
      }}>
        {text || <span style={{ color: '#71767b' }}>转写中...</span>}
      </div>
    </div>
  );
}