const API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) || ""
const CYNEXUS_API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_CYNEXUS_API_BASE) || ""

export const SERVICE_PREFIX = {
  legacy: API_BASE,
  cynexus: CYNEXUS_API_BASE,
  ai: `${CYNEXUS_API_BASE}/api/ai`,
  aiConfig: `${CYNEXUS_API_BASE}/api/ai/config`,
  market: `${CYNEXUS_API_BASE}/api/market`,
  marketData: `${CYNEXUS_API_BASE}/api/market/data`,
  core: `${CYNEXUS_API_BASE}/api/core`,
} as const

