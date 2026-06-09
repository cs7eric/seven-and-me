# 项目持久化清单 (Persistence Inventory)

> **作用**: 一份"现在磁盘上到底存了什么"的全量清单, 给后续 AI / 工程师接手时快速对账.
> **生成时间**: 2026-06-09
> **数据来源**: `f:\dev-repo\mp4-to-word-new\` 下 7 个根目录 (`uploads / outputs / runtime / models / scheduler / prompt / reference`)
> **统计口径**: 实时扫描磁盘, 6439 文件 / 28.3 GB
> **关联**: `infra/index.md` (结构索引) / `prompt/index.md` (prompt 索引) / `backend/config/settings.py` (路径常量源)

---

## 0. 总览

### 0.1 顶层持久化分布 (按目录)

| 目录 | 类型 | 文件数 | 大小 | 是否进 git | 谁在写 |
| --- | --- | --- | --- | --- | --- |
| [`reference/`](#1-reference--业务数据落盘主目录约-26-gb) | **业务数据落盘主目录** | ~1100 | ~2 GB | 是 (但会很大) | 业务运行时 + scheduler |
| [`runtime/`](#2-runtime--运行时临时dump约-15-gb) | **运行时临时 dump** (LLM raw + .pyc 校验缓存) | 4918 | ~1.5 GB | 忽略 | application-analysis / auction-analysis service |
| [`uploads/`](#3-uploads--mp4上传暂存) | MP4 / wav / mp3 上传原文件 | 393 | ~24 GB | 忽略 | 用户上传 (transcription) |
| [`models/`](#4-models--whisper-模型本地缓存) | Whisper large-v3 模型本地缓存 | 24 | ~3 GB | 忽略 | AI provider 首次加载 |
| [`outputs/`](#5-outputs--转写md导出) | MP4 转写 Markdown 导出 | 0 | 0 | 忽略 | export_service (目前无内容) |
| [`scheduler/`](#6-scheduler--调度器状态json) | 调度器注册表 + 各 job 实时状态 | 6 | <1 MB | 是 | 调度器运行时 |
| [`prompt/`](#7-prompt--ai-prompt-md) | AI prompt 源文件 | 10 | <1 MB | 是 | 人工维护 |

### 0.2 哪些"看上去是配置"但其实是"业务数据"

- `reference/index.json` (顶层索引)
- `reference/stock/index/index.json` (老 stock_chart 索引, 现在 workspaces 用 `workspaces.json`)
- `reference/stock/index/workspaces.json` (个股工作区主索引)
- `reference/stock/index/annotations.json` (annotation 顶层索引, 当前 items 为空)
- `reference/stock/index/stock_chart_config.json` (K 线数据源配置: 分钟 mootdx / 日+周 tencent, 3 个服务器)
- `reference/parse/index/index.json` (MP4 parse 历史索引, 5 条)

### 0.3 时效性一览 (数据保鲜窗口)

| 类别 | 保鲜窗口 | 触发刷新 |
| --- | --- | --- |
| K 线 | 按 period / adjust 维度长期缓存 | 首次读时落盘 |
| 分时 | 按 trade_date 落盘 | 首次读时落盘 |
| 集合竞价 | 按 symbol 落盘, 当日每日覆写 | 首次读时落盘 |
| Annotation / B/S 信号 | 用户手动操作时落盘 | 用户操作 |
| 自选股 | 用户手动 CRUD | 用户操作 |
| Application analysis | 1h 周期 + 盘后 15:30 recent30 | scheduler + 用户触发 |
| Auction AI analysis | 工作日 09:26 每日一次 | scheduler |
| Turnover (换手率) | 工作日盘内 30min + 16:00 | scheduler |
| Market pulse (行情页) | 盘内 10min + 15:30 收盘 + 15:35 成分股 | scheduler |
| Stock universe (全 A 股) | 工作日 17:00 收盘后 | scheduler |
| THS 90 行业成分股 | 每周六 18:00 全量重爬 | scheduler |
| THS 全行业资金 | 5min 内存缓存 + 强制 refresh=1 重爬 | 用户触发 / 自动 |
| MP4 parse 历史 | 永久 | 用户上传 |

---

## 1. `reference/` — 业务数据落盘主目录 (≈ 2 GB)

> **路径常量源**: [`backend/config/settings.py`](file:///f:/dev-repo/mp4-to-word-new/backend/config/settings.py) (按业务域分组, 见 §A-§K).
> **维护说明**: 这是项目**真实状态**的镜像, 所有"持久化 = 业务记忆"都在这里.

### 1.1 顶层索引

- [`reference/index.json`](file:///f:/dev-repo/mp4-to-word-new/reference/index.json) — 顶层 type registry
  - `types.stock_chart` (count=2) → `stock/index/index.json`
  - `types.mp4_parse` (count=5) → `parse/index/index.json`
  - `updated_at`: 2026-06-06T18:10:54

### 1.2 `reference/parse/` — MP4 转写历史 (5 条)

| 路径 | 角色 |
| --- | --- |
| `parse/index/index.json` | MP4 历史顶层索引, items[5] |
| `parse/data/data.json` | 0 字节占位 (没用) |
| `parse/data/mp4-{uuid}.json` | 5 条历史实际数据文件, 每个含 transcript / polished / summary / metadata |

**真实落盘的 5 条**:

| id (uuid 前 8) | 标题 | task_id |
| --- | --- | --- |
| `dd1eac7f` | 养家心法: 短线交易的情绪与仓位智慧 | `dd1eac7f-...` |
| `99695d00` | 短线辨识度与龙头股筛选法 | `99695d00-...` |
| `8c775f20` | 从爆仓到亿级: 我的情绪周期悟道之路 | `8c775f20-...` |
| `90701d42` | 龙头战法深度解析: 连板高度的奥秘 | `90701d42-...` |
| `0ad899e0` | 顶级龙头选手的情绪周期交易模式 | `0ad899e0-...` |

**单条 JSON 结构** (e.g. `mp4-0ad899e0-...json`):
```json
{
  "id": "mp4-0ad899e0-936a-...",
  "type": "mp4_parse",
  "version": 1,
  "title": "...",
  "task": {
    "task_id": "...",
    "status": "done",
    "transcript": "...",      // Whisper 原文转写
    "polished": "...",         // MiniMax 润色结果
    "summary": "...",          // MiniMax 结构化总结
    "metadata": { ... }        // MiniMax 生成的标题 / 分类 / tags
  }
}
```

### 1.3 `reference/stock/` — 个股业务数据 (8 个子域)

#### 1.3.1 `reference/stock/index/` — 工作区索引层

| 文件 | 角色 | 当前内容 |
| --- | --- | --- |
| `index.json` | 老 stock_chart 类型索引 (2 条) | `stock-000001` (平安银行), `index-000001` (上证指数) |
| `workspaces.json` | **当前主工作区索引** (10 条 workspaces) | 见下表 |
| `annotations.json` | 顶层 annotation 索引 (当前 items=[]) | 实际 annotation 按 `<id>-<period>.json` 直接落盘 |
| `stock_chart_config.json` | K 线数据源配置 | 见 §1.3.2 |

**`workspaces.json` 10 条** (按 updated_at 倒序, 反映用户最近活跃的标的):

| id | symbol | name | created_at | updated_at |
| --- | --- | --- | --- | --- |
| `stock-000001` | 000001 | 平安银行 | 2026-05-30 23:25 | **2026-06-07 13:03** |
| `index-000001` | 000001 | 上证指数 | 2026-05-31 00:21 | 2026-06-04 18:57 |
| `stock-600021` | 600021 | 上海电力 | 2026-05-31 01:41 | 2026-06-02 18:37 |
| `stock-600578` | 600578 | 京能电力 | 2026-05-31 11:20 | 2026-05-31 18:07 |
| `stock-000636` | 000636 | 风华高科 | 2026-05-31 11:21 | 2026-05-31 17:39 |
| `stock-600863` | 600863 | 华能蒙电 | 2026-05-31 11:35 | 2026-05-31 11:35 |
| `stock-002617` | 002617 | 露笑科技 | 2026-05-31 11:42 | 2026-06-01 00:15 |
| `stock-600162` | 600162 | 香江控股 | 2026-05-31 14:14 | 2026-05-31 14:25 |
| `stock-600415` | 600415 | 小商品城 | 2026-05-31 17:40 | 2026-05-31 17:40 |

**`stock_chart_config.json`** (K 线数据源路由):
```json
{
  "kline": {
    "minute_provider": "mootdx",          // 分钟 K 走 mootdx
    "daily_provider":  "tencent",          // 日 K 走 tencent
    "weekly_provider": "tencent",          // 周 K 走 tencent
    "fallbacks": {
      "minute": ["mootdx", "sina", "eastmoney"],
      "daily":  ["tencent", "eastmoney"],
      "weekly": ["tencent", "eastmoney"]
    },
    "mootdx": {
      "servers": [
        ["110.41.147.114", 7709],
        ["8.129.13.54",     7709],
        ["124.70.176.52",   7709]
      ],
      "timeout": 10,
      "minute_adjust_mode": "none_only"
    }
  }
}
```

#### 1.3.2 `reference/stock/data/snapshots/` — workspace 数据快照 (14 个)

> 跟 workspaces.json 一一对应 + 几只老标的遗留

文件命名: `stock-{symbol}.json` / `index-{symbol}.json`

| 文件 | 角色 | 示例字段 |
| --- | --- | --- |
| `stock-600415.json` | 工作区配置 (period/adjust/indicators/drawing_tool/show_auction_panel) | `period=5m`, `indicators=[MA,BOLL,MACD,AMOUNT]`, `show_auction_panel=true` |

#### 1.3.3 `reference/stock/data/annotations/` — 标线 / B/S 标记 (7 个)

> 路径规则: `data/annotations/{target_id}-{period}.json`
> 复用规则: B/S 标记走 `period=bs_signals` 跨 period 共享

| 文件 | 角色 | 内容大小 |
| --- | --- | --- |
| `stock-000001-1d.json` | 平安银行 日 K 标线 | - |
| `stock-000001-5m.json` | 平安银行 5 分 K 标线 | - |
| `stock-000001-all.json` | 平安银行 跨周期 | - |
| `stock-600021-bs_signals.json` | 上海电力 B/S 标记 (含 `overlay_type=bs_point` / `side=B` / `source=manual`) | 实际有数据 |
| `stock-600519-1d.json` | 贵州茅台 日 K | - |
| `index-000300-1d.json` | 沪深300 日 K | - |
| `sector-ai-1d.json` | AI 板块 日 K | - |

#### 1.3.4 `reference/stock/cache/` — 行情 / F10 / 涨跌家数 缓存 (按子目录)

##### `cache/klines/` — K 线缓存 (86 个)

文件命名规则: `{target_id}-{period}-{adjust}.json`, period ∈ {`1d`, `1w`, `15m`, `30m`, `60m`, `5m`}, adjust ∈ {`none`, `qfq`, `hfq`}

覆盖标的:
- **个股** (12 个): `000001 / 000636 / 002617 / 600021 / 600162 / 600415 / 600519 / 600578 / 600688 / 600789 / 600863`
- **指数** (12 个): `000001 / 000016 / 000037 / 000300 / 000688 / 000852 / 000905 / 399001 / 399006 / 399986 / 399997 / 932000`
- **板块** (2 个): `sector-ai` (AI 板块)
- **示例条**: `stock-600415-1d-qfq.json` (updated_at=2026-06-08, source=tencent, items 含 trade_date / OHLCV)

##### `cache/auction/` — 集合竞价快照 (15 个)

> 文件命名: `{symbol}.json` (无前缀), `ai.json` 是 AI 板块

个股: `000001 / 000037 / 000055 / 000300 / 000636 / 002617 / 300750 / 600021 / 600162 / 600415 / 600519 / 600578 / 600688 / 600863` + `ai.json`

单条结构 (`600415.json`):
```json
{
  "symbol": "600415",
  "trade_date": "2026-06-09",
  "opening": {
    "time": "09:24:58", "price": 11.15, "volume": 2252, "amount": 2510979.91,
    "matchPrice": 11.15, "unmatchedBuyVolume": 0, "unmatchedSellVolume": 890,
    "gapRate": -0.18, "auctionVolumeRatio": 0.8051, "unmatchedDelta": -890,
    "strengthLabel": "弱势低开"
  }
}
```

##### `cache/intraday/` — 当日分时 (10 个)

文件命名: `stock-{symbol}-{YYYY-MM-DD}.json` / `index-{symbol}-{YYYY-MM-DD}.json`

- `stock-000055-2026-06-04.json`
- `stock-600021-2026-{03-02, 05-18, 05-26, 05-27, 06-02, 06-03, 06-04, 06-05}.json`
- `stock-600415-2026-06-05.json`

单条结构: `trade_date / requested_trade_date / effective_adjust / requested_adjust / timeshare[]`

##### `cache/breadth/` — 涨跌家数 (3 个)

| 文件 | 角色 |
| --- | --- |
| `latest.json` | 最新一份: upCount=2876, downCount=2058, limitUp=96, limitDown=20, totalCount=5058, source=cfi |
| `series.json` | 历史序列 |
| `eltdx_latest.json` | 备用源 (eltdx) |

##### `cache/f10/` — F10 业务 12 个子目录

```
f10/
├── business_composition/    5 个  (000001 / 000055 / 600021 / 600415 / 600688)
├── company_profile/         2 个  (000001 / 600789)
├── concept_sectors_market/  3 个  (x-涨幅-False-0-{80,200}.json + x-涨幅-False-0-100.json)
├── finance_diagnosis/      16 个  (5 股 × 4 项: cznl / hlnl / xjll / yynl, 000001 完整 4 项)
├── finance_report/         15 个  (5 股 × 3 表: lrb / xjllb / zcfzb)
├── governance/              5 个  (wgcl)
├── industry_sectors_market/ 4 个  (i-涨幅-False-0-{3,80,100,200}.json)
├── limit_count/             1 个  (沪深A股.json, 50974 只)
├── profit_forecast/         5 个
├── ranking_detail/          5 个  (scpmdela)
├── sectors_market/         31 个  (c-6-{涨跌幅,成交额}-{True,False}-{0,80,160,240,320,400,480,560}-80.json)
├── stock_info/              5 个  (stock-000001/055/021/415/688.json)
├── stock_score/             5 个  (pf.json)
├── theme_market/            5 个  (200743.json)
├── topics/                  6 个  (000001/034/055/021/415/688.json)
├── turnover/                3 个  (index-000001 / stock-000001 / stock-000055 × 1d-qfq)
├── valuation/               5 个  (200191.json)
```

##### `cache/industry_index_overrides.json` — 行业 index 手动覆盖 (2 条)

```json
[
  { "code": "sh881111", "name": "养殖", "kind": "sector" },
  { "code": "sh881394", "name": "证券", "kind": "sector" }
]
```

#### 1.3.5 `reference/stock/turnover/` — 换手率主数据 (5 个, eltdx 源)

文件命名: `{target_id}.json`

- `index-000001.json` (上证指数)
- `stock-000055.json` (方大集团)
- `stock-600021.json` (上海电力)
- `stock-600415.json` (小商品城, 示例含 `circulating_shares=5483559375` / `source=eltdx` / `entries[trade_date, turnover_rate, volume, amount]`)
- `stock-600688.json` (上海石化)

### 1.4 `reference/application-analysis/` — **个股应用分析 (大头, ≈ 700 MB)**

> 入口: `targets.json` 配置 + scheduler 跑, 落盘 `results/` + `history/` + `auction/` + `snapshots/` + `scheduler.json`

| 路径 | 角色 | 当前量 |
| --- | --- | --- |
| `targets.json` | 应用分析 target 列表 + horizon 配置 | 6 个 target (含 600415, 600021, 000055, 000001, 600688, 600519), `horizon={days:120, segments:4, monthly_keep:6, weekly_keep:12}` |
| `scheduler.json` | scheduler 实时状态 (running / tick_count / last_run per target) | running=true, tick_count=2133, 37 runs, 覆盖 6 个 target |
| `results/` | 最新结果 (一份 / target) | 6 个: `index-000001 / index-000300 / index-399001 / stock-000055 / stock-600021 / stock-600415 / stock-600519 / stock-600688` |
| `history/{target}/YYYYMMDD-HHMMSS.json` | 历史归档 (每次 AI 分析一份) | **523 个** (按 target 拆) |
| `auction/{target}/YYYY-MM-DD.json` | 集合竞价 AI 分析 (每日 1 份) | 7 个, 覆盖 4 个标的 (000055, 600021, 600415, 600688) |
| `snapshots/{target}/YYYY-MM-DD.json` | 盘后 15:30 recent30 快照 | 13 个, 覆盖 5 个 target |

**history 子目录明细**:
- `history/index-000001/` — 37 个 (2026-06-02 ~ 2026-06-04)
- `history/index-000300/` — 20 个 (2026-06-02 ~ 2026-06-03)
- `history/index-399001/` — 21 个 (2026-06-02 ~ 2026-06-03)
- `history/stock-000055/` — 52 个 (2026-06-03 ~ 2026-06-05)
- `history/stock-600021/` — 149 个 (2026-06-02 ~ 2026-06-09, 当前最活跃)
- `history/stock-600415/` — 244 个 (2026-06-03 ~ 2026-06-08, **最热**)
- `history/stock-600519/` — 2 个 (2026-06-02)
- `history/stock-600688/` — 5 个 (2026-06-05)

### 1.5 `reference/industry-application/` — **行业 / 概念应用面分析 (小)**

| 路径 | 角色 | 当前内容 |
| --- | --- | --- |
| `targets.json` | target 配置 + horizon | 4 个: `industry-sh880301` (农副食品), `concept-sh880401` (沪深300概念), `concept-sh880427`, `concept-sh880435`, `horizon={days:120, segments:4}` |
| `results/` | 最新结果 | 3 个: `concept-sh880401 / concept-sh880435 / industry-sh880301` |
| `history/{target}/YYYYMMDD-HHMMSS.json` | 历史归档 | 5 个 |

### 1.6 `reference/self-selected/` — **自选股** (2 个 JSON)

| 文件 | 内容 |
| --- | --- |
| `groups.json` | 2 个分组: "观察" (sort_order=2), "For See" (sort_order=3), 蓝色 |
| `items.json` | 1 个标的: 600415 (小商品城, market=SH), 隶属"观察"组 |

### 1.7 `reference/ths-fund-flow/` — **同花顺全行业主力资金 (hexin-v 破解)**

| 路径 | 角色 | 当前内容 |
| --- | --- | --- |
| `latest.json` | 最新一份, 给前端直接读 | 2026-06-09 18:59, 90 行 (半导体 净额 123.65 亿 居首) |
| `history/2026-06-09.json` | 当日归档 | 同上 |

### 1.8 `reference/ths-industry/` — **同花顺 90 行业 / 成分股 (hexin-v 破解)**

| 路径 | 角色 | 当前量 |
| --- | --- | --- |
| `industry_list.json` | 90 行业 `{byCode: {code: {name, code}}}` | 90 条, 2026-06-07 fetch |
| `industry_info.json` | 每行业 9 项指数数据 | (未列出, 实际存在) |
| `kline/{code}_day.json` | 每行业 975 根 K 线 (akshare) | 1 个示例: `881121_day.json` |
| `constituents/{6 位 code}.json` | 每行业全量成分股 (hexin-v 破解) | **90 个**, 共 **4666 只股** |
| `constituents_index.json` | constituents 顶层索引 | `industryCount=90, totalStocks=4666` |

**constituents/ 90 个 code 分布**:
- `881101 ~ 881182` (前 56 个 = 同花顺标准 56 行业)
- `881263 ~ 881284` (后 24 个 = 同花顺风格 / 概念板块)

**单条示例** (`881102.json`):
```json
{ "ok": true, "code": "881102", "totalPages": 2, "pageRowCounts": [20,16],
  "fetchedAt": "2026-06-09T15:41:31", "rowCount": 36, "rows": [ ...14 列... ] }
```

### 1.9 `reference/stock-universe/` — **A 股全市场每日持久化 (≈ 700 MB, 最大头)**

| 路径 | 角色 | 当前量 |
| --- | --- | --- |
| `index.json` | 版本索引 + latest 指针 | `versions=[{trading_day: 2026-06-06, stock_count: 5530}]` |
| `2026-06-06.json` ~ `2026-06-09.json` | 每日全市场快照 | 4 份, 每份 ≈ 5530 只股, version=2 |
| `_codes.json` | 全 A 股 code 列表 | 1 个 (≈ 5530 条) |
| `_failed_codes.json` | 拉取失败的 code | 1 个 |
| `_progress.json` | 拉取进度状态 | 1 个 |
| `sectors.json` | 行业 / 板块归一总表 | 1 个 |
| `tdx_industry_56.json` | TDX 56 行业映射 | 1 个 |
| `sectors/` | 三大类板块缓存 | `sectors_concepts_2.json` (270 概念) / `sectors_industries_0.json` / `sectors_styles_4.json` / `index.json` |
| `groups/0001.json ~ 0007.json` | 分片拉取结果 (按 code hash 分桶) | 7 份 |
| `_quote_cache/2026-06-05.json` | 行情快照缓存 | 1 份 |
| `_shares_cache/2026-06-{05,08,09}.json` | 股本数据缓存 | 3 份 |
| `qt_fund_flow/{market}{code}.json` | qt.gtimg.cn 个股资金流 (5 只) | `sh600519/601398/688981`, `sz000725/000858` |
| `ths_industry/` | 同花顺行业冗余缓存 (与 `ths-industry/` 重复) | `industry_list.json` + `constituents/{code}.json` 88 个 + `kline/881121_day.json` + `constituents_crawl_state.json` |
| `market_pulse/rotation/YYYY-MM-DD.json` | 行情页 15:30 收盘 Top N 快照 | 3 份: 2026-06-07/08/09 |

**单条 `market_pulse/rotation/2026-06-09.json`**:
- `topN=10`, 包含 `name / changePct / mainNet / inflow / outflow / stockCount / leadingStock / leadingChangePct / rank`
- 半导体 (6.38%, 净额 123.65 亿, 沪硅产业 领涨 20.01%) / 通信设备 (3.30%) / 电池 (3.01%) 等

---

## 2. `runtime/` — 运行时临时 dump (≈ 1.5 GB)

> 仅做 LLM 调试用, **不需要**业务读取; `pycache-verify/` 是 .pyc 校验脚本输出.

### 2.1 `runtime/application-analysis-dumps/` (4868 个)

> `application-analysis` service 每次调 LLM 把 prompt/response 留底

文件命名: `YYYYMMDD-HHMMSS-{target_id}-{name}-{#seg1..#segN}-{raw.json | content.txt}`
- `raw.json` — 发给 LLM 的完整 messages + response
- `content.txt` — 渲染后的纯文本

覆盖标的 (期间): `index-000001 / 000300 / 399001` + `stock-600021 / 600415 / 600519 / 600578 / 000055 / 600688`
时间跨度: `2026-06-02 ~ 2026-06-09`

### 2.2 `runtime/auction-analysis-dumps/` (28 个)

> `auction-analysis` service 每次集合竞价 AI 调用的 dump

文件命名: `YYYYMMDD-HHMMSS-{target_id}-{name}-{raw.json | content.txt}`
覆盖: `stock-000055 / 600021 / 600415 / 600688`, 2026-06-04 ~ 2026-06-09

### 2.3 `runtime/pycache-verify/` (22+ 个)

> pyc 校验缓存, 应该是早期 importlib 校验脚本输出, 可清理.

---

## 3. `uploads/` — MP4 上传暂存 (393 文件 / ≈ 24 GB)

> `UPLOAD_FOLDER = BASE_DIR / 'uploads'` (`backend/config/settings.py`)
> **git 忽略**, 用户上传的 MP4 / wav / mp3 原文件全部暂存这里.
> 没有 index 文件 — 文件名就是 uuid + 原文件名后缀.

文件命名规则: `{uuid}_{原文件名}`

观察到的常见模式:
- `playback-video.mp4` — 抖音视频
- `playback-video_1.mp4` — 抖音视频 (二次抓取)
- `_audio.wav` — 抽出来的音轨
- `_7555519810096859913.mp3` — 抖音直接拉到的 mp3
- `_8_.mp4` / `_9_.mp4` / `_---.mp4` — 含 B 站 / 抖音原始名

---

## 4. `models/` — Whisper 模型本地缓存

```
models/AI-ModelScope/whisper-large-v3/
├── model.fp32-00001-of-00002.safetensors     # 3GB+
├── model.fp32-00002-of-00002.safetensors
├── pytorch_model.fp32-00001-of-00002.bin
├── pytorch_model.fp32-00002-of-00002.bin
├── model.safetensors / model.safetensors.index.fp32.json
├── pytorch_model.bin / pytorch_model.bin.index.fp32.json
├── tokenizer.json / tokenizer_config.json / vocab.json / merges.txt
├── config.json / configuration.json / generation_config.json
├── preprocessor_config.json / normalizer.json
├── added_tokens.json / special_tokens_map.json
├── flax_model.msgpack                         # Flax 权重
├── .mdl / .msc / .mv                          # ModelScope 元数据
└── README.md
```

> **首次加载由 ai_provider_service 触发**, 之后一直复用本地.
> 模型源: `AI-ModelScope/whisper-large-v3`, fp32 双份权重 (safetensors + pytorch bin) 占大头.

---

## 5. `outputs/` — 转写 md 导出

> `OUTPUT_FOLDER = BASE_DIR / 'outputs'`
> **当前为空目录** — `export_service` 在调用时才会写 md 文件, 此次扫描未发现内容.

---

## 6. `scheduler/` — 调度器状态 JSON (6 个, < 1 MB)

> `SCHEDULER_DIR = BASE_DIR / 'scheduler'`

| 文件 | 角色 | 关键状态 (截至 2026-06-09 20:44) |
| --- | --- | --- |
| `jobs.json` | **统一注册表** (8 个 job) | market_pulse_inside / market_pulse_close / market_pulse_constituents / turnover_refresh / stock_universe_refresh / auction_ai_analysis / ths_industry_constituents_weekly / application_analysis |
| `turnover_job.json` | 换手率调度器实时状态 | enabled=true, last_run=2026-06-09 16:00 (success, 2 targets, 3.7s), total_runs=38, total_failures=0 |
| `auction_analysis_job.json` | 集合竞价 AI 调度器状态 | enabled=true, last_run=2026-06-09 09:28 (success, 2 targets, 164s), total_runs=4, total_failures=2 |
| `market_pulse_job.json` | 行情页调度器状态 | lastInsideRefreshAt=2026-06-09 14:59 (85 ticks), lastCloseSnapshot=15:30, lastConstituentsAt=15:35 (90 行业 / 4666 股), topN 中含半导体 6.38% 等 |
| `stock_universe_job.json` | 全 A 股调度器状态 | enabled=true, last_run=2026-06-09 17:30 (success, 30min, file=`2026-06-09.json`), total_runs=4, total_failures=2 |
| `ths_industry_constituents_job.json` | 同花顺 90 行业周调度器 | enabled=true, last_run=2026-06-09 00:45 (success, 90 行业 / 4666 行, 380s), total_runs=1, total_failures=0, schedule=每周六 18:00 |

---

## 7. `prompt/` — AI prompt md (10 个, < 1 MB)

> 完整索引见 [`prompt/index.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/index.md)

| 文件 | 用途 | 加载点 |
| --- | --- | --- |
| `index.md` | 索引 (本节源头) | - |
| `annotation.md` | B/S 标注 / 标线生成 | `polisher.py` |
| `ask_system.md` / `ask_user.md` | MP4 Ask AI 问答系统/用户 prompt | `polisher.ask_about_content` + `transcription.py` |
| `auction_analysis.md` | 集合竞价 AI | `auction_ai_analysis_service._prompt_text()` |
| `metadata_system.md` / `metadata_user.md` | MP4 metadata 生成 | `polisher.metadata` |
| `polish_system.md` | MP4 润色 | `polisher.polish` |
| `short_term_daily.md` | 个股应用分析 (含 horizon/segments 硬约束) | `application_analysis_service._prompt_text()` |
| `summarize_system.md` | MP4 结构化总结 | `polisher.summarize` |

---

## 8. 维护 / 清理建议 (不是任务, 仅记录)

- **`reference/application-analysis/history/`**: 累计 523 个, 单文件 ≈ 1-3 MB, 总量 ≈ 700 MB. 老的 stock-600415 跑得最勤 (244 个). 可考虑按 horizon.monthly_keep / weekly_keep 之外的"额外"清理.
- **`reference/stock-universe/`**: 每日全 A 股快照, 4 份已累积 ≈ 700 MB; `_quote_cache` 旧了可清.
- **`runtime/application-analysis-dumps/`**: 4868 个 LLM 调试 dump, 1 GB+. 仅调试用, 不进业务读取, 可定期清空.
- **`runtime/pycache-verify/`**: 应该是早期 importlib 校验输出, 可全清.
- **`uploads/`**: 24 GB, 上传原文件全留底. 既然 outputs 都导出了 md, 旧 uploads 没用了可清.
- **`guide/`**: `infra/index.md` §5.3 已标 5 个 0 字节废弃文件, 可清.

---

## 9. 索引 / 关联

- 项目结构索引: [`infra/index.md`](file:///f:/dev-repo/mp4-to-word-new/infra/index.md)
- 路径常量源: [`backend/config/settings.py`](file:///f:/dev-repo/mp4-to-word-new/backend/config/settings.py)
- 数据源能力矩阵: [`design/backend/data-source-capability-matrix.md`](file:///f:/dev-repo/mp4-to-word-new/design/backend/data-source-capability-matrix.md)
- Prompt 索引: [`prompt/index.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/index.md)
- 老行情数据源: [`design/backend/stock-data-source.md`](file:///f:/dev-repo/mp4-to-word-new/design/backend/stock-data-source.md)