export function SummaryList({ title, items, tone }: { title: string; items: string[]; tone: "success" | "danger" | "neutral" }) {
  const toneClass = tone === "success" ? "border-l-emerald-500" : tone === "danger" ? "border-l-red-500" : "border-l-slate-500"
  return (
    <div className={`rounded-2xl border border-slate-200 border-l-4 bg-white p-4 ${toneClass}`}>
      <div className="mb-3 text-sm font-semibold text-slate-800">{title}</div>
      <div className="space-y-2">
        {items.length ? items.map((item) => (
          <div key={item} className="rounded-xl bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">{item}</div>
        )) : <div className="text-sm text-slate-400">暂无内容</div>}
      </div>
    </div>
  )
}
