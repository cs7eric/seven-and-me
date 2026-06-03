import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function Alerts({
  error,
  info,
  warnings,
  errors,
}: {
  error: string | null
  info: string | null
  warnings: string[]
  errors: string[]
}) {
  return (
    <>
      {error ? (
        <Alert variant="destructive" className="rounded-2xl border-red-200 bg-red-50">
          <ShieldAlert className="size-4" />
          <AlertTitle>分析失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {info ? (
        <Alert className="rounded-2xl border-emerald-200 bg-emerald-50 text-emerald-900">
          <CheckCircle2 className="size-4" />
          <AlertTitle>提示</AlertTitle>
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      ) : null}
      {warnings.length || errors.length ? (
        <Alert className="rounded-2xl border-amber-200 bg-amber-50 text-amber-900">
          <AlertTriangle className="size-4" />
          <AlertTitle>数据质量 / 错误</AlertTitle>
          <AlertDescription>{[...warnings, ...errors].join("；")}</AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}
