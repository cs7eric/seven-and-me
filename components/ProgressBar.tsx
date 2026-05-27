interface ProgressBarProps {
  phase: string;
  progress: number;
}

export default function ProgressBar({ phase, progress }: ProgressBarProps) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontSize: '13px', color: '#71767b' }}>{phase}</span>
        <span style={{ fontSize: '13px', color: '#71767b' }}>{progress}%</span>
      </div>
      <div style={{
        height: '4px',
        background: '#2f3336',
        borderRadius: '2px',
        overflow: 'hidden',
      }}>
        <div style={{
          height: '100%',
          width: `${progress}%`,
          background: '#1d9bf0',
          borderRadius: '2px',
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  );
}