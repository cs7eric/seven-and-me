interface CynexusResult<T> {
  code?: string
  message?: string
  data?: T
  success?: boolean
  failed?: boolean
}

function parseJsonPreservingLongIds<T>(text: string): T | null {
  if (!text.trim()) return null
  const normalized = text.replace(/"([A-Za-z][A-Za-z0-9_]*)":(-?\d{16,})/g, '"$1":"$2"')
  return JSON.parse(normalized) as T
}

export async function cynexusResult<T>(res: Response): Promise<T> {
  const text = await res.text()
  const data = parseJsonPreservingLongIds<CynexusResult<T>>(text)
  if (!res.ok || !data || data.success === false || data.failed === true) {
    throw new Error(data?.message || `request failed: ${res.status}`)
  }
  return data.data as T
}

