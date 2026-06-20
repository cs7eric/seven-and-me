# TDX hsjday Download Pipeline — Technical Architecture Document

> **Author:** cs7eric  
> **Date:** 2026-06-21  
> **Scope:** `scripts/download_tdx_hsjday.py` + `backend/services/scheduler/tdx_hsjday_download_scheduler.py`

---

## 1. Overview

The TDX hsjday download pipeline is the **data ingestion entry point** for the entire analysis system. It downloads the daily hsjday.zip (~538 MB) from TongDaXin (通达信), extracts binary `.day` files for all A-share stocks (SH/SZ/BJ), verifies data integrity, and atomically replaces the live data directory.

```
https://data.tdx.com.cn/vipdoc/hsjday.zip  (~538 MB)
        │
        ▼  7-step pipeline
reference/tdx/day/hsjday/
  ├── sh/lday/sh000001.day, sh600036.day, ...
  ├── sz/lday/sz000001.day, sz002415.day, ...
  └── bj/lday/bj430047.day, ...
```

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  tdx_hsjday_download_scheduler.py (APScheduler)             │
│  cron: "30 16 * * mon-fri"                                  │
│  guard: is_trading_day (local calendar)                     │
│  timeout: 30 min                                             │
│         │                                                    │
│         │ subprocess python -u download_tdx_hsjday.py        │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         download_tdx_hsjday.py                        │   │
│  │                                                       │   │
│  │  Step 0 → 交易日校验 (Tencent K-line API)              │   │
│  │  Step 1 → 存量数据新鲜度检查                           │   │
│  │  Step 2 → 下载 hsjday.zip                             │   │
│  │  Step 3 → 解压到 hsjday-{date}/ (旧数据不动)           │   │
│  │  Step 4 → 验证 .day 二进制数据 (失败则清理临时目录)     │   │
│  │  Step 5 → 删旧 hsjday → hsjday-{date} 改名 hsjday     │   │
│  │  Step 6 → 清理旧 zip (只保留最近 2 天)                 │   │
│  └──────────────────────────────────────────────────────┘   │
│         │                                                    │
│         │ structured JSON blocks via stdout                   │
│         ▼                                                    │
│  Parse JSON → store to app.scheduler_jobs.extra (JSONB)     │
│  Decision: success / failed / skipped                        │
│  record_run → app.scheduler_job_run_history                  │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Extract to `hsjday-{date}/` first, verify, then rename | Old data is safe until new data passes verification |
| Delete old data ONLY after verify passes | If new data is bad, old data stays intact — no data loss window |
| Tencent K-line API for trading day check | Network-based ground truth; complements local holiday calendar |
| Structured JSON blocks via stdout | Scheduler can parse specific phases without fragile grep |
| Distinct exit codes per phase | Scheduler can route to correct error category |
| Keep only last 2 days of zip files | 538MB each, caps disk usage at ~1GB for downloads |

---

## 3. The 7-Step Pipeline

### Step 0 — 交易日校验

**Purpose:** Verify the target date is actually an A-share trading day.

**Implementation:** `_check_is_trading_day(target_date)`

- Queries `http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,{date},,2,qfq`
- Parses the K-line JSON response
- Compares the latest K-line date with the target date
- If `latest_date < target_date` → not a trading day → **skip with exit 0**

**Output JSON:**
```json
---begin-trading-day-json---
{"ok": true, "latestDataDate": "2026-06-19", "checked": true, "error": null}
---end-trading-day-json---
```

**Skip behavior:** If `ok=false`, the script exits with code **0** (not an error). The scheduler records this as `status: skipped`.

### Step 1 — 存量数据新鲜度检查

**Purpose:** Avoid redundant download if the existing `hsjday/` already covers the target date.

**Implementation:** `_check_existing_data_latest(TDX_TARGET, target_date)`

- Reads `tdx/day/hsjday/sh/lday/sh000001.day`
- Seeks to the last 32-byte record, unpacks the date field (little-endian `uint32`)
- If `existing_date >= target_date` → **skip with exit 0**

**Output JSON:**
```json
---begin-existing-data-json---
{"ok": true, "latestDate": "20260619", "alreadyHaveData": true}
---end-existing-data-json---
```

**Skip behavior:** If `alreadyHaveData=true`, the script exits with code **0**. The scheduler records this as `status: skipped`.

### Step 2 — 下载

**Purpose:** Download `hsjday.zip` from TDX CDN.

**Implementation:** `_download()` → `urlopen` or `_download_via_playwright()`

- First tries `urllib` with sniffing (reads first 4KB to detect JS challenge)
- If JS challenge detected, falls back to Playwright real browser with Range-based chunked download
- `--skip-download` flag allows bypassing for pre-downloaded files

**Output JSON:**
```json
---begin-download-json---
{"ok": true, "fileName": "hsjday.zip", "filePath": "reference/stock/download/2026-06-19/hsjday.zip", "fileBytes": 538123456, "alreadyExisted": false}
---end-download-json---
```

**Failure:** Exit code **2** → scheduler records `[下载失败] ...`

### Step 3 — 解压到带日期后缀的临时目录

**Purpose:** Extract zip to `hsjday-{date}/` (temporary, does NOT touch existing `hsjday/`).

**Flow:**
1. Clean up any existing `hsjday-{date}/`
2. Extract zip to temporary `hsjday_extract_tmp/`
3. Find the actual `hsjday/` root inside (handles both `zip/hsjday/sh/lday/` and `zip/sh/lday/` layouts)
4. `rename(hsjday_extract_tmp/hsjday_root → hsjday-{date})`
5. Clean up temp

**Critical:** Old `hsjday/` is NOT touched yet — if verification fails later, old data stays intact.

**Output JSON:**
```json
---begin-extract-json---
{"ok": true, "totalDayFiles": 5423, "extractedTo": "reference/tdx/day/hsjday-2026-06-19"}
---end-extract-json---
```

**Failure:** Exit code **4** → scheduler records `[解压失败] ...` (old hsjday/ is safe)

### Step 4 — 验证数据

**Purpose:** Confirm the extracted `.day` files (in `hsjday-{date}/`) contain data for the target trading day. **Old `hsjday/` is still untouched.**

**Implementation:** `_verify_download(hsjday_root, target_date)`

- Iterates `sh/sz/bj/lday/` directories
- Samples 9 verification codes (3 per market): `sh000001, sh600036, sh601318, sz000001, sz002415, sz300750, bj430047, bj830799`
- For each sample: reads first & last 32-byte record, unpacks date field
- Check: `last_record_date >= target_date` (as YYYYMMDD integer)

**Output JSON:**
```json
---begin-verify-json---
{
  "ok": true,
  "totalFiles": 5423,
  "totalBytes": 173536,
  "perMarket": {
    "sh": {"files": 2100, "bytes": 67200},
    "sz": {"files": 2800, "bytes": 89600},
    "bj": {"files": 523, "bytes": 16736}
  },
  "samples": [
    {"code": "000001", "market": "sh", "firstDate": "19901219", "lastDate": "20260619", "records": 7000, "bytes": 224000, "ok": true},
    ...
  ],
  "sampleOkCount": 9,
  "sampleTotalCount": 9,
  "targetTradingDay": "2026-06-19",
  "errors": []
}
---end-verify-json---
```

**Failure:** Exit code **3** → scheduler records `[验证失败] ...` (old hsjday/ is preserved, failed hsjday-{date}/ is deleted)

### Step 5 — 原子替换

**Purpose:** Only AFTER verification passes: delete old `hsjday/` and rename `hsjday-{date}` → `hsjday`.

1. `rm -rf tdx/day/hsjday` (old data — verified new data is good, safe to delete)
2. `mv tdx/day/hsjday-{date} → tdx/day/hsjday`

Since both are on the same filesystem, `Path.rename()` is atomic on POSIX and near-atomic on NTFS.

**Warning:** If rename fails after deleting old `hsjday/`, the system is left without data. The scheduler logs this as a critical error.

**Output JSON:**
```json
---begin-rename-json---
{"ok": true, "from": "reference/tdx/day/hsjday-2026-06-19", "to": "reference/tdx/day/hsjday"}
---end-rename-json---
```

**Failure:** Exit code **5** → scheduler records `[替换失败] ...` ⚠️ old data already deleted

### Step 6 — 输出文件列表 + 清理旧 zip

- Outputs `---begin-files-json---` with file samples
- Deletes zip files older than 2 days from `reference/stock/download/`
- Deletes intermediate `hsjday_extracted/` and `hsjday_extract_tmp/` directories

---

## 4. Exit Codes

| Code | Meaning | Scheduler Label |
|------|---------|----------------|
| 0 | Success (data updated) or benign skip | `success` / `skipped` |
| 1 | Argument/usage error | `[运行失败]` |
| 2 | Download failed | `[下载失败]` |
| 3 | Verify failed (no target date data) | `[验证失败]` |
| 4 | Extract failed | `[解压失败]` |
| 5 | Rename failed | `[替换失败]` |

---

## 5. Scheduler Integration

### 5.1 Status Fields (stored in `app.scheduler_jobs.extra` JSONB)

| Field | Type | Description |
|-------|------|-------------|
| `lastZipName` | string | e.g. `"hsjday.zip"` |
| `lastZipPath` | string | Full path to downloaded zip |
| `lastZipBytes` | int | Size of zip file |
| `lastDayFileCount` | int | Number of `.day` files |
| `lastFileSamples` | [string] | First 6 `.day` filenames |
| `lastTradingDayCheck` | dict | Trading day API check result |
| `lastExistingDataDate` | string | Latest date in existing `.day` files |
| `lastAlreadyHaveData` | bool | Whether skip was due to existing data |
| `lastExtractOk` | bool | Whether extraction succeeded |
| `lastRenameOk` | bool | Whether rename succeeded |
| `lastVerifyOk` | bool | Whether verification passed |
| `lastVerifySampleOk` | int | Samples that passed (e.g. 9) |
| `lastVerifySampleTotal` | int | Total samples checked (e.g. 9) |
| `lastVerifyErrors` | [string] | Error details per failed sample |
| `lastSkipped` | bool | Whether this run was skipped |
| `lastSkipReason` | string | Human-readable skip reason |

### 5.2 History Records (`app.scheduler_job_run_history`)

| Status | When |
|--------|------|
| `success` | All 7 steps passed, data updated |
| `failed` | Any step returned non-zero exit code |
| `skipped` | Non-trading day or already have latest data |

### 5.3 Error Message Format

```
[下载失败] RuntimeError: site 走 JS challenge 拦截, 需要 playwright 真实浏览器绕过
[解压失败] zipfile.BadZipFile: File is not a zip file
[验证失败] sh000001: 最后日期=20260618 < 目标日期=20260619; sz000001: 最后日期=20260618 < 目标日期=20260619
[替换失败] OSError: [WinError 5] 拒绝访问
```

---

## 6. Data Flow Diagram

```
                    ┌──────────────────────┐
                    │  Tencent K-line API   │
                    │  (sh000001 daily)     │
                    └──────────┬───────────┘
                               │
                               ▼
  ┌──────────────┐   Step 0: is today a trading day?
  │  Skip (exit 0)│◄──── no ──┤
  └──────────────┘            │ yes
                               ▼
  ┌──────────────┐   Step 1: does existing hsjday/ already
  │  Skip (exit 0)│◄── yes ──  cover target date?
  └──────────────┘            │ no
                               ▼
                    ┌──────────────────────┐
                    │  data.tdx.com.cn      │
                    │  /vipdoc/hsjday.zip   │
                    └──────────┬───────────┘
                               │ ~538 MB
                               ▼
                    ┌──────────────────────┐
                    │  reference/stock/     │
                    │  download/{date}/     │
                    │  hsjday.zip           │
                    └──────────┬───────────┘
                               │ extract (to temp, old data safe)
                               ▼
                    ┌──────────────────────┐
                    │  reference/tdx/day/   │
                    │  hsjday-{date}/       │  ← dated temp (hsjday/ untouched)
                    │  ├── sh/lday/*.day    │
                    │  ├── sz/lday/*.day    │
                    │  └── bj/lday/*.day    │
                    └──────────┬───────────┘
                               │ verify (sample 9 stocks)
                               │ check last record date >= target
                               ▼
                    ┌──────────────────────┐
                    │  verify OK?           │
                    └──────┬───────┬───────┘
                           │ yes   │ no
                           ▼       ▼
                    ┌──────────┐  ┌──────────────────┐
                    │ 1.删除旧  │  │ 清理 hsjday-{date}│
                    │   hsjday/ │  │ 旧 hsjday/ 不动   │
                    │ 2.重命名  │  │ exit 3            │
                    │  -{date}  │  └──────────────────┘
                    │ → hsjday │
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────────────────┐
                    │  reference/tdx/day/   │
                    │  hsjday/              │  ← LIVE data
                    │  (verified, atomic)   │
                    └──────────────────────┘
```

---

## 7. File Locations

| Path | Purpose |
|------|---------|
| `reference/stock/download/{date}/hsjday.zip` | Downloaded zip (kept 2 days for audit, then auto-deleted) |
| `reference/tdx/day/hsjday/` | **LIVE** data directory (consumed by all downstream jobs) |
| `reference/tdx/day/hsjday-{date}/` | Temp directory during pipeline (exists only during Step 3-5) |

---

## 8. `.day` Binary Format

```
32 bytes per record, little-endian

Offset  Size  Type    Field
0       4     uint32  Date (YYYYMMDD as integer, e.g. 20260619)
4       4     uint32  Open (cents, divide by 100)
8       4     uint32  High
12      4     uint32  Low
16      4     uint32  Close
20      4     uint32  Amount (yuan)
24      4     uint32  Volume (shares)
28      4     uint32  Reserved
```

Record count = file_size / 32. Last record is at offset `-32` from EOF.

---

## 9. Scheduler Configuration

```python
DOWNLOAD_CRON = "30 16 * * mon-fri"        # 北京时间 16:30
_JOB_TIMEOUT_SECONDS = 30 * 60             # 30 min max
```

- **Guard 1:** APScheduler `mon-fri` cron
- **Guard 2:** `is_trading_day()` local calendar check (weekends + known holidays)
- **Guard 3:** Step 0 — Tencent K-line API network check
- **Guard 4:** Step 1 — existing data freshness check

---

## 10. CLI Usage

```powershell
# Normal run (today's date)
python scripts/download_tdx_hsjday.py

# Specific date
python scripts/download_tdx_hsjday.py --date 2026-06-19

# Skip trading day check (force run)
python scripts/download_tdx_hsjday.py --skip-trading-day-check

# Skip download (use existing zip)
python scripts/download_tdx_hsjday.py --skip-download

# Dry run (print plan only)
python scripts/download_tdx_hsjday.py --dry-run
```

## 11. Troubleshooting

| Symptom | Check |
|---------|-------|
| `[下载失败] JS challenge` | `pip install playwright && playwright install chromium` |
| `[验证失败] 最后日期 < 目标日期` | TDX hasn't published today's zip yet — wait until 16:30+. Old hsjday/ data is safe. |
| `[跳过] 非交易日` | Check `lastTradingDayCheck` in job status — verify K-line API is reachable |
| `[跳过] 已有最新数据` | `reference/tdx/day/hsjday/sh/lday/sh000001.day` already has target date record |
| `[解压失败]` | Check disk space (~1GB needed for zip + extracted files). Old hsjday/ data is safe. |
| `[替换失败]` | ⚠️ Old data deleted but rename failed — check `hsjday-{date}/` directory manually |
