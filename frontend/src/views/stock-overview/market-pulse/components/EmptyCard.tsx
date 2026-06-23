import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { cardChrome } from "../lib/format"

export function EmptyCard({ title, description }: { title: string; description: string }) {
  return (
    <Card className={cardChrome}>
      <CardHeader>
        <CardTitle className="text-base text-slate-900">{title}</CardTitle>
        <CardDescription className="text-sm text-slate-500">{description}</CardDescription>
      </CardHeader>
    </Card>
  )
}
