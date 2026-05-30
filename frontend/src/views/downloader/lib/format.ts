export function formatDuration(seconds?: number) {
  if (!seconds || Number.isNaN(seconds)) return "-"
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60

  if (h > 0) {
    return [h, m, s].map((value, index) => (index === 0 ? String(value) : String(value).padStart(2, "0"))).join(":")
  }

  return [m, s].map((value) => String(value).padStart(2, "0")).join(":")
}

export function summarizeUrl(value: string) {
  try {
    const parsed = new URL(value)
    const name = parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname
    return `${parsed.hostname} / ${name}`
  } catch {
    return value
  }
}
