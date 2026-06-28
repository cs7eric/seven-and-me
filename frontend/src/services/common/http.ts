const RETRY_MAX_RETRIES = 3
const RETRY_BASE_DELAY_MS = 400

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isRetryableStatus(status: number): boolean {
  return status >= 500 || status === 408 || status === 429
}

export async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: RequestInit,
  options: { retry?: boolean; maxRetries?: number; baseDelayMs?: number } = {},
): Promise<Response> {
  const { retry = true, maxRetries = RETRY_MAX_RETRIES, baseDelayMs = RETRY_BASE_DELAY_MS } = options
  const maxAttempts = retry ? maxRetries + 1 : 1
  let lastError: unknown = null

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(input, init)
      if (!isRetryableStatus(res.status) || attempt === maxAttempts) {
        return res
      }
    } catch (err) {
      lastError = err
      if (attempt === maxAttempts) throw err
    }
    await sleep(baseDelayMs * Math.pow(2, attempt - 1))
  }

  throw lastError instanceof Error ? lastError : new Error("fetch failed")
}

