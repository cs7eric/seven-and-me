import type { StockOverlayAnnotation } from "../../stock-chart/lib/types"

export function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? "").trim()).filter(Boolean)
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

export function asOverlayAnnotations(value: unknown): StockOverlayAnnotation[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is StockOverlayAnnotation =>
    Boolean(item && typeof item === "object" && Array.isArray((item as StockOverlayAnnotation).points)),
  )
}

export function safeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

export function safeString(value: unknown): string {
  return typeof value === "string" && value.trim().length > 0 ? value : ""
}

export function fmt(value: unknown) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

export function fmtDateTime(timestamp: number) {
  if (!Number.isFinite(timestamp)) return "—"
  return new Date(timestamp).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

export function fmtPercent(value: number, digits = 2) {
  if (!Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : value < 0 ? "" : ""
  return `${sign}${value.toFixed(digits)}%`
}

export function fmtSigned(value: number, digits = 2) {
  if (!Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : value < 0 ? "" : ""
  return `${sign}${value.toFixed(digits)}`
}

export function fmtInt(value: number) {
  if (!Number.isFinite(value)) return "—"
  return Math.round(value).toLocaleString("en-US")
}

// 中文紧凑计数：优先显示「x亿」，再「x千万」/「x百万」/「x万」/原值
export function fmtCompactNumber(value: number, digits = 2) {
  if (!Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : value > 0 ? "+" : ""
  if (abs >= 1e8) {
    const v = abs / 1e8
    return `${sign}${v.toFixed(digits)}亿`
  }
  if (abs >= 1e7) {
    const v = abs / 1e7
    return `${sign}${v.toFixed(digits)}千万`
  }
  if (abs >= 1e6) {
    const v = abs / 1e6
    return `${sign}${v.toFixed(digits)}百万`
  }
  if (abs >= 1e4) {
    const v = abs / 1e4
    return `${sign}${v.toFixed(digits)}万`
  }
  return `${sign}${fmtInt(abs)}`
}

// 同时给出原值与紧凑单位：例如 105,521,815 · 1.06亿
export function fmtNumberWithCompact(value: number, digits = 2) {
  if (!Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : value > 0 ? "+" : ""
  if (abs >= 1e4) {
    return `${sign}${fmtInt(abs)} · ${fmtCompactNumber(value, digits).replace(/^[+-]/, "")}`
  }
  return fmtCompactNumber(value, digits)
}

export function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}
