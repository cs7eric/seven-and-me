/**
 * 风格板块涨跌幅 热力图 (ECharts Treemap, 单层 29 cell)
 *
 * 数据源: GET /api/stock-chart/style-sectors (StyleSectorItem[])
 * 跟 industry-application/sector-heatmap.tsx 用同一套 SECTOR_PALETTE (4 档红/绿+flat)
 * 面积: valid_size 平方根压缩, 给"样本多的风格"更大视觉权重.
 * 颜色: change_pct 4 档 (red/green 系, ±0.5 / ±2 / ±5)
 *
 * 跟 sector-heatmap.tsx 区别:
 *  - 单层 (29 cell), 没有钻入
 *  - 颜色由 cell 自己 change_pct 决定, 不需要 area/color 解耦
 *  - 没有子节点 (children), 没有 StockDetailDialog 交互
 */
import { useEffect, useRef, useState } from "react"
import * as echarts from "echarts/core"
import { TreemapChart } from "echarts/charts"
import { TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([TreemapChart, TooltipComponent, CanvasRenderer])

import type { StyleSectorItem } from "@/lib/api"

interface Props {
  items: StyleSectorItem[]
  loading?: boolean
  /** 点击 cell 回调. 不传 = 不响应点击 (跟原本的 nodeClick: false 行为一致). */
  onCellClick?: (name: string) => void
}

interface EChartsTreemapNode {
  name: string
  value: number
  _pct: number | null
  _validSize: number
  _sampleSize: number
  itemStyle: { color: string }
  upperLabel: { show: false }
  label: {
    show: true
    color: string
    fontSize: number
    fontWeight: number
    lineHeight: number
    formatter: () => string
    rich: Record<string, unknown>
  }
}

type Band =
  | "upExtreme"
  | "upStrong"
  | "upLight"
  | "flat"
  | "downLight"
  | "downStrong"
  | "downExtreme"

interface Palette {
  upExtreme: { bg: string; fg: string }
  upStrong: { bg: string; fg: string }
  upLight: { bg: string; fg: string }
  flat: { bg: string; fg: string }
  downLight: { bg: string; fg: string }
  downStrong: { bg: string; fg: string }
  downExtreme: { bg: string; fg: string }
}

/** 跟 industry-application/sector-heatmap.tsx SECTOR_PALETTE 同源, 4 档 + flat */
const SECTOR_PALETTE: Palette = {
  upExtreme:   { bg: "#DC2626", fg: "#ffffff" }, // +5%↑
  upStrong:    { bg: "#F87171", fg: "#7F1D1D" }, // +2~5%
  upLight:     { bg: "#FECACA", fg: "#991B1B" }, // +0.5~2%
  // **平盘 cell 浅灰白** (slate-50, 几乎白但可识别):
  // 不能用 #ffffff, 不然 cell 跟纯白底融为一体, 文字跟 "白纸" 上飘.
  // #f8fafc 是 Tailwind 最浅的灰, 跟纯白对比度极低 (≈2.5% delta),
  // 视觉上 "几乎跟白底同色", 但 cell 边界有微弱区分.
  // 文字保持 slate-600 灰 (#475569) — 在 #f8fafc 上能看清.
  flat:        { bg: "#f8fafc", fg: "#475569" }, // ±0.5%
  downLight:   { bg: "#DCFCE7", fg: "#14532D" }, // -0.5~-2%
  downStrong:  { bg: "#86EFAC", fg: "#14532D" }, // -2~-5%
  downExtreme: { bg: "#15803D", fg: "#ffffff" }, // -5%↓
}

function bandForPct(pct: number | null | undefined): Band {
  if (pct == null || !Number.isFinite(pct) || Math.abs(pct) > 50) return "flat"
  if (pct >= 5) return "upExtreme"
  if (pct >= 2) return "upStrong"
  if (pct >= 0.5) return "upLight"
  if (pct <= -5) return "downExtreme"
  if (pct <= -2) return "downStrong"
  if (pct <= -0.5) return "downLight"
  return "flat"
}

function buildTreemapData(items: StyleSectorItem[]): EChartsTreemapNode[] {
  return items.map((it) => {
    const band = bandForPct(it.change_pct)
    const c = SECTOR_PALETTE[band]
    const cpStr = it.change_pct != null
      ? `${it.change_pct >= 0 ? "+" : ""}${it.change_pct.toFixed(2)}%`
      : "—"
    // 面积: 样本数 0.3 次幂 + 最小保底 3.
    //   - pow(0.3) 比 sqrt (pow 0.5) 平得多: valid_size 5 vs 200 的 cell 面积比
    //     sqrt 下 0.16 (6.4x 差), pow(0.3) 下 0.40 (2.5x 差), 视觉上 29 个 cell 面积更均匀
    //   - min=3 兜底, 哪怕只有 2 只股票的极小板块也能看清
    const vSize = Math.max(0, it.valid_size || 0)
    const area = Math.max(Math.pow(vSize, 0.3), 3)
    return {
      name: it.name,
      value: area,
      _pct: it.change_pct ?? null,
      _validSize: it.valid_size,
      _sampleSize: it.sample_size,
      itemStyle: { color: c.bg },
      upperLabel: { show: false },
      label: {
        show: true,
        color: c.fg,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 16,
        // cell 太小自动只显示 name (ECharts labelLayout 兜底)
        formatter: () => `{n|${it.name}}\n{p|${cpStr}}`,
        rich: {
          n: { color: c.fg, fontSize: 12, fontWeight: 700, lineHeight: 16 },
          p: { color: c.fg, fontSize: 11, fontWeight: 600, lineHeight: 14 },
        },
      },
    }
  })
}

export function StyleSectorsHeatmap({ items, loading = false, onCellClick }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)
  const [hover, setHover] = useState<{ name: string; pct: number | null; valid: number; sample: number } | null>(null)

  // init chart once
  // **完全照搬 industry-application/sector-heatmap.tsx 同款 init 模式**:
  // - useEffect (非 useLayoutEffect)
  // - init 不传显式 width/height, 让 ECharts 自己读 clientWidth/clientHeight
  // - ResizeObserver 接管 resize, debounce 80ms 避免 hover 期间频繁触发打断 tooltip
  // - setOption 内不调 chart.resize() (避免双 resize 互相覆盖导致 treemap 居中算法错位)
  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
    instanceRef.current = chart

    // **首帧 rAF resize 兜底**: 即使父级 h-[420px] 已稳定, ECharts init 时
    // 偶尔会拿到 reflow 前一刻的尺寸, 等下一帧 paint 完再 resize 一次, 把
    // treemap 切到最终 canvas 大小.
    const rafId = requestAnimationFrame(() => {
      try {
        chart.resize()
      } catch {}
    })

    let resizeTimer: number | null = null
    const ro = new ResizeObserver(() => {
      if (resizeTimer != null) window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => chart.resize(), 80)
    })
    ro.observe(chartRef.current)

    const handleResize = () => chart.resize()
    window.addEventListener("resize", handleResize)

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener("resize", handleResize)
      ro.disconnect()
      if (resizeTimer != null) window.clearTimeout(resizeTimer)
      chart.dispose()
      instanceRef.current = null
    }
  }, [])

  // re-render on data change
  useEffect(() => {
    const chart = instanceRef.current
    if (!chart) return
    if (items.length === 0) {
      chart.clear()
      return
    }

    // 绑定点击 (cell -> 弹 drawer). 仅在 onCellClick 存在时挂, 避免无意义监听.
    const clickHandler = (params: any) => {
      if (!onCellClick) return
      // treemap 点击 event: params.data 是 cell data; 兼容: params.name 兜底
      const d = params?.data as EChartsTreemapNode | undefined
      const name = d?.name || (params?.name as string | undefined)
      if (name) onCellClick(name)
    }
    if (onCellClick) {
      chart.on("click", clickHandler)
    }

    const data = buildTreemapData(items)
    // **完全照搬 industry-application/sector-heatmap.tsx 同款 setOption 结构**:
    // - 不传 series.width / series.height (默认 100% 行为一致, 但不传更稳)
    // - 不传 series.levels (单层 treemap, 用 cell-level itemStyle/label)
    // - 加 nodeGap/nodePadding (cell 之间细缝, 跟 working 一致)
    // - 加 animationDuration* 0 (关掉默认 1000ms 动画, 避免 hover 期间 chart 重绘打断 tooltip)
    // - **不调 chart.resize()** (ResizeObserver 已经接管, 这里再调会双 resize 互相覆盖
    //   导致 treemap 居中算法在两次调用之间算出不同尺寸, 最终 treemap 偏右下)
    chart.setOption({
      backgroundColor: "#ffffff",
      animation: false,
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(15, 23, 42, 0.92)",
        borderColor: "transparent",
        textStyle: { color: "#f8fafc", fontSize: 12 },
        transitionDuration: 0,
        formatter: (info: any) => {
          const d = info?.data as EChartsTreemapNode | undefined
          if (!d) return ""
          const pctStr =
            d._pct == null
              ? "—"
              : `${d._pct >= 0 ? "+" : ""}${d._pct.toFixed(2)}%`
          return [
            `<div style="font-weight:600;margin-bottom:2px">${d.name}</div>`,
            `<div>涨跌幅: <b>${pctStr}</b></div>`,
            `<div>样本: <b>${d._validSize} / ${d._sampleSize}</b> 只</div>`,
          ].join("")
        },
      },
      series: [
        {
          type: "treemap",
          // **left/top/right/bottom: 0** 显式把 treemap 的布局边距钉死在画布边缘.
          // 不写 ECharts 自己会留 5-10px 边距, 单层 treemap 看着四周有 "细缝",
          // 加上本来就 min-h-0 flex-1 撑满父容器, 整体看着像是 "偏右下".
          left: 0,
          top: 0,
          right: 0,
          bottom: 0,
          roam: false,
          // 之前用 ``onCellClick ? "zoomToNode" : false``: zoomToNode 是给
          // 有 children 的层级 treemap 用的, 单层 29 cell 走 zoomToNode
          // 反而行为怪. 点击事件我自己用 ``chart.on("click", clickHandler)``
          // 处理, 这里直接关掉避免 ECharts 内部冲突.
          nodeClick: false,
          breadcrumb: { show: false },
          animationDuration: 0,
          animationDurationUpdate: 0,
          animationEasing: "linear",
          // cell 之间细缝 (跟 working 保持 2px) + cell 内部 padding 0
          // (cell 自带 borderWidth 1 已经够看, 不要 padding 把 cell label 往下推)
          nodeGap: 2,
          nodePadding: 0,
          upperLabel: { show: false },
          labelLayout: { hideOverlap: true },
          // **series-level itemStyle 边框全白色**:
          // 之前是 slate-200 (#e2e8f0), 跟 chart 背景白 (card 是 bg-white, setOption
          // backgroundColor #ffffff) 形成 "灰线", 看着像有灰底. 改纯白后:
          // - cell border #ffffff 跟 chart 背景同色 → 不可见
          // - nodeGap: 2 仍然画 2px 白色间隔 (nodeGap 用 chart 背景色填充)
          // - 净效果: cell 之间有 2px 白缝, 没有任何灰色边框, 看着"白净"
          itemStyle: {
            borderColor: "#ffffff",
            borderWidth: 1,
            gapWidth: 0,
          },
          emphasis: {
            // hover 时边框也白色, 宽度 2 (轻微 highlight, 不强)
            itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
          },
          // **不传 width/height, 不传 levels** — 单层 treemap, cell 自己带 itemStyle/label
          data,
        },
      ],
    })

    return () => {
      // 卸载: 解绑 click 监听, 避免热替换 / 重渲导致重复挂载
      if (onCellClick) {
        chart.off("click", clickHandler)
      }
    }
  }, [items, onCellClick])

  return (
    // **flex h-full min-h-0 flex-col + flex-1 min-h-0** 是关键:
    // - 外层 ``flex h-full min-h-0 flex-col`` 让组件整体 "吃满" 父级 (父级必须是 h-[420px] 那种明确高度)
    // - 中间图表区 ``min-h-0 flex-1`` 占满剩余空间 (min-h-0 是 flex 子项允许 shrink 到 0 的开关, 不加会按内容撑大)
    // - legend / hover 都 ``shrink-0`` 保证不被图表区挤掉
    <div className="flex h-full min-h-0 flex-col gap-2">
      {/* 彻底纯白: 去掉 border border-slate-200, 只留 bg-white.
          之前有 slate-200 border + 内部 slate-200 cell border, 双层灰线让背景看着像灰底.
          改纯 bg-white + cell 白色 border (chart 背景也是白) → 视觉上只有 nodeGap 2px 留白,
          整体白净, 没有任何灰色干扰. */}
      <div className="min-h-0 flex-1 overflow-hidden bg-white">
        <div
          ref={chartRef}
          className="h-full w-full bg-white"
        />
      </div>

      <div className="shrink-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.upExtreme.bg }} />
          涨 ≥5%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.upStrong.bg }} />
          +2% ~ +5%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.upLight.bg }} />
          +0.5% ~ +2%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.flat.bg }} />
          ±0.5%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.downLight.bg }} />
          -0.5% ~ -2%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.downStrong.bg }} />
          -2% ~ -5%
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SECTOR_PALETTE.downExtreme.bg }} />
          跌 ≥5%
        </span>
        {loading ? <span className="ml-2 text-slate-400">加载中…</span> : null}
      </div>

      {hover ? (
        <div className="shrink-0 rounded-lg bg-slate-50 px-3 py-1.5 text-[11px] text-slate-600">
          选中: <b>{hover.name}</b> {hover.pct != null ? `${hover.pct >= 0 ? "+" : ""}${hover.pct.toFixed(2)}%` : "—"}{" "}
          样本 {hover.valid} / {hover.sample}
        </div>
      ) : null}
    </div>
  )
}
