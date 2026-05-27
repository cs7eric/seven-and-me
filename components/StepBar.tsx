export interface Step {
  label: string;
  status: 'done' | 'active' | 'pending';
}

interface StepBarProps {
  currentStep: number;
  labels: string[];
}

export default function StepBar({ currentStep, labels }: StepBarProps) {
  return (
    <div style={{
      display: 'flex',
      background: '#1c2732',
      borderRadius: '12px',
      padding: '4px',
      gap: '2px',
    }}>
      {labels.map((label, i) => {
        const status = i < currentStep ? 'done' : i === currentStep ? 'active' : 'pending';
        return (
          <div key={i} style={{
            flex: 1,
            padding: '10px 8px',
            borderRadius: '8px',
            textAlign: 'center',
            fontSize: '13px',
            fontWeight: 500,
            background: status === 'active' ? '#1d9bf0' : 'transparent',
            color: status === 'done' ? '#1d9bf0' : status === 'active' ? '#fff' : '#71767b',
            transition: 'all 0.2s ease',
          }}>
            <span style={{ marginRight: '6px' }}>
              {status === 'done' ? '✓' : status === 'active' ? '●' : '○'}
            </span>
            {label}
          </div>
        );
      })}
    </div>
  );
}