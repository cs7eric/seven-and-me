import { Lock } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function NotApplicableCard({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <Card className="rounded-none border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)] sm:rounded-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Lock className="size-4 text-slate-400" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="rounded-none border border-dashed border-slate-300 bg-slate-50/70 p-6 text-sm text-slate-500 sm:rounded-2xl">
          {description}
        </div>
      </CardContent>
    </Card>
  )
}
