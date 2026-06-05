# 项目结构 / AI 协作索引

> **作用**：给后续的 AI / 工程师一个项目鸟瞰图。
> **维护原则**：任何目录结构 / 路由 / 模块归属的变动，**必须同步更新本文档**。

---

## 0. 项目一句话

`mp4-to-word` —— **本地 Whisper 转写 + MiniMax 润色** 的 MP4/MOV 音频转写工具；附带 **A 股 / 港股 / 行业 / 主题** 的实时行情 + AI 分析工作台（K 线 / 分时 / 集合竞价 / 应用分析 / F10）。

---

## 1. 顶层目录

| 目录 | 用途 | 谁来改 |
| --- | --- | --- |
| `app.py` | Flask 入口（`create_app()` + `run_dev_server()`） | 启动相关才动 |
| `polisher.py` | **MiniMax 润色器**（polish / summarize / metadata / ask_about_content）；所有 prompt 走 `prompt/*.md` | 改 AI 输出契约时 |
| `transcribe.py` | 老的 Whisper 转写 CLI（保留给 `python transcribe.py <file>`） | 一般不动 |
| `requirements.txt` | Python 依赖 | 加包时 |
| `.env.local.example` | 环境变量模板（API key / Vite base 等） | 加新环境变量时 |
| `backend/` | Flask 后端，按职责分 `api / services / repositories / adapters / config / utils` | 详见 §3 |
| `frontend/` | Vite + React 19 + TS 5 + Tailwind 4 前端 | 详见 §4 |
| `reference/` | **数据落盘目录**（K 线缓存、annotation、workspaces、MP4 parse 历史、application analysis 历史/snapshot）—— git 实际提交，跑久了会很大 | 一般 AI 不改文件，只读 |
| `prompt/` | **所有 AI prompt 维护在这里**，见 [prompt/index.md](../prompt/index.md) | 改 AI 行为时 |
| `infra/` | **本文档所在** —— 项目结构、AI 协作索引 | 改结构时 |
| `design/` | 设计文档（每个 feature 一个 .md） | 写新方案时 |
| `guide/` | 老的开发指南（**已废弃**，文件 0 字节，AI 不要参考） | 保留做历史参考 |
| `scheduler/` | 定时任务状态文件（`jobs.json` / `turnover_job.json` / `auction_analysis_job.json`），代码对应 `backend/services/scheduler/` | 跑调度时自动维护 |
| `static/` | Flask 静态资源 | 一般不动 |
| `templates/index.html` | 根路由模板（被 `backend/api/public.py:index()` 渲染） | 改首页骨架时 |
| `uploads/` | 上传文件暂存（git 忽略） | 自动维护 |
| `outputs/` | 转写导出文件（git 忽略） | 自动维护 |
| `models/` | Whisper 模型本地缓存（git 忽略） | 自动维护 |
| `runtime/` | 任务运行态（git 忽略） | 自动维护 |

---

## 2. 启动 / 入口链路

```
app.py
  └─ backend/app_factory.py:create_app()
       ├─ load_dotenv()  ←  .env.local
       ├─ Flask(CORS, MAX_CONTENT_LENGTH=10GB)
       ├─ backend/config/settings.py:ensure_app_directories()
       └─ backend/bootstrap.py:register_blueprints(app)
            ├─ stock_chart_bp
            ├─ f10_bp
            ├─ create_mp4_history_bp(...)
            ├─ create_transcription_bp(...)
            ├─ create_public_bp(...)
            ├─ create_system_bp(...)
            └─ 4 个 scheduler 条件启动

python transcribe.py <file>  ← 老的 CLI 直跑，独立于 Flask
```

---

## 3. 后端结构 `backend/`

### 3.1 目录树（按职责）

```
backend/
├── app_factory.py          ← Flask app 构造
├── bootstrap.py            ← 注册所有 blueprint + 启动 scheduler
├── runner.py               ← 端口抢占 + 启动 dev server
├── config/
│   └── settings.py         ← 所有路径常量 + ensure_app_directories()
├── adapters/
│   └── market/             ← 行情数据源适配器
│       ├── common.py           类型 / 公共工具
│       ├── eastmoney.py        K 线 + 搜索 + 财务诊断（主力）
│       ├── sina.py             分钟 K 线
│       ├── tencent.py          备用 K 线
│       ├── eltdx_adapter.py    TDX 通道
│       └── mootdx_adapter.py   TDX 通道
├── api/
│   ├── stock_chart.py      ← 主力 blueprint，34 个 /api/stock-chart/* 路由
│   ├── stock/
│   │   └── f10.py          ← F10 财报/估值/题材/榜单 路由
│   ├── mp4_history.py      ← /api/reference/mp4-history/* 工厂函数
│   ├── transcription.py    ← 上传 + SSE 流 + Ask 路由
│   ├── public.py           ← /  /uploads/*  /outputs/*
│   ├── scheduler.py        ← /api/scheduler/* **统一管理 jobs.json 中所有 job（见 §3.2）**
│   └── system.py           ← /api/system/* 健康检查
├── services/
│   ├── ai_provider_service.py  ← 维护 polisher / transcriber 单例
│   ├── export_service.py       ← Markdown 导出
│   ├── mp4_history_service.py  ← 落盘到 reference/parse/
│   ├── task_runtime_service.py ← 内存态任务（transcription）
│   ├── scheduler/
│   │   ├── auction_analysis_scheduler.py
│   │   └── turnover_scheduler.py
│   └── stock/                  ← 股票分析核心
│       ├── application_analysis_service.py  ← 当日分时 AI + 短趋势 30 天
│       ├── application_analysis_scheduler.py
│       ├── application_analysis_store.py
│       ├── auction_ai_analysis_service.py    ← 集合竞价 AI
│       ├── auction_service.py                ← 集合竞价数据
│       ├── kline_service.py                  ← K 线 + 分时 拼装
│       ├── market_data_provider.py           ← 行情聚合
│       ├── market_overview_service.py
│       ├── market_overview_metrics.py
│       ├── search_service.py                 ← 标的搜索
│       ├── config_service.py
│       ├── feature_summary.py                ← 个股综合打分
│       ├── workspace_service.py
│       ├── turnover_repo.py
│       ├── sample_data_service.py
│       ├── analysis_data_reader.py
│       ├── f10/                              ← F10 业务（财报/估值/榜单…）
│       └── market_overview/                  ← 大盘分析（情绪/行业/相似场景…）
├── repositories/               ← 纯文件 IO，无业务
│   ├── reference_index.py      ← 维护 reference/index.json 顶层索引
│   ├── mp4_history_repo.py     ← MP4 parse 历史落盘
│   └── stock/
│       ├── annotation_repo.py  ← 标线 / B/S 标记
│       └── workspace_repo.py   ← 个股工作区（period 列表 + 指标）
└── utils/
    └── json_io.py              ← read_json_file / write_json_file（带原子写）
```

### 3.2 路由速查（`backend/api/`）

#### `stock_chart.py` — 主力（34 个路由）

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/stock-chart/search` | GET | 标的搜索（东财） |
| `/api/stock-chart/klines` | GET | K 线数据 |
| `/api/stock-chart/intraday` | GET | **当日分时 + 分钟 K**（本分时 dialog 用的） |
| `/api/stock-chart/workspace` | GET / PUT | 个股工作区 |
| `/api/stock-chart/annotations` | GET / POST | 标线（B/S 标记也走这里，period 约定为 `bs_signals`） |
| `/api/stock-chart/annotations/<id>` | PUT / DELETE | 标线编辑 |
| `/api/stock-chart/auction` | GET | 集合竞价数据 |
| `/api/stock-chart/feature-summary` | GET | 个股综合打分 |
| `/api/stock-chart/auction-ai-analysis` | POST / GET | 集合竞价 AI 触发 / 拉取 |
| `/api/stock-chart/auction-ai-analysis/history` | GET | AI 历史 |
| `/api/stock-chart/auction-ai-analysis/scheduler[/trigger]` | GET / POST | 调度状态 / 触发 |
| `/api/stock-chart/stock-meta` | GET | 个股基础信息 |
| `/api/stock-chart/application-analysis/targets` | GET / PUT | 应用分析 target 列表 |
| `/api/stock-chart/application-analysis/results[/<id>]` | GET | AI 分析结果 |
| `/api/stock-chart/application-analysis/refresh` | POST | 触发分析 |
| `/api/stock-chart/application-analysis/scheduler[/start/stop]` | GET / POST | 调度状态 / 启停 |
| `/api/stock-chart/market-breadth[-series]` | GET | 涨跌家数 |
| `/api/stock-chart/application-analysis` | POST | **当日分时 AI 逻辑分析**（上一轮定位的） |
| `/api/stock-chart/application-analysis/recent30/...` | GET / POST | 短趋势 30 天 |
| `/api/stock-chart/market-overview` | GET | 大盘概览 |

#### `stock/f10.py` — 24 个路由

F10 全套：`/f10/{stock-info, company-profile, business-composition, valuation, finance-report, finance-diagnosis, stock-score, profit-forecast, ranking-detail, governance, topics, topic-compare, theme-market}` + `/sectors-market/{industry, concept}` + `/limit-count[/refresh]` + `/turnover[/refresh/refresh-all/scheduler/...]` + `/f10/ping`

#### `mp4_history.py`（工厂）

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/reference/mp4-history` | GET / POST | 历史列表 / 保存 |
| `/api/reference/mp4-history/reorder` | POST | 重排 |
| `/api/reference/mp4-history/<id>` | GET / DELETE | 详情 / 删除 |
| `/api/reference/mp4-history/<id>/ask` | POST | **MP4 Ask AI 问答**（上一轮定位的） |

#### `transcription.py`（工厂）

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/transcribe` | POST | 上传文件 |
| `/api/transcribe/remote` | POST | URL 直拉 |
| `/api/task/<id>` | GET | 任务状态 |
| `/api/stream/<id>` | GET | SSE 进度流 |
| `/api/export-markdown/<id>` | GET | 导出 md |
| `/api/ask` | POST | **MP4 Ask AI 问答**（live 任务） |

#### `system.py` / `public.py`

`/api/system/{health, status, model-info}` + `/` `/uploads/*` `/outputs/*`

#### `scheduler.py` — 调度任务统一管理

由 `/settings/scheduler` 页面使用，集中操作 `scheduler/jobs.json` 注册的 job（`turnover_refresh` / `auction_ai_analysis` / `application_analysis`）。

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/scheduler/jobs` | GET | 列出全部 job（注册表 + 各 config + 实时 status） |
| `/api/scheduler/jobs/<id>` | GET | 单个 job 详情（registry + config + live） |
| `/api/scheduler/jobs/<id>/enable` | POST | 翻转 `config.enabled = true`（turnover / auction） |
| `/api/scheduler/jobs/<id>/disable` | POST | 翻转 `config.enabled = false`（turnover / auction） |
| `/api/scheduler/jobs/<id>/trigger` | POST | 手动触发一次（turnover / auction → `trigger_now`；application_analysis → `trigger_all`） |
| `/api/scheduler/jobs/<id>/start` | POST | 启动调度线程 |
| `/api/scheduler/jobs/<id>/stop` | POST | 停止调度线程 |

> application_analysis 没有全局 enabled（靠 per-target `enabled`），所以 `/enable` `/disable` 对它返回 400。

### 3.3 关键约定（改后端必读）

- **数据落盘走 `reference/`**，仓库里看得到的就是真实状态；`gitignore` 不全
- **annotation 复用**：B/S 信号、趋势线、买卖点都走 `annotation_repo`，通过 `overlay_type` 区分（`bs_point` / 自定义），`period` 当命名空间
- **AI 入口三件套**：`polisher.py`（MP4 + 标线 metadata）、`application_analysis_service`（当日分时 + 短趋势）、`auction_ai_analysis_service`（集合竞价）
- **每个 service 自带 `_prompt_text()`**：负责「读 prompt + 追加硬约束段」；改 prompt 时改 `.md`，**别在代码里覆盖**
- **scheduler 状态写在 `scheduler/*.json`**：3 个调度器（`turnover_refresh` / `auction_ai_analysis` / `application_analysis`）启动时读、运行时更新；`application_analysis` 的状态写在 `reference/application-analysis/scheduler.json`，另两个写在 `scheduler/<id>_job.json`
- **认证未启用**：所有 API 默认开放访问，生产环境部署前需要补

---

## 4. 前端结构 `frontend/`

### 4.1 技术栈
  - **Vite 5** + **React 19** + **TypeScript 5** + **Tailwind 4**
  - **字体**：英文优先 Montserrat（regular 400 / bold 700，自托管 .ttf 放在 [`frontend/public/fonts/montserrat/`](file:///f:/dev-repo/mp4-to-word-new/frontend/public/fonts/montserrat/README.md)），中文回退到 PingFang SC / Microsoft YaHei。定义在 `src/index.css` 顶部 + body font-family。
- 路由：[react-router-dom 7](file:///f:/dev-repo/mp4-to-word-new/frontend/src/router/index.tsx)
- 状态：[zustand 5](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/stock-chart/lib/store.ts)（仅 stock-chart 用）
- UI 基础：[radix-ui + shadcn/ui](file:///f:/dev-repo/mp4-to-word-new/frontend/src/components/ui/)（27 个组件）
- 图表：[klinecharts 10-beta2](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json) + Recharts（在分时 dialog 用）
- 拖拽：[dnd-kit](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json)
- 表格：[tanstack/react-table 8](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json)
- 图标：[lucide-react](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json) + [tabler/icons-react](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json)
- 动效：[motion](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json)
- 通知：[sonner](file:///f:/dev-repo/mp4-to-word-new/frontend/src/components/ui/sonner.tsx)

### 4.2 路由 / 页面

| 路径 | 文件 | 角色 |
| --- | --- | --- |
| `/` | [`home.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/home.tsx) | 首页 / 导航 |
| `/dashboard` | [`dashboard/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/dashboard/index.tsx) | **Dashboard 总览页**（MP4 / 市场 / 调度 / 活动等关键指标集中展示，骨架版） |
| `/downloader` | [`downloader/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/downloader/index.tsx) | 视频/音频链接下载 |
| `/mp4-to-word` | [`mp4-to-word/page.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/mp4-to-word/page.tsx) | **MP4 转写 + 润色主流程** |
| `/mp4-to-word/history[/:id]` | [`mp4-to-word/history.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/mp4-to-word/history.tsx) | 历史记录 |
| `/stock-chart` | [`stock-chart/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/stock-chart/index.tsx) | **个股 K 线 + 集合竞价 + 技术指标** |
| `/stock-overview` | [`stock-overview/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/stock-overview/index.tsx) | 大盘概览 |
| `/stock-overview/application-analysis` | [`application-analysis/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/application-analysis/index.tsx) | **个股应用分析**（含分时 dialog） |
| `/stock-review` | [`stock-review/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/stock-review/index.tsx) | 复盘页（**占位**，未实装） |
| `/settings/scheduler` | [`settings/scheduler/index.tsx`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/settings/scheduler/index.tsx) | **调度任务管理页**（统一管理 `scheduler/jobs.json` 中所有 job：实时状态 / 启用禁用 / 启停线程 / 手动触发） |

### 4.3 目录约定

```
frontend/src/
├── App.tsx                    ← 极简壳：<Outlet />
├── main.tsx                   ← 入口：createRoot + RouterProvider
├── index.css                  ← Tailwind 4 + 全局样式
├── layout/                    ← 全站布局相关（独立于 components/，因为是跨 view 的根级关注点）
│   ├── workspace-shell.tsx    ← 所有业务页面的统一外壳（侧边栏 + 面包屑 + main）
│   ├── app-sidebar.tsx        ← 侧边栏骨架（TeamSwitcher + NavMain + NavProjects + NavUser + Rail）
│   ├── team-switcher.tsx      ← 侧边栏顶部 team 切换
│   ├── nav-main.tsx           ← 侧边栏中间 Applications 折叠菜单
│   ├── nav-projects.tsx       ← 侧边栏右侧 Projects 链接
│   └── nav-user.tsx           ← 侧边栏底部 user 头像 + dropdown
├── components/
│   ├── ui/                    ← shadcn/ui 27 个组件（**不要手改**）
│   └── (其他 view 私有业务组件，如 AnimatedList / data-table 等)
├── lib/
│   ├── api.ts                 ← **所有 HTTP 调用入口**，按 view 分段
│   ├── types.ts               ← 跨 view 共享类型（Phase / SSEEvent / QAResponse / PostMetadata）
│   ├── history-types.ts       ← MP4 历史类型
│   ├── html.ts                ← HTML 工具
│   ├── summary-utils.ts       ← Summary 渲染
│   └── utils.ts               ← 通用工具
├── router/index.tsx           ← 路由表
├── views/
│   └── <view>/
│       ├── index.tsx          ← 主组件
│       ├── components/        ← view 私有组件
│       └── lib/               ← view 私有工具 / 类型
├── hooks/                     ← 通用 hooks（目前只有 use-mobile.ts）
├── config/                    ← 侧边栏配置
└── app/dashboard/             ← 老 dashboard 残留（未实装）
```

### 4.4 关键约定（改前端必读）

- **API 调用统一走 `src/lib/api.ts`**，按 view 分组加函数；不要在组件里直接 fetch
- **跨 view 共享类型**放 `lib/types.ts`，view 私有类型放 `views/<view>/lib/types.ts`
- **页面外壳统一用 `<WorkspaceShell sectionLabel="..." pageTitle="...">`**，自带侧边栏 + 面包屑
  - 默认外层 `p-6 gap-6`（外 padding + 子元素间距），view 自己**不要再加外层 padding wrapper**
  - 需要"全屏画布"的页面（如 [`application-analysis`](file:///f:/dev-repo/mp4-to-word-new/frontend/src/views/application-analysis/index.tsx)）传 `fullBleed`，关掉外层 p-6，自己负责 padding
- **新 UI 组件**先看 `components/ui/` 有没有现成的，没有的话查看 shadcn ui 组件库，如果有就执行添加到项目中
- **新页面UI style 要与现有项目一致**
- **shadcn/ui 组件不要手改**（`noUnusedLocals` / `verbatimModuleSyntax` 都开着，改坏一处全报错）
- **路径别名**：`@/*` → `./src/*`（见 `tsconfig.app.json`）

---

## 5. AI 协作清单（后续改项目要参考 / 更新的东西）

### 5.1 改任何代码前，先读这 3 个索引

1. **[`infra/index.md`](file:///f:/dev-repo/mp4-to-word-new/infra/index.md)** ← 本文（项目结构 / 路由 / 模块归属）
2. **[`prompt/index.md`](../prompt/index.md)** ← 所有 AI prompt 的位置、用途、加载点
3. **[`design/`](../design/)** ← 各 feature 的设计文档（如有）

### 5.2 改动触发的连带更新

| 改了什么 | 必更 |
| --- | --- |
| 新增 / 删除 / 改用途的 prompt 文件 | [prompt/index.md](../prompt/index.md) + 加载该 prompt 的代码（保证路径一致） |
| 新增 / 删除 / 重命名目录 | [infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §1 / §3 / §4 |
| 新增 / 删除 / 改路径的 API 路由 | [infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §3.2 |
| 新增 / 删除 / 改路径的页面 | [infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §4.2 + [router/index.tsx](file:///f:/dev-repo/mp4-to-word-new/frontend/src/router/index.tsx) |
| 新增 / 改 schema 的数据类型 | 同时更新 `frontend/src/lib/types.ts` 或对应 `views/<view>/lib/types.ts` + 后端对应 Pydantic model（如果有） |
| 新增 / 删除 scheduler | [infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §3.1 + `backend/bootstrap.py` + `scheduler/*.json` |
| 改 annotation 协议（如新增 overlay_type） | [infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §3.3 + `annotation_repo.py` + 共享 `_PROMPT_DIR` 里的 `period` 约定 |
| 改 AI 输出 schema | 同 prompt 流程（更新 `.md` + 加载点代码的硬约束段） |
| 改行情数据源 | `backend/adapters/market/` + `backend/services/stock/market_data_provider.py` + 新增/修改对应 cache 目录 | 并且更新 design/stock-data-source.md 
| 改前端依赖 | [frontend/package.json](file:///f:/dev-repo/mp4-to-word-new/frontend/package.json) + pnpm-lock.yaml + §4.1 |

### 5.3 几个常踩的坑

- **`guide/` 目录全部 0 字节**，是废弃的，**AI 不要读它当参考**
- **`reference/` 数据落盘会很大**（kline 缓存、application analysis 历史、annotation 都在），AI 读取时**避免一次性扫整个目录**；用 `Grep` / `LS` 限定路径
- **`.codegraph/` 目录**是 IDE 生成的代码图缓存，不是项目代码
- **annotation 复用的 `period` 命名空间**：B/S 标记约定用 `bs_signals`，跨 period 共享；不要给 B/S 单独建表
- **scheduler JSON 状态文件**会被服务进程自动改，**不要手改** `scheduler/*.json`；调度逻辑改在 `backend/services/scheduler/`
- **前后端 prompt / 类型 / 路由不一致**是 90% 报错的来源，改完**先 grep 对侧**

### 5.4 推荐的 AI 工作流

1. 接到任务后，先读 `infra/index.md` + `prompt/index.md` 定位涉及哪些文件
2. 读对应模块的现有代码 + `design/` 下相关文档
3. 改代码 + 同步更新 `infra/index.md` / `prompt/index.md`（如果动了结构）
4. 如果新增 feature / 改协议，**先写 `design/<area>/<feature>.md`** 再动代码
5. 跑通后回头 check：路由对得上？类型对得上？prompt 加载点对得上？落盘目录对得上？

---

## 6. 维护 checklist

- [ ] 任何目录变动 → 更新 §1 / §3 / §4
- [ ] 任何 API / 页面变动 → 更新 §3.2 / §4.2 + 同步路由文件
- [ ] 任何 prompt 变动 → [prompt/index.md](../prompt/index.md) 同步
- [ ] 任何设计文档新增 / 更新 → `design/` 对应目录
- [ ] 任何依赖变动 → `package.json` / `requirements.txt` + §4.1 / §3 提及处
- [ ] 删 `guide/` 残留（5 个 0 字节文件）—— 可选清理任务
