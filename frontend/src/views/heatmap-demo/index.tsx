import { useEffect, useRef, useState } from "react"
import * as echarts from "echarts/core"
import { TreemapChart, SunburstChart } from "echarts/charts"
import { TitleComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([TreemapChart, SunburstChart, TitleComponent, TooltipComponent, CanvasRenderer])

// 与 echarts 官方 example `echarts-package-size.json` 一致的样例数据
// (简化版: 包名 + 体积, 来自 echarts 官网示例)
// 完整版: https://echarts.apache.org/examples/data/asset/data/echarts-package-size.json
const SAMPLE_DATA = {
  name: "flare",
  children: [
    {
      name: "analytics",
      children: [
        { name: "cluster", value: 1358 },
        { name: "graph", value: 4231 },
        { name: "optimization", value: 6999 },
      ],
    },
    {
      name: "animate",
      children: [
        { name: "Easing", value: 17010 },
        { name: "FunctionSequence", value: 5842 },
        { name: "interpolate", value: 19874 },
      ],
    },
    {
      name: "data",
      children: [
        { name: "converters", value: 12000 },
        { name: "DataUtil", value: 8000 },
        { name: "DataSet", value: 9000 },
      ],
    },
    {
      name: "display",
      children: [
        { name: "DirtySprite", value: 1000 },
        { name: "LineSprite", value: 2000 },
        { name: "RectSprite", value: 3000 },
        { name: "TextSprite", value: 4000 },
      ],
    },
    {
      name: "flex",
      children: [{ name: "FlareVis", value: 4116 }],
    },
    {
      name: "physics",
      children: [
        { name: "DragForce", value: 1082 },
        { name: "GravityForce", value: 1336 },
        { name: "IForce", value: 319 },
        { name: "NBodyForce", value: 16498 },
        { name: "Particle", value: 8018 },
        { name: "Simulation", value: 9983 },
        { name: "Spring", value: 2213 },
        { name: "SpringForce", value: 1681 },
      ],
    },
    {
      name: "query",
      children: [
        { name: "All", value: 1 },
        { name: "Methods", value: 6161 },
        { name: "Parameter", value: 5609 },
        { name: "Selector", value: 9513 },
        { name: "Visibility", value: 2000 },
      ],
    },
    {
      name: "scale",
      children: [
        { name: "IScaleMap", value: 2105 },
        { name: "LinearScale", value: 1316 },
        { name: "LogScale", value: 3151 },
        { name: "OrdinalScale", value: 3770 },
        { name: "QuantileScale", value: 2435 },
        { name: "QuantitativeScale", value: 4839 },
        { name: "RootScale", value: 1756 },
        { name: "Scale", value: 4268 },
        { name: "ScaleType", value: 1821 },
        { name: "TimeScale", value: 5833 },
      ],
    },
    {
      name: "util",
      children: [
        { name: "Arrays", value: 8258 },
        { name: "Colors", value: 10001 },
        { name: "Dates", value: 8217 },
        { name: "Displays", value: 12555 },
        { name: "Filter", value: 2324 },
        { name: "Geometry", value: 17293 },
        { name: "heap", value: 9194 },
        { name: "IEvaluable", value: 335 },
        { name: "IPredicate", value: 383 },
        { name: "IValueProxy", value: 874 },
        { name: "math", value: 11782 },
        { name: "Matrixs", value: 17309 },
        { name: "Numbers", value: 8742 },
        { name: "Objects", value: 14229 },
        { name: "Orient", value: 1496 },
        { name: "palette", value: 1879 },
        { name: "Property", value: 5559 },
        { name: "Shapes", value: 19118 },
        { name: "Sort", value: 6888 },
        { name: "Stats", value: 6557 },
        { name: "Strings", value: 22026 },
        { name: "SVGUtil", value: 7125 },
        { name: "Time", value: 11779 },
        { name: "Trees", value: 9937 },
        { name: "Vectors", value: 6316 },
        { name: "Zip", value: 1516 },
      ],
    },
    {
      name: "vis",
      children: [
        {
          name: "axis",
          children: [
            { name: "Axes", value: 1302 },
            { name: "Axis", value: 24593 },
            { name: "AxisGridLine", value: 652 },
            { name: "AxisLabel", value: 636 },
            { name: "CartesianAxes", value: 6703 },
          ],
        },
        {
          name: "controls",
          children: [
            { name: "AnchorControl", value: 2138 },
            { name: "ClickControl", value: 3824 },
            { name: "Control", value: 1353 },
            { name: "ControlList", value: 4665 },
            { name: "DragControl", value: 2649 },
            { name: "ExpandControl", value: 2832 },
            { name: "HoverControl", value: 4896 },
            { name: "IControl", value: 763 },
            { name: "PanZoomControl", value: 5222 },
            { name: "SelectionControl", value: 7862 },
            { name: "TooltipControl", value: 8435 },
          ],
        },
        {
          name: "data",
          children: [
            { name: "Data", value: 20544 },
            { name: "DataList", value: 19788 },
            { name: "DataSprite", value: 10349 },
            { name: "EdgeSprite", value: 3301 },
            { name: "NodeSprite", value: 19382 },
            { name: "render", children: [
              { name: "ArrowType", value: 698 },
              { name: "EdgeRenderer", value: 5569 },
              { name: "IRenderer", value: 353 },
              { name: "ShapeRenderer", value: 2247 },
            ] },
            { name: "ScaleBinding", value: 11275 },
            { name: "Tree", value: 7147 },
            { name: "TreeBuilder", value: 9930 },
          ],
        },
        {
          name: "event",
          children: [
            { name: "DragEvent", value: 2312 },
            { name: "Event", value: 7745 },
            { name: "MouseEvent", value: 3835 },
          ],
        },
        {
          name: "legend",
          children: [
            { name: "Legend", value: 20859 },
            { name: "LegendItem", value: 4614 },
            { name: "LegendRange", value: 10530 },
          ],
        },
        {
          name: "operator",
          children: [
            { name: "distortion", children: [
              { name: "BifocalDistortion", value: 4461 },
              { name: "Distortion", value: 6314 },
              { name: "FisheyeDistortion", value: 3444 },
            ] },
            { name: "Encoder", value: 7210 },
            { name: "Filter", value: 2183 },
            { name: "IOperator", value: 128 },
            { name: "label", children: [
              { name: "Labeler", value: 9956 },
              { name: "RadialLabeler", value: 3899 },
              { name: "StackedAreaLabeler", value: 3202 },
            ] },
            { name: "layout", children: [
              { name: "AxisLayout", value: 6725 },
              { name: "BundledEdgeRouter", value: 3727 },
              { name: "CircleLayout", value: 9317 },
              { name: "CirclePackingLayout", value: 12003 },
              { name: "DendrogramLayout", value: 4853 },
              { name: "ForceDirectedLayout", value: 8411 },
              { name: "IcicleTreeLayout", value: 4864 },
              { name: "IndentedTreeLayout", value: 4854 },
              { name: "Layout", value: 7886 },
              { name: "NodeLinkTreeLayout", value: 12870 },
              { name: "PieLayout", value: 2728 },
              { name: "RadialTreeLayout", value: 12348 },
              { name: "RandomLayout", value: 870 },
              { name: "StackedAreaLayout", value: 9121 },
              { name: "TreeMapLayout", value: 9191 },
            ] },
            { name: "Operator", value: 2490 },
            { name: "OperatorList", value: 5248 },
            { name: "OperatorSequence", value: 4190 },
            { name: "OperatorSwitch", value: 2581 },
            { name: "SortOperator", value: 2023 },
          ],
        },
        { name: "Visualization", value: 16540 },
      ],
    },
  ],
}

export function HeatmapDemoPage() {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })
    chart.setOption({
      title: { text: "Treemap 最小 demo (照搬 ECharts 官方 example)", left: 16, top: 8 },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "treemap",
          id: "echarts-package-size",
          animationDurationUpdate: 1000,
          roam: false,
          nodeClick: undefined,
          data: SAMPLE_DATA.children,
          universalTransition: true,
          label: { show: true },
          breadcrumb: { show: false },
        },
      ],
    })
    // 切到 sunburst 复现 example 中的 setInterval 效果
    const treemapOption = chart.getOption()
    const sunburstOption = {
      series: [
        {
          type: "sunburst" as const,
          id: "echarts-package-size",
          radius: ["20%", "90%"] as [string, string],
          animationDurationUpdate: 1000,
          nodeClick: undefined,
          data: SAMPLE_DATA.children,
          universalTransition: true,
          itemStyle: { borderWidth: 1, borderColor: "rgba(255,255,255,.5)" },
          label: { show: false },
        },
      ],
    }
    let currentOption: any = treemapOption
    const timer = setInterval(() => {
      currentOption = currentOption === treemapOption ? sunburstOption : treemapOption
      chart.setOption(currentOption as any, true)
    }, 3000)
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => {
      clearInterval(timer)
      ro.disconnect()
      chart.dispose()
    }
  }, [])

  return (
    <div className="flex h-screen w-screen flex-col bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
        路由: <code className="rounded bg-slate-200 px-1.5 py-0.5">/heatmap-demo</code> · 数据: 官方 <code>echarts-package-size.json</code> 简化版
      </div>
      <div ref={ref} className="h-[600px] w-full" />
    </div>
  )
}

export default HeatmapDemoPage

// -----------------------------------------------------------------------------
// 第二个 demo: 直接 fetch /api/stock-chart/industry-application/heatmap,
// 用 echarts treemap 渲染, 跟 sector-heatmap.tsx 的 data shape 一模一样。
// 用于排查: 是数据问题, 还是 ECharts 配置问题。
// -----------------------------------------------------------------------------
const HEATMAP_API = "http://localhost:5000/api/stock-chart/industry-application/heatmap"

export function HeatmapDataDebug() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [payload, setPayload] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(HEATMAP_API)
      .then((r) => r.json())
      .then((j) => setPayload(j))
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!ref.current || !payload) return
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" })
    const items: any[] = payload.items || []
    const data = items.map((s) => ({
      name: s.name,
      value: Math.max(s.amount || s.value || 1, 1),
      children: (s.children || []).map((c: any) => ({
        name: c.name && c.name !== c.code ? c.name : c.code.slice(-4),
        value: Math.max(c.amount || 1, 1),
      })),
    }))
    chart.setOption({
      title: { text: "后端 heatmap 真实数据 → ECharts treemap", left: 16, top: 8 },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: { show: true, formatter: "{b}" },
          data,
        },
      ],
    })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.dispose() }
  }, [payload])

  return (
    <div className="flex h-screen w-screen flex-col bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
        路由: <code className="rounded bg-slate-200 px-1.5 py-0.5">/heatmap-data-debug</code>
        · 状态: {error ? <span className="text-red-600">{error}</span> : payload ? `ok, ${payload.items?.length || 0} sectors, ${payload.totalStocks || 0} stocks` : "loading…"}
      </div>
      <div ref={ref} className="h-[600px] w-full" />
    </div>
  )
}
