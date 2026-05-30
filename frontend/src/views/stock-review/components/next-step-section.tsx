import { Link } from "react-router-dom"
import { ArrowRight, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"

export function NextStepSection() {
  return (
    <div className="rounded-3xl border border-border/30 bg-background p-6 shadow-sm shadow-black/5">
      <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
        <Sparkles className="size-3.5" />
        Next Step
      </div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
          这个 mock 页面已经准备好承接后续真实模块，风格上会和 Home / Sidebar 保持一致。
        </p>
        <Button asChild className="rounded-xl">
          <Link to="/">
            返回应用总览
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </div>
    </div>
  )
}
