export const BAND = {
  upExtreme: "#B71C1C",
  upStrong: "#D32F2F",
  upMid: "#F44336",
  upLight: "#EF9A9A",
  flat: "#9E9E9E",
  downLight: "#A5D6A7",
  downMid: "#4CAF50",
  downStrong: "#2E7D32",
  downExtreme: "#1B5E20",
} as const

export function bandColor(pct: number | null | undefined) {
  if (pct == null || !Number.isFinite(pct) || Math.abs(pct) > 50) return BAND.flat
  if (pct >= 10) return BAND.upExtreme
  if (pct >= 5) return BAND.upStrong
  if (pct >= 2) return BAND.upMid
  if (pct >= 0.5) return BAND.upLight
  if (pct <= -10) return BAND.downExtreme
  if (pct <= -5) return BAND.downStrong
  if (pct <= -2) return BAND.downMid
  if (pct <= -0.5) return BAND.downLight
  return BAND.flat
}

export function bandFg(pct: number | null | undefined) {
  if (pct == null) return "#ffffff"
  if (Math.abs(pct) < 0.5) return "#ffffff"
  if (pct >= 0.5 && pct < 2) return "#7f1d1d"
  if (pct <= -0.5 && pct > -2) return "#14532d"
  return "#ffffff"
}

export function fmtPct(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—"
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`
}

export function fmtAmount(value: number | null | undefined) {
  if (value == null) return "—"
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(1)}亿`
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return String(Math.round(value))
}

export function fmtYi(value: number | null | undefined) {
  if (value == null) return "—"
  return `${value >= 0 ? "+" : ""}${(value / 1e8).toFixed(2)}亿`
}

export const cardChrome =
  "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.045)]"

export function prettyDate(date: string) {
  return date.slice(5)
}

export function weekday(date: string) {
  const day = new Date(`${date}T00:00:00Z`).getUTCDay()
  return ["日", "一", "二", "三", "四", "五", "六"][day]
}

export const INSIDE_REFRESH_MS = 10 * 60 * 1000
