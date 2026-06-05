export function OverviewCard({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-border/30 bg-muted/35 p-5">
      <div className="mb-2 text-sm font-medium text-foreground">{title}</div>
      <p className="text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  )
}
