# 前端 Component 文档

> 项目: `mp4-to-word-new` · 路径: `frontend/src`
> 框架: React 19 + Vite 8 + TypeScript + Tailwind 4 + shadcn/ui (radix-ui)
> 路由: react-router-dom v7 (`createBrowserRouter`)
> 状态: zustand (轻) + URL query (重) + 组件内 useState/useRef (局部)
>
> 最近更新: 把 `views/market/market-pulse.tsx` 的内部 UI 全部下沉到 `views/market/components/` 和 `views/market/lib/` (主文件 765 → 318 行, -58%)

本文档以**组件**为颗粒度（不是以文件为颗粒度）：一个 `.tsx` 文件内可能封装了多个 React 组件，文档会逐个列出。同时标记组件是否在多 page 复用，便于把可复用部分抽到 `src/components/` 公共目录。

---

## 目录

1. [路由与布局](#1-路由与布局)
2. [全局通用组件 (`src/components/`)](#2-全局通用组件)
3. [UI 基础组件 (`src/components/ui/`)](#3-ui-基础组件)
4. [业务组件（按 page 维度）](#4-业务组件按-page-维度)
   - [4.1 Home (`/`)](#41-home-)
   - [4.2 Dashboard (`/dashboard`)](#42-dashboard-dashboard)
   - [4.3 Downloader (`/downloader`)](#43-downloader-downer)
   - [4.4 MP4 to Word (`/mp4-to-word`, `/mp4-to-word/history`)](#44-mp4-to-word-mp4-to-word-mp4-to-wordhistory)
   - [4.5 Stock Chart (`/stock-chart`)](#45-stock-chart-stock-chart)
   - [4.6 Stock Overview (`/stock-overview`)](#46-stock-overview-stock-overview)
   - [4.7 Market Pulse & Sentiment (`/market/pulse`, `/market/sentiment`)](#47-market-pulse--sentiment-marketpulse-marketsentiment)
   - [4.8 Application Analysis (`/stock-overview/application-analysis`)](#48-application-analysis-stock-overviewapplication-analysis)
   - [4.9 Industry / Concept Application (`/stock-overview/industry-application`)](#49-industry--concept-application-stock-overviewindustry-application)
   - [4.10 Self-Selected (`/stock-overview/self-selected`)](#410-self-selected-stock-overviewself-selected)
   - [4.11 Stock Review (`/stock-review`)](#411-stock-review-stock-review)
   - [4.12 Settings · Scheduler (`/settings/scheduler`)](#412-settings--scheduler-settingsscheduler)
   - [4.13 Heatmap Demo (`/heatmap-demo`, `/heatmap-data-debug`)](#413-heatmap-demo-heatmap-demo-heatmap-data-debug)
5. [复用建议 / 重构清单](#5-复用建议--重构清单)
6. [路由表（汇总）](#6-路由表汇总)
7. [重构交付记录](#7-重构交付记录)

---

## 1. 路由与布局

### 路由表

入口 `src/router/index.tsx:1-99`，结构：

| Path | Element（page） | 文件 |
| --- | --- | --- |
| `/` | `HomePage` | `src/views/home.tsx` |
| `/downloader` | `DownloaderPage` | `src/views/downloader/index.tsx` |
| `/dashboard` | `DashboardPage` | `src/views/dashboard/index.tsx` |
| `/mp4-to-word` | `Mp4ToWordPage` | `src/views/mp4-to-word/page.tsx` |
| `/mp4-to-word/history` | `Mp4HistoryPage`（列表态） | `src/views/mp4-to-word/history.tsx` |
| `/mp4-to-word/history/:id` | `Mp4HistoryPage`（详情态） | `src/views/mp4-to-word/history.tsx` |
| `/stock-chart` | `StockChartPage` | `src/views/stock-chart/index.tsx` |
| `/stock-overview` | `StockOverviewPage` | `src/views/stock-overview/index.tsx` |
| `/stock-overview/market` | `MarketPulseMock` | `src/views/stock-overview/mock-market.tsx` |
| `/market/pulse` | `MarketPulsePage` | `src/views/market/market-pulse.tsx` |
| `/market/sentiment` | `MarketSentimentPage` | `src/views/market/market-sentiment.tsx` |
| `/stock-overview/application-analysis` | `ApplicationAnalysisPage` | `src/views/application-analysis/index.tsx` |
| `/stock-overview/industry-application` | `IndustryApplicationPage` | `src/views/industry-application/index.tsx` |
| `/stock-overview/self-selected` | `SelfSelectedPage` | `src/views/self-selected/index.tsx` |
| `/stock-review` | `StockReviewPage` | `src/views/stock-review/index.tsx` |
| `/settings/scheduler` | `SchedulerSettingsPage` | `src/views/settings/scheduler/index.tsx` |
| `/heatmap-demo` | `HeatmapDemoPage` | `src/views/heatmap-demo/index.tsx` |
| `/heatmap-data-debug` | `HeatmapDataDebug` | `src/views/heatmap-demo/index.tsx` |

### 顶层 App

- **`App`** · `src/App.tsx:3-7` · 单一 `<Outlet/>`，是 `createBrowserRouter` 的根 element。

### 布局层 (`src/layout/`)

| 组件 | 文件 | 用途 | 被哪些 page 引用 |
| --- | --- | --- | --- |
| **`WorkspaceShell`** | `src/layout/workspace-shell.tsx:39-108` | 整个应用统一外壳：左侧 `AppSidebar` + 顶部 breadcrumb + `GlobalCommandTrigger` + `GlobalCommandPalette` + `NotificationRoot`，主体通过 children 传入。带 `fullBleed` 选项（去掉外 padding）。 | **几乎所有 page**：`Home`, `Dashboard`, `Downloader`, `Mp4ToWordPage`, `Mp4HistoryPage`, `StockChartPage`, `StockOverviewPage`, `MarketPulse` (mock), `MarketPulsePage`, `MarketSentimentPage`, `ApplicationAnalysisPage`, `IndustryApplicationPage`, `SelfSelectedPage`, `StockReviewPage`, `SchedulerSettingsPage` |
| **`AppSidebar`** | `src/layout/app-sidebar.tsx:18-34` | 左侧 sidebar 外壳：内含 `TeamSwitcher` + `NavMain` + `NavProjects` + `NavUser`。 | 由 `WorkspaceShell` 间接使用 |
| **`NavMain`** | `src/layout/nav-main.tsx:24-150` | 应用导航（dashboard / mp4-to-word / market / stock-overview / stock-review / settings），支持二级 collapsible group，open 状态持久化到 `localStorage("app-sidebar-open-groups")`。 | 由 `AppSidebar` 间接使用 |
| **`NavProjects`** | `src/layout/nav-projects.tsx:29-92` | sidebar 底部 "Projects" 分组链接 + 右键 dropdown（Open / Share / Archive）。 | 由 `AppSidebar` 间接使用 |
| **`NavUser`** | `src/layout/nav-user.tsx:31-112` | sidebar 底部用户菜单（Upgrade / Account / Billing / Notifications / Log out）。 | 由 `AppSidebar` 间接使用 |
| **`TeamSwitcher`** | `src/layout/team-switcher.tsx:22-91` | sidebar 顶部 workspace 切换 dropdown。 | 由 `AppSidebar` 间接使用 |

> **可复用性**：WorkspaceShell 已经是事实上的"应用外壳"，所有 page 都应该套它。

---

## 2. 全局通用组件

> 路径: `src/components/`

| 组件 | 文件 | 用途 | 被哪些 page / 场景引用 |
| --- | --- | --- | --- |
| **`AnimatedList`** | `src/components/AnimatedList.tsx:49-197` | 带 motion 入场动画的虚拟列表：支持键盘上下/ Tab 导航、滚动渐变遮罩、controlled / uncontrolled 选中态、自定义渲染、空态。 | `IndustryApplicationPage` 左侧 Watchlist（仅 `false && (...)` 包裹的隐藏代码使用）；其他未直接使用 |
| **`ChartAreaInteractive`** | `src/components/chart-area-interactive.tsx:143-286` | shadcn 风格的可交互面积图（基于 recharts），支持 90d/30d/7d 时间切换，移动端 fallback。 | **未被任何 page 引用**（属于 shadcn 模板保留组件） |
| **`DataTable`** | `src/components/data-table.tsx:337-626` | shadcn 风格通用可拖拽表格（dnd-kit + @tanstack/react-table），含分页 / 排序 / 列显示控制 / 行选择。表格项类型用 zod schema 写死。 | **未被任何 page 引用**（属于 shadcn 模板保留组件） |
| **`MP4HistoryDataTable`** | `src/components/mp4-history-data-table.tsx:177-360` | **专门**给 `Mp4HistoryPage` 用的可拖拽历史列表，含 Filter / 列显示 / 翻页 / 调 `deleteMP4History` / `reorderMP4History`。 | `Mp4HistoryPage` (列表态) |
| **`GlobalCommandTrigger`** | `src/components/global-command-palette.tsx:91-108` | 顶栏右侧「搜索 Alt+K」按钮，点开 `GlobalCommandPalette`。 | `WorkspaceShell` 内嵌（所有 page 顶部） |
| **`GlobalCommandPalette`** | `src/components/global-command-palette.tsx:110-299` | 浮层命令面板（基于 cmdk + `CommandDialog`）：聚合 ① 静态 12 个页面导航 ② 自选股 ③ Application Analysis 标的 ④ MP4 历史 5 条。数据走 `Promise.allSettled` 并 30s 缓存。**模块级 singleton** open 状态，可由 `openGlobalCommand()` / `closeGlobalCommand()` 外部触发。 | `WorkspaceShell` 内嵌（portal 到 body） |
| **`NavDocuments`** | `src/components/nav-documents.tsx:28-92` | sidebar 用的 Documents 列表 + 右键 dropdown（Open / Share / Delete）。 | **未被引用**（保留组件） |
| **`NavSecondary`** | `src/components/nav-secondary.tsx:14-42` | sidebar 用的二级链接列表。 | **未被引用**（保留组件） |
| **`SectionCards`** | `src/components/section-cards.tsx:13-102` | 4 张营收/客户/活跃/增长指标卡（写死 mock 数据）。 | **未被引用**（保留组件） |
| **`SiteHeader`** | `src/components/site-header.tsx:5-30` | shadcn dashboard 模板 header。 | **未被引用**（保留组件） |
| **`StockDetailDialog`** | `src/components/stock-detail-dialog.tsx:104-1080` | 90vw 大对话框，**左侧 7 份 K 线 + IndicatorToolbar + ChartPanel，右侧 3 份 Tab（基本 / 财务 / 公告新闻研报）**。F10 数据走 `fetchStockMeta / fetchStockSectors / fetchStockValuation / fetchStockBusinessComposition / fetchStockFinanceReport / fetchStockAnnouncements / fetchStockNews / fetchStockRoadshows / fetchStockCompanyNews` 等 9 个 API。复用 `stock-chart` 的 `IndicatorToolbar` 和 `ChartPanel`。 | **当前仅由 `IndustryConstituentsDrawer` 内部调用**（点击成分股时弹） |
| **`DogLoader`** | `src/components/loader/dog-loader.tsx:10-99` | 纯 CSS "小狗"动画 loader；支持 `overlay` 全屏蒙版 / 嵌入态两态。 | `DashboardPage`、`StockOverviewPage`、`SelfSelectedPage`、`Mp4HistoryPage`、`SchedulerSettingsPage`（多处用全屏蒙版） |
| **`OverviewCard`** | `src/components/overview-card.tsx:1-` | 占位 / 简介型卡片 `{title, description}`。**统一了 dashboard + stock-review 100% 重复的 2 份文件**。 | `DashboardPage`, `StockReviewPage` |
| **`MetricCard`** | `src/components/metric-card.tsx:1-` | 小指标卡：label + value + icon + 3 种 tone (slate/teal/violet)。 | `ApplicationAnalysisPage` 内的 `OverviewCard` (4 个 metric 组合) |
| **`CollapsibleCard`** | `src/components/collapsible-card.tsx:1-` | 通用可折叠卡：title / description / icon / badge / 折叠按钮 + 内容区。 | `ApplicationAnalysisPage` 内 4 处: `OverviewCard` / `AIDirectionCard` / `ChartCard` / `SelectionPanel` |
| **`EmptyState`** | `src/components/empty-state.tsx:1-` | 通用空态：title / description / icon / 可选 children / Card 包裹开关。**新增**, 留作未来 page 统一空态。 | 当前未直接引用（view-local `NotApplicableCard` 视觉差异保留） |
| **`AskSection`** | `src/components/ask-section.tsx:1-` | Ask AI 问答折叠列表（每条可单独折叠/展开），通过事件代理捕获 `.qa-followup-chip` 的 `data-followup` 实现追问。 | `Mp4ToWordPage`, `Mp4HistoryPage` |
| **`FloatingAskBar`** | `src/components/floating-ask-bar.tsx:1-` | 任务可见时的浮动输入条，Enter 提交，loading 时换 placeholder。 | `Mp4ToWordPage`, `Mp4HistoryPage` |
| **`ReaderModal`** | `src/components/reader-modal.tsx:1-` | 简易"阅读模式"模态（黑底 + 文字 + 关闭）。 | `Mp4ToWordPage` |
| **`IndustryConstituentsDrawer`** | `src/components/industry-constituents-drawer.tsx:1-` | 行业 / 概念 / 风格板块"成分股" 抽屉（**支持 external data 模式**, 14 列行情, 表头排序, 点击名称弹 `StockDetailDialog`）。 | `IndustryApplicationPage` (KLine / 资金流 Tab), `MarketPulsePage` (风格板块点击 cell) |
| **`ConfirmDialog`** | `src/components/ui/confirm-dialog.tsx:1-` | 通用确认弹窗：title / description / icon / 确认 / 取消 / destructive / pending (同时支持 internal + external)。 | `SelfSelectedPage` (删除分类), `ItemRow` (删除自选股) |
| **`app/*`** | `src/components/app/` | (空目录) | — |

> 关键判断：
> - `MP4HistoryDataTable` 已经独立、专门给一个 page 用，**无需重构成公共组件**。
> - `GlobalCommandPalette` + `GlobalCommandTrigger` 已经是真正的"全局"基础设施，无需重命名。
> - `StockDetailDialog` 内嵌 4 个子组件：`EmptyPlaceholder`、`BasicInfoCard`、`SectorAffiliationCard`、`FinanceSnapshotCard`、`NewsAndResearchCard`（详见 §4.9）。
> - `ChartAreaInteractive / DataTable / NavDocuments / NavSecondary / SectionCards / SiteHeader` 是 shadcn 模板保留，**当前未被引用**（不建议删除，保留以便后续 dashboard 改造直接复用）。

---

## 3. UI 基础组件

> 路径: `src/components/ui/`，均为 shadcn/ui 风格原子组件。

| 组件 | 文件 | 导出 | 备注 |
| --- | --- | --- | --- |
| **`Alert`** + `AlertTitle` + `AlertDescription` | `alert.tsx` | `Alert, AlertTitle, AlertDescription` | 多 page 通用 |
| **`Avatar`** + `AvatarFallback` + `AvatarImage` | `avatar.tsx` | (同前) | 仅 `NavUser` 用 |
| **`Badge`** + `badgeVariants` | `badge.tsx` | `Badge, badgeVariants` | 全局最高频 |
| **`Breadcrumb`** + `BreadcrumbList`/`BreadcrumbItem`/`BreadcrumbLink`/`BreadcrumbPage`/`BreadcrumbSeparator` | `breadcrumb.tsx` | (全量) | `WorkspaceShell` 用 |
| **`Button`** + `buttonVariants` | `button.tsx` | `Button, buttonVariants` | 全局最高频 |
| **`Card`** + `CardHeader`/`CardTitle`/`CardDescription`/`CardContent`/`CardFooter`/`CardAction` | `card.tsx` | (全量) | 全局最高频 |
| **`ChartContainer`** + `ChartTooltip`/`ChartTooltipContent` + type `ChartConfig` | `chart.tsx` | `ChartContainer, ChartTooltip, ChartTooltipContent, ChartConfig` | `ChartAreaInteractive`（未引用） |
| **`Checkbox`** | `checkbox.tsx` | `Checkbox` | `DataTable`（未引用） |
| **`Collapsible`** + `CollapsibleTrigger` + `CollapsibleContent` | `collapsible.tsx` | (全量) | `NavMain` |
| **`CommandDialog`** + `CommandInput` + `CommandList` + `CommandEmpty` + `CommandGroup` + `CommandItem` | `command.tsx` | (全量) | `GlobalCommandPalette` |
| **`Dialog`** + `DialogTrigger`/`DialogContent`/`DialogHeader`/`DialogTitle`/`DialogDescription`/`DialogFooter`/`DialogClose` | `dialog.tsx` | (全量) | `StockDetailDialog`, `DeleteJobButton`, `ConfirmDialog`, `CreateGroupDialog`, `CreateItemDialog` |
| **`Drawer`** + `DrawerTrigger`/`DrawerContent`/`DrawerHeader`/`DrawerTitle`/`DrawerDescription`/`DrawerFooter`/`DrawerClose` | `drawer.tsx` | (全量) | `IndustryConstituentsDrawer` |
| **`DropdownMenu`** + 子件 | `dropdown-menu.tsx` | (全量) | `NavProjects`, `NavUser`, `TeamSwitcher`, `DataTable`（未引用）等 |
| **`Input`** | `input.tsx` | `Input` | 全局最高频 |
| **`Label`** | `label.tsx` | `Label` | `DataTable`（未引用）, `CreateGroupDialog`, `CreateItemDialog` |
| **`Notification`** + `NotificationRoot` + `NotificationVariant` | `notification.tsx` | `NotificationRoot, notification.{info,success,warn,danger,error}` | `WorkspaceShell` 装容器，**所有 page 业务通知走它**（`notification.success({...})`） |
| **`Progress`** | `progress.tsx` | `Progress` | `Mp4ToWordPage` 的 step 进度，`MarketOverviewPage` 的 `RegimeHero`，`CycleMatrix` |
| **`ScrollArea`** + `ScrollBar` | `scroll-area.tsx` | `ScrollArea, ScrollBar` | `StockDetailDialog` |
| **`Select`** + `SelectTrigger`/`SelectContent`/`SelectItem`/`SelectValue` | `select.tsx` | (全量) | `ChartAreaInteractive`（未引用）, `MP4HistoryDataTable`, `DataTable`（未引用）, `ChartHeader` |
| **`Separator`** | `separator.tsx` | `Separator` | 多个 page 通用 |
| **`Sheet`** + 子件 | `sheet.tsx` | (全量) | 保留未使用 |
| **`Sidebar`** + 子件 | `sidebar.tsx` | (全量: `Sidebar`, `SidebarContent`, `SidebarHeader`, `SidebarFooter`, `SidebarRail`, `SidebarInset`, `SidebarProvider`, `SidebarTrigger`, `useSidebar`, `SidebarMenu`, `SidebarMenuItem`, `SidebarMenuButton`, `SidebarMenuAction`, `SidebarGroup`, `SidebarGroupLabel`, `SidebarGroupContent`, `SidebarMenuSub`, `SidebarMenuSubItem`, `SidebarMenuSubButton`) | `WorkspaceShell` + `AppSidebar` + `Nav*` |
| **`Skeleton`** | `skeleton.tsx` | `Skeleton` | `StockDetailDialog`, `Mp4ToWordPage`（`TextSkeletonBlock`） |
| **`Table`** + `TableHeader`/`TableBody`/`TableRow`/`TableHead`/`TableCell` | `table.tsx` | (全量) | `DataTable`（未引用）, `MP4HistoryDataTable` |
| **`Tabs`** + `TabsList`/`TabsTrigger`/`TabsContent` + `tabsListVariants` | `tabs.tsx` | (全量) | `StockDetailDialog`, `DataTable`（未引用）, `MarketSentimentPage`（未引用）, `ApplicationAnalysisPage`, `IndustryApplicationPage`, `SelfSelectedPage`, `StockChartPage` |
| **`ToggleGroup`** + `ToggleGroupItem` | `toggle-group.tsx` | (全量) | `ChartAreaInteractive`（未引用） |
| **`Toggle`** + `toggleVariants` | `toggle.tsx` | (同前) | 保留未使用 |
| **`Tooltip`** + `TooltipTrigger`/`TooltipContent`/`TooltipProvider` | `tooltip.tsx` | (全量) | 保留未使用 |

---

## 4. 业务组件（按 page 维度）

### 4.1 Home (`/`)

文件: `src/views/home.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `HomePage` (default export) | `home.tsx:289-351` | 应用总览：用 `WorkspaceShell` 包一层，按 `sections` (overview / media-tools / stock-workspace / settings) 分组展示应用入口卡片（每张卡带 lucide 图标 + 渐变背景 + 手工 SVG 插画）。 |
| *(模块级 const)* | `home.tsx:37-189` | 7 个手工 SVG 插画 (`DownloaderIllustration` / `Mp4ToWordIllustration` / `Mp4HistoryIllustration` / `StockOverviewIllustration` / `DashboardIllustration` / `StockReviewIllustration` / `SelfSelectedIllustration` / `SettingsIllustration`) + `sections: SectionItem[]` 数据源 |

> **页面内组件定义**：`ApplicationItem`、`SectionItem`（类型），8 个 Illustration const（仅本文件使用）。**没有需要抽出公共组件**。

---

### 4.2 Dashboard (`/dashboard`)

文件: `src/views/dashboard/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `DashboardPage` (default export) | `index.tsx:8-45` | 占位总览页：标题 + `OverviewCard` 网格 + `NextStepSection` + `DogLoader overlay`（loading 时） |
| **`OverviewCard`** | 引用 `@/components/overview-card.tsx` | 简单卡片：`{title, description}` 两行文本（**已抽到公共目录**, 跟 stock-review 合并） |
| **`NextStepSection`** | 引用 `dashboard/components/next-step-section.tsx:27-81` | 「下一步」链接集合：3 个 Link（Stock Workspace / MP4 to Word / Settings）+ 2 个 CTA 按钮 |

数据源: `lib/content.ts` → `dashboardCards: DashboardCard[]`（6 个占位卡）。

---

### 4.3 Downloader (`/downloader`)

文件: `src/views/downloader/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `DownloaderPage` (default export) | `index.tsx:16-299` | 视频 / 帖子链接解析：textarea + 粘贴 + 解析按钮 → 展示 `DownloaderParseData`（platform / title / 多链接 / 分 P / embedded videos）→ "Send to Parse" 跳到 `/mp4-to-word?mode=remote&...` |
| **`LinkActionRow`** | `components/link-action-row.tsx:6-39` | 一行链接 + Copy 按钮（带 1.5s 已复制态）+ Open 按钮（新窗口）。 |
| **`LoadingState`** | `components/loading-state.tsx:3-16` | 解析中的 Skeleton 占位（title + 2 line + 2 卡片骨架）。 |

数据源: `lib/api.ts` → `parseDownloaderUrl`, `formatDuration`, `summarizeUrl`。

> **可复用性**：`LinkActionRow` 非常通用，**已具备被抽到 `src/components/` 的资格**（当前 view-local 即可，也可挪到全局）。`LoadingState` 仅 downloader 用，但也可抽到全局作为通用 loading placeholder。

---

### 4.4 MP4 to Word (`/mp4-to-word`, `/mp4-to-word/history`)

#### 4.4.1 `/mp4-to-word` 主页面

文件: `src/views/mp4-to-word/page.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `Mp4ToWordPage` (default export) | `page.tsx:159-1178` | 完整上传 + 转写 + AI Polish + Summary 流水线：文件 dropzone / remote URL 接管 → SSE 进度 → 三栏结果（transcript / polished / summary）+ Ask AI 区 + FloatingAskBar + ReaderModal。 |
| **`TextSkeletonBlock`** | `page.tsx:83-94` | 多行文字骨架（10 行 Skeleton，错位宽度）。 |
| **`ProgressCard`** | `page.tsx:96-157` | 进度卡：百分比 / 进度条 / Speed / ETA / Total 三栏。给下载 + 转写两个阶段共用。 |

> 这些 helper 是 page 局部，外部无引用。**`ProgressCard` 抽象度足够高，可考虑抽出到 `src/components/` 给 history 页用**。

#### 4.4.2 `/mp4-to-word/history` 历史

文件: `src/views/mp4-to-word/history.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `Mp4HistoryPage` (default export) | `history.tsx:243-318` | 列表 / 详情双态：列表态渲染 `MP4HistoryDataTable`；详情态（`/mp4-to-word/history/:id`）渲染 `HistoryContent`。 |
| **`DetailPanel`** | `history.tsx:25-31` | 单卡容器：包裹 `dangerouslySetInnerHTML`，给 transcript / polished 视图。 |
| **`AskHistoryPanel`** | `history.tsx:33-58` | 简单 wrapper，把 props 透传到 `<AskSection>`（仅用于 `collapsed` prop 类型安全）。 |
| **`HistoryContent`** | `history.tsx:60-241` | 历史详情：Header 卡（type / status / task_id / file / platform / duration / source / tags / categories）+ 4 个 tab 切换（Summary / Polished / Transcript / Ask AI）+ `FloatingAskBar`。 |

复用的子组件（**已抽到 `src/components/` 公共目录**）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`AskSection`** | `@/components/ask-section.tsx` | Ask AI 问答折叠列表（每条可单独折叠/展开），`onFollowupClick` 通过冒泡事件代理（data-followup）。 |
| **`FloatingAskBar`** | `@/components/floating-ask-bar.tsx` | 任务可见时的浮动输入条，Enter 提交，loading 时换 placeholder。 |
| **`ReaderModal`** | `@/components/reader-modal.tsx` | 简易"阅读模式"模态（黑底 + 文字 + 关闭）。 |

> 已抽到公共目录，跨 `Mp4ToWordPage` / `Mp4HistoryPage` 复用。

---

### 4.5 Stock Chart (`/stock-chart`)

文件: `src/views/stock-chart/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `StockChartPage` (default export) | `index.tsx:131-507` | 股票 / 指数 / 板块 K 线工作台：SymbolSearch + IndicatorToolbar + ChartPanel + BS 标记 CRUD + 3 个 Tab（集合竞价 / 技术指标 / 资金）。 |
| *（模块级 helper）* | `index.tsx:33-128` | `INDEX_KLINE_SYMBOLS` 静态表（上证 / 上证50 / 沪深300 / 中证500 / 中证1000 / 中证2000 / 创业板 / 科创50）, `loadContextIndexBars`, `settledBarsToMap`, `annotationToSignal`, `isSameTradeDate`, `mapSignalToVisibleBar` |

子组件（在 `stock-chart/components/`）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`SymbolSearch`** | `components/symbol-search.tsx:16-` | Symbol 搜索输入（debounce 调 `searchStockChart`），命中后 onSelect 写入 store。 |
| **`IndicatorToolbar`** | `components/indicator-toolbar.tsx:29-` | 顶部工具栏：period（1d/5m/1w/1m/...）、adjust（qfq/none/hfq）、副图指标 toggles、MA 线 toggles。`compact` prop 给 `StockDetailDialog` 复用。 |
| **`ChartPanel`** | `components/chart-panel.tsx:697-` | K 线主图 + 副图（基于 klinecharts）：支持 annotations / BS signals / manual 落点 / yAxisPosition。`ChartPanelSelectionItem` 类型给 ApplicationAnalysis 复用。 |
| **`AuctionPanel`** | `components/auction-panel.tsx:774-` | 集合竞价面板（含 `MetricCard`, `DetailTimeline`, `TdxLegend`, `PriceVolumeChart`, `UnmatchedChart`, `TdxAuctionChart`, `EnhancedMetrics`, `PhaseBlock` 等子组件） |
| **`TechnicalIndicatorPanel`** | `components/technical-indicator-panel.tsx:943-` | 技术指标综合面板（含 17 个子组件：`ScoreBar`, `TechnicalScoreCard`, `RiskScoreCard`, `CompositeScoreCard`, `MarketEnvCard`, `FinalOpportunityCard`, `TrendStatusOverview`, `MAPositionSection`, `MASlopeSection`, `BiasRateSection`, `VolumeMetricsSection`, `RSIATRSection`, `MACDSection`, `MAAlignmentSection`, `SignalCards`, `InterpretationText`, `KeyPriceZoneSection`, `BacktestSection`） |

数据: `useStockChartStore` (zustand) + `lib/api` 的 `fetchStockKlines / fetchStockAuction / fetchStockMeta / fetchMarketBreadth / fetchMarketBreadthSeries / fetchStockWorkspace / saveStockWorkspace / createStockAnnotation / deleteStockAnnotation / listStockAnnotations`。

> **可复用性**：`IndicatorToolbar` + `ChartPanel` 已经被 `StockDetailDialog` 直接复用，**已经是被多 page 复用的公共组件**，文件位置可以维持，但 props 名字带 `compact` 是个内部标志，看是否需要规范化（保持即可）。

---

### 4.6 Stock Overview (`/stock-overview`)

#### 4.6.1 主页面

文件: `src/views/stock-overview/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `StockOverviewPage` (default export) | `index.tsx:705-769` | "市场情景驾驶舱"：调用 `fetchMarketOverview()`，按 hero / shanghaiMap / cycleMatrix / internalStructure / similarScenarios / industryLeadership 6 大块展示。 |
| **`SectionHeader`** | `index.tsx:249-259` | 通用 卡片 header：eyebrow 大写小标签 + title + description 三件套。 |
| **`RegimeHero`** | `index.tsx:261-297` | 顶部 hero：regime headline / 综述分 / 进攻等级 / 风险等级 + 3 张 mini（最近压力 / 支撑 / 主导风格）。 |
| **`HeroStat`** | `index.tsx:299-307` | 数字 + progress 副指标的小卡。 |
| **`HeroMini`** | `index.tsx:309-317` | 3 张 mini（label + value + tone）。 |
| **`ActionPlanCard`** | `index.tsx:319-340` | 行动剧本卡（stance + 4 列 SignalList）。 |
| **`SignalList`** | `index.tsx:342-365` | 适合 / 不适合 / 确认 / 失效 4 类信号列表（带左侧 border-l 强调色）。 |
| **`ShanghaiZoneMap`** | `index.tsx:390-499` | 上证 K 线 + 支撑 / 压力叠加（手画 SVG）。 |
| **`ZoneSummaryCard`** | `index.tsx:501-510` | "最近压力 / 支撑" 摘要卡。 |
| **`KLineZoneBand`** | `index.tsx:512-530` | SVG 内单个支撑 / 压力 band（红涨 / 绿跌 + 权重 alpha）。 |
| **`CycleMatrix`** | `index.tsx:532-564` | 多周期结构表（周期 / 涨跌幅 / 区间位置 / 距高点 / 状态）。 |
| **`InternalStructurePanel`** | `index.tsx:566-580` | 情绪 / 风格 / 行业三联动。 |
| **`StructureCard`** | `index.tsx:582-594` | 三联动内单卡。 |
| **`SimilarScenarioPanel`** | `index.tsx:596-635` | 历史相似市场回测卡。 |
| **`MetricTile`** | `index.tsx:637-644` | 极简 metric（label + 大数字）。 |
| **`IndustryLeadership`** | `index.tsx:646-664` | 强弱行业排行（含内部 `IndustryList`）。 |
| **`IndustryList`** | `index.tsx:666-694` | 强 / 弱 行业列表（含 `IndustryStat`）。 |
| **`IndustryStat`** | `index.tsx:696-703` | 行业 stat（5/20/60 日涨幅）。 |

> **可复用性**：这些组件**全部 view-local**。最有希望抽出到公共的：
> - `SectionHeader` —— 任何想用「eyebrow + title + description」组合的卡都能复用。
> - `MetricTile` / `HeroStat` —— 极简 metric，可做通用 "LabelTile"。
> - `SignalList`（支持 4 种 tone 边框）—— 任何 "适合 / 风险 / 确认 / 失效" 类列表都能复用。
>
> 详见 §5。

#### 4.6.2 mock-market（旧版 Market Pulse）

文件: `src/views/stock-overview/mock-market.tsx`（路由 `/stock-overview/market`）

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `MarketPulse` (default export) | `mock-market.tsx:1016-1102` | 行情老版页面：4 大块（强势板块 / 主力净流入 / 行业轮动 / 轮动历史趋势） + 行业钻入 drawer。 |
| `PageHeader` | `mock-market.tsx:214-267` | 顶部 header（标题 + 自动刷新说明 + 交易时间徽章 + 刷新 / 实时刷新按钮）。 |
| `SummaryStrip` | `mock-market.tsx:270-308` | 4 张概要卡（领涨 / 领跌 / 主力净流入 / 主力净流出）。 |
| `StrongSectors` | `mock-market.tsx:311-397` | 强势板块 grid 卡片。 |
| `CapitalFlow` | `mock-market.tsx:400-434` | 主力净流入/流出双列。 |
| `FlowColumn` | `mock-market.tsx:436-509` | 单列 flow。 |
| `IndustryRotation` | `mock-market.tsx:512-636` | 行业轮动矩阵（日期 × 排名）。 |
| `RotationTrend` | `mock-market.tsx:639-758` | 轮动历史趋势表。 |
| `IndustryDetailDrawer` | `mock-market.tsx:761-906` | 行业钻入抽屉（领涨股 + 30 天主力净流入 mini chart + 60 日 K 线 mini chart + 成分股）。 |
| `FlowMiniChart` | `mock-market.tsx:908-929` | 30 天 flow 柱图 mini。 |
| `KLineMini` | `mock-market.tsx:931-959` | 60 日 K 线 mini。 |
| `SchedulerStatusBar` | `mock-market.tsx:962-998` | 调度状态条（运行中 / 失败 / 正常 + 手动 snapshot 按钮）。 |
| `EmptyCard` | `mock-market.tsx:1000-1009` | 空数据占位。 |

> **可复用性**：
> - `EmptyCard` —— view-local 通用占位卡，可抽 `src/components/empty-card.tsx`。
> - `SchedulerStatusBar` —— 只有这一个 page 用，保留。
> - `IndustryDetailDrawer` / `FlowMiniChart` / `KLineMini` —— 都是 drawer 内部子件，保留。
> - `PageHeader` / `SummaryStrip` —— 跟新版 `MarketPulsePage` 有重叠（新版在 §4.7），**可考虑在新版里复用旧版的 PageHeader**。

---

### 4.7 Market Pulse & Sentiment (`/market/pulse`, `/market/sentiment`)

#### 4.7.1 `/market/pulse` 新版市场脉搏

> **本次重构**：把 `market-pulse.tsx` 主页的 UI 全部下沉，主页 765 → 318 行（-58%），逻辑/布局 100% 保留。

文件: `src/views/market/market-pulse.tsx`（主页，只保留 state/handler/页面组装）

主页**只保留**：
- 14 个 useState（items / overview / overviewCounts / constituents / heatmap / hoveredPoint / selectedPoint 等）
- 8 个 handler（load / loadOverview / mapToIndustryShape / loadConstituents / loadHeatmap / handlePointHover / clearReplay / setSelectedPoint toggle）
- 2 个 useEffect（轮询 + heatmap kind 切换）
- `mapToIndustryShape`（`formatReadable` 紧密耦合，留主页）
- JSX 顶层：`<MarketPulseHeader />` + 4 个 `<MarketOverviewCards/...>` + `<IndexKlineDeck/>` + `<MarketPulsePanel/>` + `<MarketStyleSectorsSection/>` + `<div h-420><IndustryHeatmap/></div>` + `<LimitEmotionPanel/>` + `<MarketPlaceholderCards/>` + `<MarketRoadmapNote/>` + 末尾 `<IndustryConstituentsDrawer/>`

子组件（**已下沉到 `views/market/components/`**）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`MarketPulseHeader`** | `components/market-pulse-header.tsx` | 顶部 chip (Flame) + h1 + 描述 p |
| **`MarketOverviewCards`** | `components/market-overview-cards.tsx` | **整段大盘成交额/主力净流入**（6 列 grid + 4 列超大/大/中/小单 + activePoint 历史日联动 IIFE + "返回今日" 按钮）。**最复杂的一个子组件** |
| **`MarketStyleSectorsSection`** | `components/market-style-sectors-section.tsx` | 风格板块标题 + refresh + error + 420px treemap 容器。`useMemo` 排序保留在组件内 |
| **`MarketPlaceholderCards`** | `components/market-placeholder-cards.tsx` | 6 张 "Mock · 待接入" 占位卡 + `PLACEHOLDER_CARDS` 常量 |
| **`MarketRoadmapNote`** | `components/market-roadmap-note.tsx` | 底部 dashed "路线" box |
| **`IndexKlineDeck`** | `components/index-kline-deck.tsx:49-` | 三大指数分时 + K 线 deck（含 `IndexKlineCard`）。支持 replay 模式 + pinned。 |
| **`IndexKlineCard`** | `components/index-kline-card.tsx:181-` | 单条指数 K 线卡（pill + 趋势）。 |
| **`StyleSectorsHeatmap`** | `components/style-sectors-heatmap.tsx:134-` | 29 个风格板块 ECharts treemap（`echarts/core` + `TreemapChart`）。 |
| **`IndustryHeatmap`** | `components/industry-heatmap.tsx:489-` | 行业板块 ECharts treemap（含 `FilterChip`, `SelectBar`），跟 style-heatmap 视觉一致。 |
| **`MarketPulsePanel`** | `components/market-pulse-panel.tsx:65-` | 历史趋势 4 视图复合图（含 `MarketPulseEChart`, `MarketPulseChart`, `PulseStats`）。 |
| **`MarketPulseEChart`** | `components/market-pulse-chart.tsx:568-` | ECharts 复合图（默认 4 视图可切换：flow / amount / count / breakRate）。 |
| **`MarketPulseChart`** | `components/market-pulse-chart.tsx:...` | （未在前述 grep 列出，可能是 `MarketPulseEChart` 别名） |
| **`MarketPulseStats`** (PulseStats) | `components/market-pulse-stats.tsx:54-` | 顶部 mini 指标条（hover 联动）。 |
| **`LimitEmotionPanel`** | `components/limit-emotion-panel.tsx:136-` | 涨跌停情绪面板（含 `StockTooltip`, `Cell`, `DistributionStrip`, `TierStockList`, `StockRow`, `PromotionTable`, `BrokenList` 等 7 个子件）。 |
| **`IndustryConstituentsDrawer`** | `@/components/industry-constituents-drawer.tsx:282-` | 行业 / 风格板块的"成分股" 抽屉（external data 模式），**被 `MarketPulsePage` 直接复用**。 |

工具函数（**已下沉到 `views/market/lib/`**）:

| 文件 | 内容 |
| --- | --- |
| `lib/format.ts` | `formatYi` / `formatWanShou` / `formatCount` / `moneyTone` / `diffBadgeTone` / `formatReadable` |
| `lib/trading-time.ts` | `getMostRecentTradingDayClient` / `isTradeTimeClient` |

> **跨 view 复用**：
> - `IndustryConstituentsDrawer` 跨 `IndustryApplicationPage` 和 `MarketPulsePage` 复用，**已经抽到 `src/components/` 公共目录**。
> - `MarketOverviewCards` / `MarketStyleSectorsSection` / `MarketPulseHeader` / `MarketPlaceholderCards` / `MarketRoadmapNote` 当前仅 `MarketPulsePage` 用，作 view-local 子组件存在。

#### 4.7.2 `/market/sentiment` 市场情绪（占位）

文件: `src/views/market/market-sentiment.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `MarketSentimentPage` (default export) | `market-sentiment.tsx:33-77` | 6 张情绪指标占位卡（Fear & Greed / Bull-Bear / News / Social / Margin / Regime）。 |

> 没有可抽出的子组件。

---

### 4.8 Application Analysis (`/stock-overview/application-analysis`)

文件: `src/views/application-analysis/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `ApplicationAnalysisPage` (default export) | `index.tsx:67-932` | 6 个 Tab（图表 / AI 方向 / 分析详情 / 集合竞价 / 技术指标 / 资金）的标的 AI 分析工作台：左侧 `TargetCard` + `SelectionPanel` + `Alerts`；右侧顶部 `ChartHeader` + 6 Tab。 |
| *（模块级 helper）* | `index.tsx:56-65` | `formatTradeDateFromTimestamp`（UTC+8 → yyyy-mm-dd） |

子组件（`application-analysis/components/`）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`TargetCard`** + type `HorizonPatch` | `components/target-card.tsx:18-` | 左侧 target 列表：搜索 / 启用 / 删除 / 触发 / 调度器状态 / 启用开关 / horizon 调节。 |
| **`SelectionPanel`** | `components/selection-panel.tsx:11-` | 选中 K 柱的列表 + 颜色映射 + 单项分析入口。 |
| **`ChartHeader`** | `components/chart-header.tsx:10-` | 顶部当前目标卡（含 adjust 选择 + 触发 / 手动单次按钮）。 |
| **`ChartCard`** | `components/chart-card.tsx:7-` | 包装 `ChartPanel`，接入 K 柱选择回调。 |
| **`OverviewCard`** | `components/overview-card.tsx:6-` | "分析概览" 卡：当前目标 / K 数量 / AI 状态 / 可渲染标注（**用 `CollapsibleCard` + 4 个 `MetricCard` 拼装**）。 |
| **`Alerts`** | `components/alerts.tsx:5-` | 错误 / 提示 / 数据质量警告 3 种 Alert。 |
| **`AnalysisDetail`** | `components/analysis-detail.tsx:9-` | AI 分析详情（多 section 复合：overlay + 各 trend block）。 |
| **`OverlayTable`** | `components/overlay-table.tsx:4-` | AI 可渲染标注列表。 |
| **`BarSummary`** | `components/bar-summary.tsx:5-` | 单根 K 柱的元数据：开高低收 / 量 / 振幅 / 换手 / 涨幅 / 昨收比较。 |
| **`SummaryList`** | `components/summary-list.tsx:1-` | "适合 / 风险 / 确认 / 失效" 风格列表（4 种 tone 边框）。 |
| **`TrendBlock`** | `components/trend-block.tsx:4-` | 趋势块：state badge + 趋势分 / 置信 / 均线 / 价格结构 / 量能 / 换手。 |
| **`AuctionTab`** + `MetricPill` + `SectionList` + `StyleViewCard` + `AuctionAiPanel` | `components/auction-tab.tsx:308-` | 集合竞价 Tab（含 4 个 helper 子件）。 |
| **`TechnicalIndicatorTab`** | `components/technical-indicator-tab.tsx:87-` | 技术指标 Tab（直接调用 stock-chart 的 `TechnicalIndicatorPanel`，未自实现）。 |
| **`FundFlowTab`** | `components/fund-flow-tab.tsx:10-` | 资金流 Tab（内容略）。 |
| **`IntradayAnalysisDialog`** + `CandleOverlay` | `components/intraday-analysis-dialog.tsx:292-` | 单根 K 柱的分时分析大对话框（含分时蜡烛叠加 + AI 分析）。 |

> **可复用性 / 重复实现**：
> - **`OverviewCard`（app-analysis 内的）** vs **Dashboard 的 `OverviewCard`** —— 是两个完全不同的组件：
>   - Dashboard: 引用 `@/components/overview-card.tsx`（**已抽公共**） — `{title, description}` 简单卡
>   - ApplicationAnalysis: `components/overview-card.tsx` — 多 metric 复合卡（用 `CollapsibleCard` + 4 个 `MetricCard` 拼装）
>   - **建议**：把 application-analysis 内的"复合 metric 卡"沿用 `MetricCard` 拼装，dashboard 的简单卡已抽到公共；或者把 dashboard 的简单卡挪到 `src/components/overview-card.tsx` 通用。
> - **`MetricCard`**（**已抽到 `@/components/metric-card.tsx`**）
> - **`CollapsibleCard`**（**已抽到 `@/components/collapsible-card.tsx`**）
> - **`SummaryList`**（4 tone border-l）跟 `stock-overview/index.tsx:342-365` 的 **`SignalList`** 视觉一致，**重复实现**——可以合并。
> - **`ChartCard`** / **`ChartHeader`** / **`ChartPanel`** / **`IndicatorToolbar`** —— 已经被 `StockDetailDialog` 复用跨 page，**已经跨 view 边界**。

---

### 4.9 Industry / Concept Application (`/stock-overview/industry-application`)

文件: `src/views/industry-application/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `IndustryApplicationPage` (default export) | `index.tsx:112-661` | 行业 / 概念指数的应用面分析：7 个 Tab（总览 / K 线 / AI 方向 / 分析详情 / 分时 / 技术指标 / 资金流）。`fullBleed`。 |
| **`IndustryTargetCard`** (未渲染, `false && ...` 包裹) | `index.tsx:693-906` | 左侧 Watchlist 列表（搜索 / 启停 / 删除 / horizon / 全部刷新）。**当前在页面里没有渲染**，但状态 / handler 全部保留。 |
| **`IndustryAddCard`** (未渲染) | `index.tsx:917-985` | 行业 / 概念代码表（搜索 → 加入）。**当前未渲染**。 |
| **`Group`** | `index.tsx:987-1024` | 行业 / 概念分组按钮小卡。**当前未渲染**。 |
| **`EmptyHint`** | `index.tsx:1026-1034` | 空白态："请从左侧加入一个行业 / 概念"。 |
| *（模块级 helper）* | `index.tsx:54-90` | `DEFAULT_HORIZON` / `eltdxBarToStockBar` / `industryTargetToAppTarget` 数据适配函数 |

子组件（`industry-application/components/`）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`SectorHeatmap`** + `FilterChip` + `SelectBar` | `components/sector-heatmap.tsx:604-` | ECharts 行业 / 概念 treemap 视图（总览 Tab）。 |
| **`IndustryFundFlowTable`** | `components/industry-fund-flow-table.tsx:199-` | 行业资金流表（资金流 Tab）。 |
| **`IndustryTechnicalIndicatorPanel`** + `MetricRow` + `MaRow` + `RangePositionBar` | `components/industry-technical-indicator-panel.tsx:223-` | 行业专用技术指标面板（**注意：阈值按行业校准，跟 stock-chart 的个股版不同**）。 |
| **`NotApplicableCard`** | `components/not-applicable-card.tsx:5-` | "暂不适用"占位卡（AI 方向 / 分析详情 / 分时 等 Tab 用，**独特 Lock 图标 + dashed 内框视觉**保留）。 |
| **`IndustryConstituentsDrawer`** | **已抽到 `@/components/industry-constituents-drawer.tsx`** | 行业 / 概念成分股 drawer（被 `MarketPulsePage` 复用）。 |

> **可复用性**：
> - `NotApplicableCard` 通用空态卡但视觉独特（Lock 图标 + dashed 内框），保留 view-local。
> - `IndustryConstituentsDrawer` 跨 view 复用，**已抽到 `src/components/` 公共目录**。
> - `IndustryTechnicalIndicatorPanel` 是 stock-chart `TechnicalIndicatorPanel` 的行业特化版（阈值不同），**不应该抽到公共**。

---

### 4.10 Self-Selected (`/stock-overview/self-selected`)

文件: `src/views/self-selected/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `SelfSelectedPage` (default export) | `index.tsx:31-349` | 自选股 tab 页：分类 tab + items 网格 + 「+ 加自选」tile。 |
| **`EmptyState`** | `index.tsx:355-374` | 完全没有分类时的空态（带「新建分类」CTA）。 |
| *(子组件)* | 见下表 |  |

子组件（`self-selected/components/`）:

| 组件 | 文件 | 用途 |
| --- | --- | --- |
| **`AddItemTile`** | `components/add-item-tile.tsx:14-` | 网格末尾的虚线占位加号 tile（点击打开 `CreateItemDialog`）。 |
| **`ItemRow`** | `components/item-row.tsx:23-` | 自选股单卡：左侧 accent bar + symbol + market badge + 名称 + 备注；hover 显示「编辑 / 删除」按钮；点击跳到 `application-analysis`。带「已加入应用分析」徽章。 |
| **`CreateGroupDialog`** | `components/create-group-dialog.tsx:23-` | 新建分类对话框（名称 / 描述 / 8 种颜色）。 |
| **`CreateItemDialog`** + `SearchInput` + `ResultsList` | `components/create-item-dialog.tsx:33-` | 加自选两步式弹窗：步骤 1 搜索选股（debounce + 搜索 stock chart），步骤 2 确认 + 备注。 |
| **`ConfirmDialog`** | **已抽到 `@/components/ui/confirm-dialog.tsx`** | 通用确认弹窗：title / description / icon / 确认 / 取消 / destructive / pending。 |

数据: `lib/api.ts` 的 `fetchSelfSelectedGroups` / `fetchSelfSelectedItems` / `createSelfSelectedGroup` / `createSelfSelectedItem` / `deleteSelfSelectedGroup` / `deleteSelfSelectedItem` / `fetchApplicationAnalysisTargets`。

常量: `lib/constants.ts` → `GROUP_COLOR_OPTIONS`, `getGroupColorClasses`, `getMarketClasses`, `getMarketAccentClasses`, `inferMarketFromSymbol`, `TARGET_TYPE_LABEL`。

> **可复用性**：
> - **`ConfirmDialog`** **已抽到 `src/components/ui/confirm-dialog.tsx` 公共目录**。
> - `AddItemTile` 通用「加号 tile」，可考虑抽到 `src/components/add-item-tile.tsx`，但**当前仅 self-selected 用**，暂留 view-local。

---

### 4.11 Stock Review (`/stock-review`)

文件: `src/views/stock-review/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `StockReviewPage` (default export) | `index.tsx:8-35` | 占位 mock 页：与 Dashboard 风格一致（`OverviewCard` 网格 + `NextStepSection`）。 |
| **`OverviewCard`** | 引用 `@/components/overview-card.tsx`（**已抽到公共目录**, 跟 dashboard 合并） | 同 Dashboard 的简单卡。 |
| **`NextStepSection`** | 引用 `stock-review/components/next-step-section.tsx:6-26` | "返回应用总览" 卡片（与 Dashboard 风格相近但内容不同）。 |

> **重复代码**：
> - `dashboard/components/overview-card.tsx` 与 `stock-review/components/overview-card.tsx` **100% 相同** —— **已合并到 `src/components/overview-card.tsx`**。
> - `dashboard/components/next-step-section.tsx` 与 `stock-review/components/next-step-section.tsx` **不同**（Dashboard 给出 3 步链接，StockReview 只给"返回应用总览"）。所以不能简单合并；建议抽到一个 `NextStepSection` 公共组件，props 接受 `steps: StepItem[]`。

---

### 4.12 Settings · Scheduler (`/settings/scheduler`)

文件: `src/views/settings/scheduler/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `SchedulerSettingsPage` (default export) | `index.tsx:476-711` | 调度任务管理：3 张汇总卡 + `JobCard` 列表（每 5s 轮询）。 |
| **`JobCard`** | `index.tsx:100-392` | 单 job 折叠卡：状态 / 启停 / 触发 / 详情 / 启用禁用 / 删除（含 `DeleteJobButton`）。 |
| **`DeleteJobButton`** | `index.tsx:395-454` | "删除" 按钮 + 弹窗确认对话框（自带 Dialog）。 |
| **`Stat`** | `index.tsx:456-474` | icon + label + value 的小卡。 |
| **`SummaryCard`** | `index.tsx:713-738` | 顶部 3 张汇总（注册 / 运行中 / 已启用）。 |

> **可复用性**：
> - `Stat`（icon + label + value）极简 metric，跟 `stock-overview` 的 `MetricTile` / `HeroStat` 是同一类。**建议合并**为一个 `<InfoTile icon label value hint />` 公共组件。
> - `SummaryCard` 跟 `Stat` 视觉很近，可以一起重构。

---

### 4.13 Heatmap Demo (`/heatmap-demo`, `/heatmap-data-debug`)

文件: `src/views/heatmap-demo/index.tsx`

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `HeatmapDemoPage` (export function + default export) | `index.tsx:82-115` | 最小 echarts treemap demo（验证渲染）。 |
| `HeatmapDataDebug` (export function) | `index.tsx:132-250` | 29 风格板块 treemap 调试视图（直连 `STYLE_SECTORS_API`）。 |
| *（模块级 const）* | `index.tsx:17-130` | `BAND_COLORS` / `bandForPct` / `colorForPct` / `formatPct` / `SAMPLE_DATA` / `STYLE_SECTORS_API` / interface `StyleSectorItem` |

> **可复用性**：`BAND_COLORS` / `bandForPct` / `colorForPct` 这套涨跌色阶跟 `mock-market.tsx:168-184` 的 `BAND` 几乎一致（阈值 ±0.5% / ±2% / ±5% / ±10%）—— **重复定义**。可以抽到 `src/lib/heatmap-band.ts` 公共工具。

---

## 5. 复用建议 / 重构清单

下面列出**真正可以抽取到 `src/components/` 公共目录**的组件，以及**重复实现合并**建议。所有重构要求**不丢失功能**：保持现有 props 行为、视觉效果、依赖关系。

### 5.1 优先级 P0（多 page 重复 / 强复用）

| 组件 | 现有位置 | 建议新位置 | 原因 |
| --- | --- | --- | --- |
| **`ConfirmDialog`** | `views/self-selected/components/confirm-dialog.tsx` | `src/components/ui/confirm-dialog.tsx` ✅ **已重构** | 通用确认弹窗，参数化设计良好，已经在 `ItemRow` / `SelfSelectedPage` 多次使用。 |
| **`MetricCard`** | `views/application-analysis/components/metric-card.tsx` | `src/components/metric-card.tsx` ✅ **已重构** | label + value + icon + 3 tone 极简卡，`OverviewCard` 内组合 4 个用。 |
| **`CollapsibleCard`** | `views/application-analysis/components/collapsible-card.tsx` | `src/components/collapsible-card.tsx` ✅ **已重构** | 通用折叠卡（icon / title / description / badge / 折叠）。`OverviewCard` 也基于它。 |
| **`EmptyCard`** | `views/stock-overview/mock-market.tsx:1000-1009` | `src/components/empty-state.tsx`（已建, 跟 NotApplicableCard 视觉差异保留） | 二者视觉与用途高度雷同, 应统一为 `<EmptyState>`。 |
| **`NotApplicableCard`** | `views/industry-application/components/not-applicable-card.tsx` | **保留 view-local**（独特 Lock 图标 + dashed 内框） | 视觉差异是设计意图, 合并会改变外观。 |
| **`OverviewCard` (dashboard / stock-review 简单版)** | `views/dashboard/components/overview-card.tsx` 与 `views/stock-review/components/overview-card.tsx`（**100% 重复**） | `src/components/overview-card.tsx` ✅ **已重构** | 两份文件完全相同，合并到公共目录，view-local 改为 import。 |
| **`InfoTile`** (合并 `Stat` + `SummaryCard` + `MetricTile` + `HeroStat`) | 散落在 `views/settings/scheduler/index.tsx`, `views/stock-overview/index.tsx` | `src/components/info-tile.tsx` | 都是 icon + label + value 形式，统一为一个组件。 |

### 5.2 优先级 P1（跨 view 已复用 / 建议挪位）

| 组件 | 现有位置 | 建议新位置 | 原因 |
| --- | --- | --- | --- |
| **`IndustryConstituentsDrawer`** | `views/industry-application/components/industry-constituents-drawer.tsx` | `src/components/industry-constituents-drawer.tsx` ✅ **已重构** | 已经被 `MarketPulsePage` 直接 import 跨 view 使用，挪到 `src/components/` 让依赖更清晰。 |
| **`AskSection`** | `views/mp4-to-word/components/AskSection.tsx` | `src/components/ask-section.tsx` ✅ **已重构** | 已经在 `Mp4ToWordPage` 和 `Mp4HistoryPage` 都用，挪公共目录。 |
| **`FloatingAskBar`** | `views/mp4-to-word/components/FloatingAskBar.tsx` | `src/components/floating-ask-bar.tsx` ✅ **已重构** | 同上。 |
| **`ReaderModal`** | `views/mp4-to-word/components/ReaderModal.tsx` | `src/components/reader-modal.tsx` ✅ **已重构** | 同上，但目前只 page.tsx 用，挪公共为后续 page 复用准备。 |
| **`ProgressCard`** | `views/mp4-to-word/page.tsx:96-157` | `src/components/progress-card.tsx` | 通用进度卡，mp4-to-word / future task workflow 都能用。 |
| **`SectionHeader`** | `views/stock-overview/index.tsx:249-259` | `src/components/section-header.tsx` | eyebrow + title + description 的卡头，market-pulse / market-overview / 任何 detail 都能用。 |
| **`SignalList`** (stock-overview) | `views/stock-overview/index.tsx:342-365` | 与 application-analysis `SummaryList` 合并 → `src/components/signal-list.tsx` | 两份视觉与 API 几乎相同，合并为 1 个组件。 |
| **`ChartCard`** | `views/application-analysis/components/chart-card.tsx` | （保留 view-local，但暴露给 `IndustryApplicationPage`） | 已经被 `IndustryApplicationPage` 直接 import 跨 view 用了，但实际是 application-analysis 的私有组件。可以挪公共，或者保持现状并加注释。 |
| **`LinkActionRow`** | `views/downloader/components/link-action-row.tsx` | `src/components/link-action-row.tsx` | 链接行 + Copy / Open，其他 page（如 share / 报告导出）也能复用。 |
| **`LoadingState`** | `views/downloader/components/loading-state.tsx` | `src/components/loading-state.tsx` | 通用 loading placeholder。 |

### 5.3 优先级 P2（重复工具 / 死代码清理）

| 项 | 现有位置 | 处理 |
| --- | --- | --- |
| `BAND_COLORS` / `bandForPct` / `colorForPct` 涨跌色阶 | `views/heatmap-demo/index.tsx:17-44` + `views/stock-overview/mock-market.tsx:168-184` | 抽到 `src/lib/heatmap-band.ts`，两处统一引用。 |
| `formatPct` / `formatYi` / `formatAmount` | `views/market/market-pulse.tsx:42-169` + `views/stock-overview/mock-market.tsx:192-203` | 抽到 `src/lib/format.ts`（或合并进 `lib/format.ts` 已有的 downloader/format.ts 同名工具）。✅ **部分已重构**：`views/market/lib/format.ts` 已下沉 market 内部使用的工具。 |
| `StepBar` | `views/mp4-to-word/components/StepBar.tsx` | **已被 page.tsx 取代, 文件已删除** ✅ **已重构** |
| `ChartAreaInteractive`, `DataTable`, `NavDocuments`, `NavSecondary`, `SectionCards`, `SiteHeader` | `src/components/*` | shadcn 模板保留组件，**目前未被引用**。保留即可，不删除。 |
| `drawer.tsx`, `sheet.tsx`, `tooltip.tsx`, `toggle.tsx` UI 基础 | `src/components/ui/*` | 保留，作为后续 sheet / tooltip 基础设施。 |

### 5.4 重复 / 容易混淆组件对照表

| 名字 | 位置 | 说明 |
| --- | --- | --- |
| `OverviewCard` × 3 | dashboard 简单版 / stock-review 简单版（**100% 相同**）/ application-analysis 复合版（**不同**） | 简单两版合并到 `src/components/overview-card.tsx` ✅ **已重构**；application-analysis 复合版改名为 `AnalysisOverviewCard` 或直接用 `CollapsibleCard + MetricCard` 拼装。 |
| `MetricTile` / `HeroStat` / `Stat` / `SummaryCard` | `stock-overview` / `settings/scheduler` | 都是 label + value 极简 metric。合并为 1 个 `InfoTile`，props 区分 "title + hint" / "value + suffix" / "progress"。 |
| `EmptyCard` (mock-market) / `NotApplicableCard` (industry-application) | `stock-overview` / `industry-application` | 同语义, 但视觉差异（NotApplicableCard 独特的 Lock + dashed）是设计意图, 暂不合并；新建通用 `EmptyState` ✅ **已建** 留作未来 page 用。 |
| `SectionHeader` (stock-overview) / `RegimeHero` header (stock-overview) / `PageHeader` (mock-market) | `stock-overview` / `stock-overview/mock-market` | 顶部页头可以统一为 `PageHeader` (eyebrow + title + description + 右侧 action)。 |
| `MarketPulseHeader` / `MarketOverviewCards` / `MarketStyleSectorsSection` / `MarketPlaceholderCards` / `MarketRoadmapNote` | `views/market/components/` | **本次重构新增**: 把 `market-pulse.tsx` 主页内联 UI 全部下沉, 主页从 765 → 318 行。 |

---

## 6. 路由表（汇总）

| Path | Page | 业务子组件汇总 |
| --- | --- | --- |
| `/` | `HomePage` | 7 个 SVG 插画 const |
| `/dashboard` | `DashboardPage` | `OverviewCard` (公共) · `NextStepSection` (dashboard) |
| `/downloader` | `DownloaderPage` | `LinkActionRow` · `LoadingState` |
| `/mp4-to-word` | `Mp4ToWordPage` | `TextSkeletonBlock` · `ProgressCard` · `AskSection` (公共) · `FloatingAskBar` (公共) · `ReaderModal` (公共) |
| `/mp4-to-word/history` | `Mp4HistoryPage` (列表 / 详情) | `MP4HistoryDataTable` · `HistoryContent` · `DetailPanel` · `AskHistoryPanel` · `AskSection` · `FloatingAskBar` |
| `/stock-chart` | `StockChartPage` | `SymbolSearch` · `IndicatorToolbar` · `ChartPanel` · `AuctionPanel` · 17 个 `TechnicalIndicatorPanel` 子件 |
| `/stock-overview` | `StockOverviewPage` | `RegimeHero` · `ActionPlanCard` · `ShanghaiZoneMap` · `CycleMatrix` · `InternalStructurePanel` · `SimilarScenarioPanel` · `IndustryLeadership` + 多 sub-component |
| `/stock-overview/market` | `MarketPulseMock` | `PageHeader` · `SummaryStrip` · `StrongSectors` · `CapitalFlow` · `IndustryRotation` · `RotationTrend` · `IndustryDetailDrawer` + sub |
| `/market/pulse` | `MarketPulsePage` | `MarketPulseHeader` · `MarketOverviewCards` · `MarketStyleSectorsSection` · `MarketPlaceholderCards` · `MarketRoadmapNote` + `IndexKlineDeck` + `MarketPulsePanel` + `IndustryHeatmap` + `LimitEmotionPanel` + `IndustryConstituentsDrawer` |
| `/market/sentiment` | `MarketSentimentPage` | 6 张占位卡 |
| `/stock-overview/application-analysis` | `ApplicationAnalysisPage` | `TargetCard` · `SelectionPanel` · `ChartHeader` · `ChartCard` · `OverviewCard` · `Alerts` · `AnalysisDetail` · `OverlayTable` · `BarSummary` · `SummaryList` · `TrendBlock` · `AuctionTab` · `TechnicalIndicatorTab` · `FundFlowTab` · `IntradayAnalysisDialog` (用 `CollapsibleCard` / `MetricCard` 公共组件) |
| `/stock-overview/industry-application` | `IndustryApplicationPage` | `SectorHeatmap` · `IndustryFundFlowTable` · `IndustryTechnicalIndicatorPanel` · `NotApplicableCard` (view-local, 视觉独特保留) + 隐藏的 `IndustryTargetCard` / `IndustryAddCard` / `Group` / `EmptyHint` |
| `/stock-overview/self-selected` | `SelfSelectedPage` | `AddItemTile` · `ItemRow` · `CreateGroupDialog` · `CreateItemDialog` + `SearchInput` + `ResultsList` · `ConfirmDialog` (公共) |
| `/stock-review` | `StockReviewPage` | `OverviewCard` (公共) · `NextStepSection` (stock-review, 不同 dashboard) |
| `/settings/scheduler` | `SchedulerSettingsPage` | `JobCard` · `DeleteJobButton` · `Stat` · `SummaryCard` |
| `/heatmap-demo` | `HeatmapDemoPage` | 最小 treemap demo |
| `/heatmap-data-debug` | `HeatmapDataDebug` | 29 风格板块 treemap 调试 |

---

## 7. 重构交付记录

### 📅 第一轮：跨 view 复用组件抽取

> 目标: 把多 page 复用的组件 / 重复实现的文件 / 死代码 整理到 `src/components/` 公共目录。

| 动作 | 来源 | 新位置 / 状态 |
| --- | --- | --- |
| ✅ 合并重复 | dashboard `OverviewCard` + stock-review `OverviewCard` 100% 重复 | `src/components/overview-card.tsx` |
| ✅ 抽取 | self-selected `ConfirmDialog` | `src/components/ui/confirm-dialog.tsx` |
| ✅ 抽取 | application-analysis `MetricCard` | `src/components/metric-card.tsx` |
| ✅ 抽取 | application-analysis `CollapsibleCard` | `src/components/collapsible-card.tsx` |
| ✅ 抽取 | industry-application `IndustryConstituentsDrawer`（已跨 view 复用） | `src/components/industry-constituents-drawer.tsx` |
| ✅ 抽取 | mp4-to-word `AskSection`（已跨 page 复用） | `src/components/ask-section.tsx` |
| ✅ 抽取 | mp4-to-word `FloatingAskBar`（已跨 page 复用） | `src/components/floating-ask-bar.tsx` |
| ✅ 抽取 | mp4-to-word `ReaderModal` | `src/components/reader-modal.tsx` |
| ✅ 删除死代码 | mp4-to-word `StepBar`（未被任何 page 引用） | 已删除 |
| ✅ 新增 | 通用 `EmptyState` 组件（未来用） | `src/components/empty-state.tsx` |

**影响文件**：
- 9 个 view-local 文件被删除
- 9 处 import 改为 `@/components/...` 绝对路径
- tsc 编译：0 新增错误（剩余错误全部项目原本就存在）

### 📅 第二轮：`market-pulse.tsx` 内部 UI 下沉

> 目标: 把 `market-pulse.tsx` 主页的内联 UI 全部下沉到 view-local 子组件 + 工具函数到 lib。**不动逻辑，不动布局**。

**主页 765 → 318 行（-58%）**。

| 动作 | 来源 | 新位置 |
| --- | --- | --- |
| ✅ 抽取 | 主页顶部 chip + 标题 + 描述 | `views/market/components/market-pulse-header.tsx` |
| ✅ 抽取 | 大盘成交额 / 主力净流入整段（最复杂, 含 activePoint IIFE） | `views/market/components/market-overview-cards.tsx` |
| ✅ 抽取 | 风格板块涨跌幅整段（含 useMemo 排序） | `views/market/components/market-style-sectors-section.tsx` |
| ✅ 抽取 | 6 张 "待接入" 占位卡 + `PLACEHOLDER_CARDS` 常量 | `views/market/components/market-placeholder-cards.tsx` |
| ✅ 抽取 | "路线"注释 box | `views/market/components/market-roadmap-note.tsx` |
| ✅ 抽取 | `formatYi` / `formatWanShou` / `formatCount` / `moneyTone` / `diffBadgeTone` / `formatReadable` | `views/market/lib/format.ts` |
| ✅ 抽取 | `getMostRecentTradingDayClient` / `isTradeTimeClient` | `views/market/lib/trading-time.ts` |

**影响**：
- 主页只剩 state / handler / mapToIndustryShape / JSX 顶层组装
- `mapToIndustryShape` 留主页（用 `formatReadable` 且与 `loadConstituents` 紧密耦合）
- 底部 `<IndustryConstituentsDrawer>` 留主页（顶层状态消费者）
- `<IndexKlineDeck> <MarketPulsePanel> <IndustryHeatmap> <LimitEmotionPanel>` 4 个跨 view 组件保持原样

**质量保证**：
- tsc 编译：3 个错误 → 2 个错误（**减少 1 个**; 剩余 2 个都是项目原本就存在的）
- 修复了原文件里 `MarketHeatmapResponse` 类型未导出的 `TS2459` 错误
- 逻辑、布局、className、JSX 嵌套、useEffect 依赖、handler 调用顺序 100% 保留

---

## 附录 A：UI 基础组件 import 频率排行（粗略）

按 import 出现次数估算（仅粗略）：

1. `Card` 系列 — 30+ 次（最高频）
2. `Button` — 25+ 次
3. `Badge` — 20+ 次
4. `Tabs` 系列 — 10+ 次
5. `Input` — 8+ 次
6. `Select` 系列 — 8+ 次
7. `Dialog` 系列 — 7+ 次
8. `Separator` — 6+ 次
9. `ScrollArea` — 3+ 次
10. `DropdownMenu` 系列 — 5+ 次
11. `Progress` — 5+ 次
12. `Tooltip` 系列 — 0 次（保留）
13. `Sheet` / `Drawer` — 2 次（drawer.tsx 实际未直接用，用 `vaul` 或 `IndustryConstituentsDrawer` 自管）

## 附录 B：组件依赖关系速查

```
WorkspaceShell
├── AppSidebar
│   ├── TeamSwitcher
│   ├── NavMain
│   ├── NavProjects
│   └── NavUser
├── GlobalCommandTrigger
├── GlobalCommandPalette
└── NotificationRoot (通知根容器)

IndustryConstituentsDrawer  ──>  StockDetailDialog  ──>  ChartPanel + IndicatorToolbar (from stock-chart)
                              ─────────────────────
MarketPulsePage  ──>  IndustryConstituentsDrawer
                    ──>  MarketPulseHeader
                    ──>  MarketOverviewCards
                    ──>  IndexKlineDeck
                    ──>  MarketPulsePanel
                    ──>  MarketStyleSectorsSection
                    ──>  IndustryHeatmap
                    ──>  LimitEmotionPanel
                    ──>  MarketPlaceholderCards
                    ──>  MarketRoadmapNote
                    ──>  IndustryConstituentsDrawer (at bottom)

IndustryApplicationPage  ──>  IndustryConstituentsDrawer + ChartCard (from application-analysis)
ApplicationAnalysisPage  ──>  ChartHeader + CollapsibleCard + MetricCard + OverviewCard (app 版) + Alerts + BarSummary + ...
                          ──>  CollapsibleCard / MetricCard (公共)

Mp4ToWordPage ──>  AskSection, FloatingAskBar, ReaderModal, ProgressCard
Mp4HistoryPage ──>  MP4HistoryDataTable, AskSection, FloatingAskBar

ItemRow (self-selected) ──>  ConfirmDialog (公共)
```
