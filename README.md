<div align="center">

<br />

<img src="frontend/public/favicon.svg" width="72" height="72" alt="MP4 to Word New" />

# MP4 to Word New

### AI transcription workspace · A-share market analysis console · Design-first codebase

<p>
  <a href="#-quick-start">Quick Start</a>
  <span> · </span>
  <a href="#-product-map">Product Map</a>
  <span> · </span>
  <a href="#-architecture">Architecture</a>
  <span> · </span>
  <a href="#-design-first-maintenance">Design First</a>
</p>

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-111827?style=for-the-badge&logo=python&logoColor=white" />
  <img alt="Flask" src="https://img.shields.io/badge/Flask-API-111827?style=for-the-badge&logo=flask&logoColor=white" />
  <img alt="React" src="https://img.shields.io/badge/React-19-2563eb?style=for-the-badge&logo=react&logoColor=white" />
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-Data-0f766e?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img alt="Design First" src="https://img.shields.io/badge/Design--First-Maintenance-b45309?style=for-the-badge" />
</p>

<br />

<table>
  <tr>
    <td align="center"><strong>Media AI</strong><br />Transcribe, polish, summarize, export, Ask AI</td>
    <td align="center"><strong>Market Console</strong><br />K lines, pulse, sentiment, heatmaps, schedulers</td>
    <td align="center"><strong>Design System</strong><br />Every major path points back to a design document</td>
  </tr>
</table>

<br />

</div>

---

## What This Is

`mp4-to-word-new` started as a local MP4 transcription tool and has become a local-first AI research workspace. It combines media understanding, A-share market analysis, watchlist workflows, scheduler operations, and a design-first maintenance system.

The app runs as a Flask backend plus a React/Vite frontend. Postgres stores structured market/application data, while `reference/`, `runtime/`, `uploads/`, and `outputs/` hold generated and historical artifacts.

## Product Map

<table>
  <tr>
    <th align="left">Workspace</th>
    <th align="left">Route</th>
    <th align="left">Purpose</th>
  </tr>
  <tr>
    <td><strong>MP4 to Word</strong></td>
    <td><code>/mp4-to-word</code></td>
    <td>Upload or remote-ingest media, then transcribe, polish, summarize, export, and ask follow-up questions.</td>
  </tr>
  <tr>
    <td><strong>MP4 History</strong></td>
    <td><code>/mp4-to-word/history</code></td>
    <td>Browse saved reference records and continue Ask AI on historical outputs.</td>
  </tr>
  <tr>
    <td><strong>Downloader</strong></td>
    <td><code>/downloader</code></td>
    <td>Parse media links and hand resolved downloads into the transcription workflow.</td>
  </tr>
  <tr>
    <td><strong>Stock Chart</strong></td>
    <td><code>/stock-chart</code></td>
    <td>Search symbols, inspect K lines, persist workspace state, annotate, and manage manual B/S points.</td>
  </tr>
  <tr>
    <td><strong>Application Analysis</strong></td>
    <td><code>/stock-overview/application-analysis</code></td>
    <td>Maintain analysis targets, run AI analysis, inspect chart context, auction data, indicators, and daily snapshots.</td>
  </tr>
  <tr>
    <td><strong>Self-Selected</strong></td>
    <td><code>/stock-overview/self-selected</code></td>
    <td>Manage custom watchlists and synchronize the system <code>target</code> group with Application Analysis.</td>
  </tr>
  <tr>
    <td><strong>Market Overview</strong></td>
    <td><code>/stock-overview</code></td>
    <td>Read the composite market regime dashboard and structural market map.</td>
  </tr>
  <tr>
    <td><strong>Market Pulse</strong></td>
    <td><code>/market/pulse</code></td>
    <td>Track market turnover, fund flow, style sectors, heatmap, and limit emotion.</td>
  </tr>
  <tr>
    <td><strong>Market Sentiment</strong></td>
    <td><code>/market/sentiment</code></td>
    <td>Composite sentiment index plus nine factor cards with historical context.</td>
  </tr>
  <tr>
    <td><strong>Industry Application</strong></td>
    <td><code>/stock-overview/industry-application</code></td>
    <td>Watch industry/concept targets, inspect K lines, heatmaps, and sector-level indicators.</td>
  </tr>
  <tr>
    <td><strong>Scheduler Settings</strong></td>
    <td><code>/settings/scheduler</code></td>
    <td>Inspect registered jobs, categories, run history, and manual operations.</td>
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
  Services --> Reference["reference/ JSON artifacts"]
  Services --> Runtime["runtime / uploads / outputs"]
  Scheduler["Scheduler services"] --> Services
  Market["Market adapters<br/>EastMoney / ELTDX / THS / Tencent"] --> Services
  AI["Whisper / MiniMax"] --> Services
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
    <td><strong>Frontend views</strong></td>
    <td><code>frontend/src/views/</code></td>
    <td>Business pages grouped by domain.</td>
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
| Transcription runtime | [`design/backend/transcription-runtime-flow.md`](design/backend/transcription-runtime-flow.md) |
| MP4 history flow | [`design/backend/mp4-history-reference-flow.md`](design/backend/mp4-history-reference-flow.md) |
| Scheduler runtime | [`design/backend/scheduler-registry-runtime.md`](design/backend/scheduler-registry-runtime.md) |
| Market sentiment pipeline | [`design/backend/market-sentiment-pipeline.md`](design/backend/market-sentiment-pipeline.md) |
| Application Analysis target sync | [`design/backend/application-analysis-target-sync.md`](design/backend/application-analysis-target-sync.md) |

Important source files also include a short header pointing to their local design entry.

## Project Layout

```text
mp4-to-word-new/
├─ backend/                 Flask API, services, repositories, adapters
├─ frontend/                React + Vite frontend
├─ design/                  Frontend/backend design and maintenance docs
├─ alembic/                 Database migrations
├─ infra/                   SQL, OpenAPI, persistence notes, seed helpers
├─ scheduler/               Job config JSON and scheduler artifacts
├─ reference/               Reference JSON data and exported histories
├─ runtime/                 Runtime dumps and generated intermediate files
├─ scripts/                 Backfill, validation, and data maintenance scripts
├─ uploads/                 Uploaded or remote-ingested media
├─ outputs/                 Generated exports
├─ app.py                   Flask dev entry
└─ requirements.txt         Python dependencies
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
<summary><strong>Frontend cannot reach backend</strong></summary>

Confirm `VITE_API_BASE=http://localhost:5000` and make sure `python app.py` is running.

</details>

<details>
<summary><strong>Database errors on startup</strong></summary>

Confirm `DATABASE_URL`, start Postgres, then run:

```powershell
alembic upgrade head
```

</details>

<details>
<summary><strong>MP4 conversion fails</strong></summary>

Confirm `imageio-ffmpeg` is installed and the source file is readable.

</details>

<details>
<summary><strong>AI polish or summary fails</strong></summary>

Confirm `MINIMAX_API_KEY` and `MINIMAX_GROUP_ID` in `.env`.

</details>

<details>
<summary><strong>Market pages show no data</strong></summary>

Check scheduler/backfill state first, then read the matching `design/backend/*.md` document.

</details>

---

<div align="center">

<strong>Change behavior with the design beside you.</strong>

<br />

<sub>Read design · Edit code · Verify · Sync design</sub>

</div>
