import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, ShieldAlert, X } from "lucide-react"

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
  const [visibleError, setVisibleError] = useState(error)
  const [visibleInfo, setVisibleInfo] = useState(info)
  const [visibleWarnings, setVisibleWarnings] = useState(warnings)
  const [visibleErrors, setVisibleErrors] = useState(errors)

  useEffect(() => {
    setVisibleError(error)
  }, [error])

  useEffect(() => {
    setVisibleInfo(info)
  }, [info])

  useEffect(() => {
    setVisibleWarnings(warnings)
  }, [warnings])

  useEffect(() => {
    setVisibleErrors(errors)
  }, [errors])

  useEffect(() => {
    const hasVisible = Boolean(visibleError || visibleInfo || visibleWarnings.length || visibleErrors.length)
    if (!hasVisible) return
    const timer = window.setTimeout(() => {
      setVisibleError(null)
      setVisibleInfo(null)
      setVisibleWarnings([])
      setVisibleErrors([])
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [visibleError, visibleInfo, visibleWarnings, visibleErrors])

  const combinedIssueText = useMemo(() => [...visibleWarnings, ...visibleErrors].join("；"), [visibleWarnings, visibleErrors])

  return (
    <div className="space-y-3">
      {visibleError ? (
        <Alert variant="destructive" className="relative rounded-2xl border-red-200 bg-red-50 pr-10">
          <ShieldAlert className="size-4" />
          <AlertTitle>分析失败</AlertTitle>
          <AlertDescription>{visibleError}</AlertDescription>
          <button
            type="button"
            className="absolute right-2 top-2 rounded-md p-1 text-red-500 transition hover:bg-red-100 hover:text-red-700"
            onClick={() => setVisibleError(null)}
            aria-label="关闭消息"
          >
            <X className="size-4" />
          </button>
        </Alert>
      ) : null}
      {visibleInfo ? (
        <Alert className="relative rounded-2xl border-emerald-200 bg-emerald-50 text-emerald-900 pr-10">
          <CheckCircle2 className="size-4" />
          <AlertTitle>提示</AlertTitle>
          <AlertDescription>{visibleInfo}</AlertDescription>
          <button
            type="button"
            className="absolute right-2 top-2 rounded-md p-1 text-emerald-600 transition hover:bg-emerald-100 hover:text-emerald-800"
            onClick={() => setVisibleInfo(null)}
            aria-label="关闭消息"
          >
            <X className="size-4" />
          </button>
        </Alert>
      ) : null}
      {combinedIssueText ? (
        <Alert className="relative rounded-2xl border-amber-200 bg-amber-50 text-amber-900 pr-10">
          <AlertTriangle className="size-4" />
          <AlertTitle>数据质量 / 错误</AlertTitle>
          <AlertDescription>{combinedIssueText}</AlertDescription>
          <button
            type="button"
            className="absolute right-2 top-2 rounded-md p-1 text-amber-700 transition hover:bg-amber-100 hover:text-amber-900"
            onClick={() => {
              setVisibleWarnings([])
              setVisibleErrors([])
            }}
            aria-label="关闭消息"
          >
            <X className="size-4" />
          </button>
        </Alert>
      ) : null}
    </div>
  )
}
