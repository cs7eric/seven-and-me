<div align="center">

<br />

<img src="frontend/public/favicon.svg" width="76" height="76" alt="Research Workbench" />

# Market Research Workbench

### A-share market intelligence · Stock research workflow · Scheduler operations · AI content processing

<p>
  <a href="#-core-domains">Core Domains</a>
  <span> · </span>
  <a href="#-workspaces">Workspaces</a>
  <span> · </span>
  <a href="#-quick-start">Quick Start</a>
  <span> · </span>
  <a href="#-architecture">Architecture</a>
  <span> · </span>
  <a href="#-design-first-maintenance">Design First</a>
</p>

<p>
  <img alt="React" src="https://img.shields.io/badge/React-19-2563eb?style=for-the-badge&logo=react&logoColor=white" />
  <img alt="Flask" src="https://img.shields.io/badge/Flask-API-111827?style=for-the-badge&logo=flask&logoColor=white" />
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-Research%20Data-0f766e?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img alt="Schedulers" src="https://img.shields.io/badge/Schedulers-Market%20Pipelines-b45309?style=for-the-badge" />
  <img alt="Design First" src="https://img.shields.io/badge/Design--First-Codebase-4338ca?style=for-the-badge" />
</p>

<br />

<table>
  <tr>
    <td align="center"><strong>Market Intelligence</strong><br />overview · pulse · sentiment · heatmap</td>
    <td align="center"><strong>Research Workflow</strong><br />watchlist · K lines · AI analysis · annotations</td>
    <td align="center"><strong>Data Automation</strong><br />scheduler · backfill · Postgres snapshots</td>
    <td align="center"><strong>Content AI</strong><br />media ingest · transcript · summary · history</td>
  </tr>
</table>

<br />

</div>

---

## What This Project Is

This repository is a local-first research cockpit for A-share market observation and stock analysis. It also includes an AI content workflow for turning market videos or audio into structured notes, but the center of gravity is the market research system: data collection, market state dashboards, sentiment factors, stock/sector analysis, watchlists, and scheduler operations.

The project runs as a Flask backend plus a React/Vite frontend. Postgres stores structured snapshots and application data; `reference/`, `runtime/`, `uploads/`, and `outputs/` hold generated artifacts, exported histories, and runtime files.

## 业务模块速览

<table>
  <tr>
    <td width="20%" valign="top">
      <strong>市场总览</strong><br />
      大盘结构、指数区间、风格轮动、相似历史场景。<br />
      <code>/stock-overview</code>
    </td>
    <td width="20%" valign="top">
      <strong>市场脉搏</strong><br />
      成交额、主力资金、涨停情绪、热力图、行业强弱。<br />
      <code>/market/pulse</code>
    </td>
    <td width="20%" valign="top">
      <strong>市场情绪</strong><br />
      九因子情绪指数、风险偏好、赚钱效应、波动风险。<br />
      <code>/market/sentiment</code>
    </td>
    <td width="20%" valign="top">
      <strong>个股研究</strong><br />
      K 线、技术指标、标注、B/S 点、AI 个股分析。<br />
      <code>/stock-chart</code>
    </td>
    <td width="20%" valign="top">
      <strong>自选与目标池</strong><br />
      自选分组、target 同步、应用分析关注列表。<br />
      <code>/stock-overview/self-selected</code>
    </td>
  </tr>
  <tr>
    <td width="20%" valign="top">
      <strong>行业/概念研究</strong><br />
      行业目标、板块 K 线、热力图、资金流、技术面。<br />
      <code>/stock-overview/industry-application</code>
    </td>
    <td width="20%" valign="top">
      <strong>应用分析</strong><br />
      目标维护、竞价数据、近日日线、资金与指标聚合。<br />
      <code>/stock-overview/application-analysis</code>
    </td>
    <td width="20%" valign="top">
      <strong>调度运维</strong><br />
      任务注册、分类、执行历史、手动触发、状态巡检。<br />
      <code>/settings/scheduler</code>
    </td>
    <td width="20%" valign="top">
      <strong>下载器</strong><br />
      解析外部媒体链接，并把结果交给内容处理链路。<br />
      <code>/downloader</code>
    </td>
    <td width="20%" valign="top">
      <strong>内容 AI</strong><br />
      MP4/音频转写、润色、摘要、导出、历史问答。<br />
      <code>/mp4-to-word</code>
    </td>
  </tr>
</table>

## Core Domains

<table>
  <tr>
    <th align="left">Domain</th>
    <th align="left">What It Owns</th>
    <th align="left">Primary Pages</th>
  </tr>
  <tr>
    <td><strong>Market Intelligence</strong></td>
    <td>Market regime, market pulse, sentiment index, heatmaps, limit emotion, style sectors, capital flow.</td>
    <td><code>/stock-overview</code><br /><code>/market/pulse</code><br /><code>/market/sentiment</code></td>
  </tr>
  <tr>
    <td><strong>Stock Research Workflow</strong></td>
    <td>Symbol search, K-line workbench, annotations, B/S points, application analysis targets, self-selected groups.</td>
    <td><code>/stock-chart</code><br /><code>/stock-overview/application-analysis</code><br /><code>/stock-overview/self-selected</code></td>
  </tr>
  <tr>
    <td><strong>Industry / Concept Research</strong></td>
    <td>Industry/concept watchlist, sector heatmap, index K lines, sector technical indicators, fund-flow table.</td>
    <td><code>/stock-overview/industry-application</code><br /><code>/stock-overview/market</code></td>
  </tr>
  <tr>
    <td><strong>Data Automation</strong></td>
    <td>Scheduler registry, job categories, run history, market data refresh, backfill and reconciliation jobs.</td>
    <td><code>/settings/scheduler</code></td>
  </tr>
  <tr>
    <td><strong>Content AI</strong></td>
    <td>Downloader handoff, MP4/audio transcription, AI polish, summary, markdown export, reference history, Ask AI.</td>
    <td><code>/downloader</code><br /><code>/mp4-to-word</code><br /><code>/mp4-to-word/history</code></td>
  </tr>
</table>

## Workspaces

### Market Intelligence

<table>
  <tr>
    <th align="left">Workspace</th>
    <th align="left">Route</th>
    <th align="left">Purpose</th>
  </tr>
  <tr>
    <td><strong>Market Overview</strong></td>
    <td><code>/stock-overview</code></td>
    <td>Composite market regime dashboard with structure, action plan, Shanghai index zones, cycle matrix, style/industry context, and similar scenarios.</td>
  </tr>
  <tr>
    <td><strong>Market Pulse</strong></td>
    <td><code>/market/pulse</code></td>
    <td>Market turnover, main fund flow, index intraday cards, style sectors, heatmap, limit emotion, and manual fund-flow fallback.</td>
  </tr>
  <tr>
    <td><strong>Stock Overview Market Pulse</strong></td>
    <td><code>/stock-overview/market</code></td>
    <td>Postgres-backed industry pulse: strong sectors, capital flow, rotation trends, industry comparison, and drill-down details.</td>
  </tr>
  <tr>
    <td><strong>Market Sentiment</strong></td>
    <td><code>/market/sentiment</code></td>
    <td>Composite market sentiment index plus nine factor cards: risk appetite, breadth, new highs, sector breadth, turnover, limit emotion, volatility, style risk, and profit effect.</td>
  </tr>
</table>

### Stock And Sector Research

<table>
  <tr>
    <th align="left">Workspace</th>
    <th align="left">Route</th>
    <th align="left">Purpose</th>
  </tr>
  <tr>
    <td><strong>Stock Chart</strong></td>
    <td><code>/stock-chart</code></td>
    <td>Search symbols, inspect stock/index/sector K lines, persist workspace state, save annotations, and manage manual B/S points.</td>
  </tr>
  <tr>
    <td><strong>Application Analysis</strong></td>
    <td><code>/stock-overview/application-analysis</code></td>
    <td>Maintain analysis targets, run AI stock analysis, inspect chart context, auction data, technical indicators, fund flow, and recent daily snapshots.</td>
  </tr>
  <tr>
    <td><strong>Self-Selected</strong></td>
    <td><code>/stock-overview/self-selected</code></td>
    <td>Manage custom watchlist tabs and synchronize the system <code>target</code> group with Application Analysis.</td>
  </tr>
  <tr>
    <td><strong>Industry Application</strong></td>
    <td><code>/stock-overview/industry-application</code></td>
    <td>Watch industry/concept targets, inspect index K lines, sector heatmaps, technical indicators, and industry fund-flow data.</td>
  </tr>
</table>

### Operations And Content AI

<table>
  <tr>
    <th align="left">Workspace</th>
    <th align="left">Route</th>
    <th align="left">Purpose</th>
  </tr>
  <tr>
    <td><strong>Scheduler Settings</strong></td>
    <td><code>/settings/scheduler</code></td>
    <td>Inspect registered jobs, categories, daily run stats, job history, live state, and manual operations.</td>
  </tr>
  <tr>
    <td><strong>Downloader</strong></td>
    <td><code>/downloader</code></td>
    <td>Parse media links and hand resolved downloads into the AI content workflow.</td>
  </tr>
  <tr>
    <td><strong>MP4 to Word</strong></td>
    <td><code>/mp4-to-word</code></td>
    <td>Upload or remote-ingest media, then transcribe, polish, summarize, export markdown, and ask follow-up questions.</td>
  </tr>
  <tr>
    <td><strong>MP4 History</strong></td>
    <td><code>/mp4-to-word/history</code></td>
    <td>Browse saved reference records and continue Ask AI on historical outputs.</td>
  </tr>
</table>

## Quick Start

<table>
  <tr>
    <td width="50%">

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.local.example .env
alembic upgrade head
python app.py
```

Backend default:

```text
http://localhost:5000
```

  </td>
  <td width="50%">

### Frontend

```powershell
cd frontend
pnpm install
pnpm dev
```

Vite usually serves:

```text
http://localhost:5173
```

  </td>
  </tr>
</table>

### Environment

```env
MINIMAX_API_KEY=your_api_key_here
MINIMAX_GROUP_ID=your_group_id_here
VITE_API_BASE=http://localhost:5000
VITE_DOWNLOADER_API_BASE=https://downloader-api.bhwa233.com
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:25432/postgres
SQLALCHEMY_ECHO=false
```

## Architecture

```mermaid
flowchart LR
  Browser["React / Vite frontend"] --> API["Flask API blueprints"]
  API --> Services["Service layer"]
  Services --> Repos["Repositories"]
  Repos --> Postgres["Postgres"]

  MarketAdapters["Market adapters<br/>EastMoney / ELTDX / THS / Tencent"] --> Services
  Schedulers["Scheduler services<br/>market data / sentiment / backfill"] --> Services
  AI["AI services<br/>Whisper / MiniMax"] --> Services

  Services --> Reference["reference/ JSON artifacts"]
  Services --> Runtime["runtime / uploads / outputs"]
```

<table>
  <tr>
    <th align="left">Layer</th>
    <th align="left">Path</th>
    <th align="left">Role</th>
  </tr>
  <tr>
    <td><strong>API</strong></td>
    <td><code>backend/api/</code></td>
    <td>Flask blueprints. Request parsing, response shape, light validation.</td>
  </tr>
  <tr>
    <td><strong>Services</strong></td>
    <td><code>backend/services/</code></td>
    <td>Business logic, scheduler jobs, AI workflows, market calculations.</td>
  </tr>
  <tr>
    <td><strong>Repositories</strong></td>
    <td><code>backend/repositories/</code></td>
    <td>Postgres/reference access. Repositories do not own transaction boundaries.</td>
  </tr>
  <tr>
    <td><strong>Market adapters</strong></td>
    <td><code>backend/adapters/market/</code></td>
    <td>External market data sources and provider-specific parsing.</td>
  </tr>
  <tr>
    <td><strong>Frontend views</strong></td>
    <td><code>frontend/src/views/</code></td>
    <td>Business workspaces grouped by domain.</td>
  </tr>
  <tr>
    <td><strong>API client</strong></td>
    <td><code>frontend/src/lib/api.ts</code></td>
    <td>Central fetch layer and response types.</td>
  </tr>
  <tr>
    <td><strong>Design docs</strong></td>
    <td><code>design/</code></td>
    <td>Maintenance entry points for major frontend and backend flows.</td>
  </tr>
</table>

## Design-First Maintenance

<div align="center">

<table>
  <tr>
    <td align="center"><strong>1. Read design</strong><br />Start from the matching document.</td>
    <td align="center"><strong>2. Change code</strong><br />Keep the edit focused.</td>
    <td align="center"><strong>3. Verify</strong><br />Run checks that match the risk.</td>
    <td align="center"><strong>4. Sync design</strong><br />Update docs when behavior changes.</td>
  </tr>
</table>

</div>

Start here:

| Area | Entry |
| --- | --- |
| Frontend design index | [`design/front/index.md`](design/front/index.md) |
| Backend design index | [`design/backend/index.md`](design/backend/index.md) |
| Stock Chart aggregation | [`design/backend/stock-chart-api-aggregation.md`](design/backend/stock-chart-api-aggregation.md) |
| Market overview migration | [`design/backend/market-overview-json-to-postgres.md`](design/backend/market-overview-json-to-postgres.md) |
| Market pulse migration | [`design/backend/market-pulse-postgres-migration.md`](design/backend/market-pulse-postgres-migration.md) |
| Market sentiment pipeline | [`design/backend/market-sentiment-pipeline.md`](design/backend/market-sentiment-pipeline.md) |
| Scheduler runtime | [`design/backend/scheduler-registry-runtime.md`](design/backend/scheduler-registry-runtime.md) |
| Application Analysis target sync | [`design/backend/application-analysis-target-sync.md`](design/backend/application-analysis-target-sync.md) |
| Transcription runtime | [`design/backend/transcription-runtime-flow.md`](design/backend/transcription-runtime-flow.md) |

Important source files also include a short header pointing to their local design entry.

## Project Layout

```text
mp4-to-word-new/
|- backend/                 Flask API, services, repositories, adapters
|- frontend/                React + Vite frontend
|- design/                  Frontend/backend design and maintenance docs
|- alembic/                 Database migrations
|- infra/                   SQL, OpenAPI, persistence notes, seed helpers
|- scheduler/               Job config JSON and scheduler artifacts
|- reference/               Reference JSON data and exported histories
|- runtime/                 Runtime dumps and generated intermediate files
|- scripts/                 Backfill, validation, and data maintenance scripts
|- uploads/                 Uploaded or remote-ingested media
|- outputs/                 Generated exports
|- app.py                   Flask dev entry
`- requirements.txt         Python dependencies
```

## Common Commands

<table>
  <tr>
    <th align="left">Task</th>
    <th align="left">Command</th>
  </tr>
  <tr>
    <td>Start backend</td>
    <td><code>python app.py</code></td>
  </tr>
  <tr>
    <td>Run migrations</td>
    <td><code>alembic upgrade head</code></td>
  </tr>
  <tr>
    <td>Start frontend</td>
    <td><code>cd frontend; pnpm dev</code></td>
  </tr>
  <tr>
    <td>Build frontend</td>
    <td><code>cd frontend; pnpm build</code></td>
  </tr>
  <tr>
    <td>Lint frontend</td>
    <td><code>cd frontend; pnpm lint</code></td>
  </tr>
</table>

## Troubleshooting

<details>
<summary><strong>Market pages show no data</strong></summary>

Check scheduler/backfill state first, then read the matching `design/backend/*.md` document.

</details>

<details>
<summary><strong>Database errors on startup</strong></summary>

Confirm `DATABASE_URL`, start Postgres, then run:

```powershell
alembic upgrade head
```

</details>

<details>
<summary><strong>Frontend cannot reach backend</strong></summary>

Confirm `VITE_API_BASE=http://localhost:5000` and make sure `python app.py` is running.

</details>

<details>
<summary><strong>Scheduler state looks stale</strong></summary>

Check `/settings/scheduler`, inspect the job history dialog, then read `design/backend/scheduler-registry-runtime.md`.

</details>

<details>
<summary><strong>AI polish or summary fails</strong></summary>

Confirm `MINIMAX_API_KEY` and `MINIMAX_GROUP_ID` in `.env`.

</details>

<details>
<summary><strong>MP4 conversion fails</strong></summary>

Confirm `imageio-ffmpeg` is installed and the source file is readable.

</details>

---

<div align="center">

<strong>Market data first. Research workflow second. Content AI as a supporting input path.</strong>

<br />

<sub>Read design · Edit code · Verify · Sync design</sub>

</div>
