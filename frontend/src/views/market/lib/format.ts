/**
 * Market Pulse 页面用到的格式化 / 配色工具
 *
 * 仅 MarketPulsePage 及其子组件使用; 抽取是为了让 market-pulse.tsx
 * 主页面只关心页面 state / 数据流, 工具细节下沉到 lib.
 */

/** 成交额 / 主力净流入 格式化 (后端已返回 亿, 前端只 toFixed).
 *  sign: 流入 + / 流出 - / null —
 */
export function formatYi(v: number | null | undefined): string {
  if (v == null) return "—"
  if (!Number.isFinite(v)) return "—"
  const sign = v > 0 ? "+" : ""
  return `${sign}${v.toFixed(2)}亿`
}

/** 成交量: 万手 */
export function formatWanShou(v: number | null | undefined): string {
  if (v == null) return "—"
  return `${v.toFixed(0)}万手`
}

export function formatCount(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toLocaleString("zh-CN")
}

/**
 * moneyTone: 返回 A 股风格的颜色集合.
 * 流入 (value > 0): 红 / 浅红底
 * 流出 (value < 0): 绿 / 浅绿底
 * 零值: 灰 / 浅灰底
 */
export function moneyTone(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v) || v === 0) {
    return {
      text: "text-slate-500",
      bg: "bg-slate-50",
      border: "border-slate-100",
      soft: "bg-slate-100 text-slate-500",
      bar: "bg-slate-300",
    }
  }
  if (v > 0) {
    return {
      text: "text-red-600",
      bg: "bg-red-50/70",
      border: "border-red-100",
      soft: "bg-red-100 text-red-700",
      bar: "bg-red-500",
    }
  }
  return {
    text: "text-emerald-600",
    bg: "bg-emerald-50/70",
    border: "border-emerald-100",
    soft: "bg-emerald-100 text-emerald-700",
    bar: "bg-emerald-500",
  }
}

export function diffBadgeTone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) {
    return "border-slate-200 bg-slate-100 text-slate-500"
  }
  if (v > 0) {
    return "border-red-200 bg-red-100 text-red-700"
  }
  return "border-emerald-200 bg-emerald-100 text-emerald-700"
}

/**
 * 把数字格式化成 "1.5亿" / "2300万" / "5百万" / "1.2万亿" / "8000" 之类可读字符串.
 *
 * 用途: 喂 IndustryConstituentsDrawer 的 流通市值 / 流通股 / 成交额 字段
 * (drawer 的 formatAmount 只是 String(value), 不做格式化, 我们前端预 format).
 *
 * 单位梯度 (从大到小):
 *   万亿 (1e12) > 亿 (1e8) > 千万 (1e7) > 百万 (1e6) > 万 (1e4) > 原始
 */
export function formatReadable(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—"
  const abs = Math.abs(v)
  const fmt = (scaled: number) => {
    // 2 位小数, 去掉尾随 0
    const s = scaled.toFixed(2).replace(/\.?0+$/, "")
    return s
  }
  if (abs >= 1e12) return `${fmt(v / 1e12)}万亿`
  if (abs >= 1e8) return `${fmt(v / 1e8)}亿`
  if (abs >= 1e7) return `${fmt(v / 1e7)}千万`
  if (abs >= 1e6) return `${fmt(v / 1e6)}百万`
  if (abs >= 1e4) return `${fmt(v / 1e4)}万`
  return v.toFixed(0)
}
