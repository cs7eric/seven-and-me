interface StepBarProps {
  steps: readonly string[];
  currentStep: number;
}

export function StepBar({ steps, currentStep }: StepBarProps) {
  return (
    <div className="step-bar">
      {steps.map((label, i) => (
        <div
          key={label}
          className={`step ${i < currentStep ? "done" : i === currentStep ? "active" : ""}`}
        >
          {label}
        </div>
      ))}
    </div>
  );
}
