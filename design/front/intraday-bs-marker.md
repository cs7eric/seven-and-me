# 当日分时图 B/S 标记 技术方案

> 适用范围：`frontend/src/views/application-analysis/components/intraday-analysis-dialog.tsx`
> 目标：让用户能在「分时图」tab 上手动标记买入/卖出点，跨刷新、跨日期、跨 period 共享，并落到后端持久化。

## 1. 背景 & 痛点
- 现存 `stock-chart` 主图已经实现了 K 线上的 B/S 标记（见 `stock-chart/index.tsx` + `annotationToSignal`），但「当日分时分析」Dialog 里没有。
- 第一版只用本地 `useState` + Recharts `<ComposedChart onClick>`，存在两个问题：
  1. Recharts 的 `onClick` 在图表背景（非 line/bar 元素）上不会提供 `activeTooltipIndex`，落点失败。
  2. 标记没有持久化，关掉 Dialog 全部丢失。

## 2. 复用 vs 新建
- **复用** `StockAnnotation` 通道（`POST/GET/DELETE /api/stock-chart/annotations`），与 stock-chart 主图保持一致。
- B/S 标记统一用：
  - `overlay_type = "bs_point"`
  - `period = "bs_signals"`（新约定的伪周期，跨 period 共享一份）
  - `points = [{ timestamp, value }]`
  - `text = "B:manual" | "S:manual"`
  - `styles.side = "B" | "S"`, `styles.source = "manual"`

> 不新建路由、不动后端 schema、不动数据库结构。仅在客户端约定 `period` 字段当作 B/S 命名空间。

## 3. 数据模型
```ts
// 前端运行态
type MarkerMode = "none" | "B" | "S"

// 与 stock-chart 主图共用
type StockSignalPoint = {
  id: string
  timestamp: number
  price: number
  side: "B" | "S"
  label?: string
  reason?: string
  score?: number
  period?: string
  source?: "manual"
  trade_date?: string
}
```
- 转换：`annotationToSignal(annotation)` 复用 `stock-chart/index.tsx` 同款逻辑（`overlay_type === "bs_point"`，text 首字母取 side）。

## 4. UI 流程
1. 工具栏（分时图卡片右上）：
   - `ToggleGroup`：`B` / `S` 互斥，再点一次取消。
   - 模式非 none 时，整张图表加 `cursor-crosshair`，并提示「点击分时图落点标记 B/S」。
   - 出现标记后，露出「清空 (N)」按钮。
2. 点击图表：
   - 在 `chartWrapperRef` 的 `onClick` 里，按容器宽 + 已知左右 margin（38 / 8）反推 `data index`：
     ```
     plotWidth = containerWidth - LEFT_OFFSET - RIGHT_OFFSET
     index     = round((clickX - LEFT_OFFSET) / (plotWidth / (n - 1)))
     ```
   - 拿 `payload.timeshare[index]` 构造 `StockSignalPoint`。
   - 乐观更新本地 state（临时 id `tmp-xxx`）→ 调 `createStockAnnotation` → 返回真 id 后替换。
   - 持久化失败回滚。
3. 落点自动回到 `markerMode = "none"`，避免误连点。
4. 图表下方「标记列表」chip 行（红/绿底 + 时间 + 价格 + ×）：
   - 单独删除 → `deleteStockAnnotation` + 本地移除，失败回滚。
   - 一键清空 → 并发 `deleteStockAnnotation`，失败回滚整组。
5. 切换股票 / 重新打开 Dialog：
   - `useEffect([open, targetType, symbol])` → 调 `listStockAnnotations(..., "bs_signals")` → 过滤 `bs_point` → 写入本地。
   - 跨日期共享标记（标记里有 `timestamp`，不匹配当天 `timeshare` 的会在 `visibleMarkers` 里被 `findIndex` 过滤掉）。

## 5. 渲染
- **不用** Recharts `<ReferenceDot>`：x 必须是 XAxis dataKey 的精确匹配值，且 `label` 函数的 `viewBox` 在不同 Recharts 版本里 shape 不一致，标记经常不显示。
- 改用**自定义 SVG 覆盖层**（绝对定位在图表容器之上，`pointer-events-none` 不抢点击）：
  - `ResizeObserver` 监听 `chartWrapperRef` 尺寸，存到 `chartSize`。
  - `visibleMarkers = useMemo(...)` 用与点击反推**完全一致**的几何公式（`LEFT_OFFSET=38 / RIGHT_OFFSET=8 / TOP_OFFSET=18`）计算每个 marker 的 `(x, y)` 像素坐标。
  - SVG 里画：竖向虚线（贯穿整个图高）+ 实心圆点 + B/S 圆角徽标 + 白色文字。
- 坐标系 = 容器像素坐标（`width={chartSize.width} height={chartSize.height}`），与点击反推 100% 对齐。

## 6. 失败 & 边界
| 场景 | 处理 |
| --- | --- |
| 持久化失败 | 乐观新增回滚（删除临时标记），不影响图表已有标记 |
| 切换股票 / 交易日 | `useEffect([open, targetType, symbol])` 重新拉取 |
| 点击超出 plot 区 | 命中区间判断直接 return |
| `payload.timeshare` 为空 | 早返回，不报错 |
| Recharts 容器宽度变化 | `getBoundingClientRect()` 实时取宽，几何反推无缓存问题 |
| 同点位重复落点 | 允许（用户主动操作即可），去重留给后续 |

## 7. 接口契约（无新增）
| 用途 | 接口 |
| --- | --- |
| 拉取 | `GET /api/stock-chart/annotations?target_type=...&symbol=...&period=bs_signals` |
| 新增 | `POST /api/stock-chart/annotations` body 同上 + `overlay_type=bs_point` |
| 删除 | `DELETE /api/stock-chart/annotations/{id}?target_type=...&symbol=...&period=bs_signals` |

## 8. 后续可扩展
- 标记 `reason` 字段：现在固定 `"manual"`，后续可加弹窗让用户输入一句话，自动写进 `text` 的 `B:xxx` 部分。
- K 线 tab 同步：复用同一份 `markers`，在 `CandleOverlay` 上也画 B/S（只显示 `trade_date` 匹配当天的）。
- 复盘笔记联动：标记点击时把 B/S 时间 + 价格附到右侧笔记末尾。
