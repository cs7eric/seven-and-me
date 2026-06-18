/**
 * 颜色工具 + sentiment 温度计色阶 (0-100 蓝→白→红).
 * 主入口: scoreToRgb / scoreToColor.
 */

/** "#rrggbb" + alpha → "rgba(r,g,b,a)" 字符串 */
export function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim())
  if (!m) return `rgba(148, 163, 184, ${alpha})`
  return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alpha})`
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

// ── 蓝→白→红 色阶: sentiment 0~100 ──
const TEMPERATURE_COLOR_STOPS: [number, number, number, number][] = [
  // [score, r, g, b]
  [0,     0,  40, 230], // 深蓝 (去紫调)
  [10,    0,  70, 242], //
  [20,   15, 100, 250], //
  [30,   45, 128, 253], //
  [40,   85, 158, 255], // 浅蓝
  [50,  245, 245, 245], // #F5F5F5 中性白
  [60,  255, 153, 153], // #FF9999 浅红
  [70,  255, 102, 102], // #FF6666
  [80,  255,   0,   0], // #FF0000 红
  [85,  229,   0,   0], // #E50000
  [90,  203,   0,   0], // #CB0000
  [95,  178,   0,   0], // #B20000
  [100, 152,   0,   0], // #980000 深红
]

/** 根据 sentiment 分数 (0-100) 返回 RGB 颜色, 在色阶之间线性插值 */
export function scoreToRgb(score: number): [number, number, number] {
  const s = clamp(score, 0, 100)
  const stops = TEMPERATURE_COLOR_STOPS

  // 精确命中
  for (let i = 0; i < stops.length; i++) {
    if (s === stops[i][0]) return [stops[i][1], stops[i][2], stops[i][3]]
  }

  // 左侧外推
  if (s < stops[0][0]) return [stops[0][1], stops[0][2], stops[0][3]]

  // 区间插值
  for (let i = 0; i < stops.length - 1; i++) {
    const [v0, r0, g0, b0] = stops[i]
    const [v1, r1, g1, b1] = stops[i + 1]
    if (s >= v0 && s <= v1) {
      const t = (s - v0) / (v1 - v0)
      return [
        Math.round(r0 + (r1 - r0) * t),
        Math.round(g0 + (g1 - g0) * t),
        Math.round(b0 + (b1 - b0) * t),
      ]
    }
  }

  // 右侧外推
  const last = stops[stops.length - 1]
  return [last[1], last[2], last[3]]
}

export function scoreToColor(score: number): string {
  const [r, g, b] = scoreToRgb(score)
  return `rgb(${r},${g},${b})`
}