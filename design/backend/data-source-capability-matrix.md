# 数据源能力矩阵 (Capability × Source)

> **作用**: 项目所有"能提供给前端的能力"及其背后的数据源实现方式, 一次看清.
> **维护原则**: 任何能力增减 / 数据源替换 / fallback 顺序变化 → **必须同步更新本文档**.
> **关联文档**:
> - 旧 `stock-data-source.md` (历史 K 线 / 分时 / 集合竞价 / 搜索等早期模块)
> - `infra/index.md` §3.2 路由速查
> - `frontend/src/lib/api.ts` 前端调用入口

---

## 0. 阅读顺序建议

如果你是新接触项目 / AI, 想做 **"xx 能力用哪个数据源"** 或 **"想加新能力应该接哪个源"**, 顺序:

1. **先看本文 §2 总览** — 7 类能力, 各家数据源能 / 不能
2. **再翻 §3 详细能力表** — 每类能力的接口 + 数据源 + 字段 + 已知坑
3. 最后看 §4 数据源能力对比 + §5 已知限制 — 决定**新能力该用哪个源**

---

## 1. 数据源清单 (按本项目用得到的)

| 数据源 | 库 / 文件 | 协议 | 限速 / 状态 | 2026-06 封禁情况 |
| --- | --- | --- | --- | --- |
| **eltdx v1.0.2** | `backend/adapters/market/eltdx_adapter.py` | 通达信 TDX 协议 | 内部线程池 | OK (本机 117.147.26.112) |
| **mootdx** | `backend/adapters/market/mootdx_adapter.py` | 通达信 TDX (mock) | 仅做 fallback | OK |
| **东财 push2** (`push2.eastmoney.com`) | `eastmoney.py` | HTTP JSON | 公开 | **IP 全封** (项目里走 push2 全部失败) |
| **东财 quote.eastmoney.com** (网页行情) | `eastmoney.py` | HTTP HTML | 公开 | **IP 全封** (行业板块 86 行 + 成分股全失败) |
| **同花顺 `q.10jqka.com.cn`** (行业详情页) | `ths_industry_service.py` | HTTP HTML (GBK) | 公开 | **IP 全封** (首页 403, 详情页 Nginx forbidden) |
| **同花顺 `basic.10jqka.com.cn`** (302 F10) | 暂无 (只探测过) | HTTP HTML | 公开 | **OK** (返 2.3KB iframe 壳, 缺具体接口) |
| **同花顺 `stockpage.10jqka.com.cn`** (成分股详情) | 暂无 | HTTP HTML | 公开 | 间接 OK (在 q.10jqka 封后已不可用) |
| **akshare 1.18.46** (akshare 同花顺系) | `market_pulse_service.py` 等 | akshare 统一封装 | 公开 | **OK** (走 stockpage/stockpage.10jqka.com.cn 走 static.10jqka.com.cn 等同花顺域) |
| **akshare (东财系)** | (探测过) | 东财 push2 | 公开 | **IP 全封** (stock_zh_a_spot_em / stock_individual_fund_flow_rank 全部失败) |
| **qt.gtimg.cn** (腾讯) | `tencent.py` + 新 `qt_fund_flow_service.py` | HTTP GBK | 公开 | **OK** (单只 240ms, 批量 5 只 172ms) |
| **新浪 `hq.sinajs.cn`** | `sina.py` | HTTP | 公开 | 单股分钟 K 偶尔通, **行业指数日 K 返空** |
| **CFI** | `market_overview_service.py` | HTTP | 公开 | OK (涨跌家数用) |
| **akshare `web.ifzq.gtimg.cn`** | (探测过) | HTTP | 公开 | 行业指数日 K 返空 (K 线协议废) |
| **东财 push2his** (`push2his.eastmoney.com`) | (探测过) | HTTP | 公开 | **IP 全封** (板块 K 线, 资金流 K 线全失败) |
| **WebFetch (本工具内置)** | Trae IDE | 浏览器 | 渲染 JS | OK 但客户端 IP 受同花顺 302 限制 |

**封禁结论**:
- 本项目环境出口 IP 被**同花顺 q.10jqka.com.cn** 和 **东财 push2 系** 全封
- 同花顺 basic / akshare 同花顺域 / qt.gtimg.cn **能用**
- 任何 `*eastmoney.com` / `*q.10jqka.com.cn` 直接 HTTP 调用一律失败

---

## 2. 总览 — 7 大类能力

```
┌─────────────────────────────────────────────────────────────────┐
│  ① 个股行情 (K 线 / 分时 / 集合竞价 / 实时)                       │
│  ② 个股搜索 / meta (搜索 / 名称 / 流通市值等)                     │
│  ③ 个股 F10 (财报 / 估值 / 题材 / 榜单)                            │
│  ④ 主力资金 / 资金流 (个股 + 板块)                                  │
│  ⑤ 行业 (列表 / K 线 / 9 项实时 / 成分股)                         │
│  ⑥ 大盘 / 情绪 (涨跌家数 / 风格 / 阶段)                            │
│  ⑦ MP4 转写 / 润色 / Ask AI (MiniMax 跑)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 一句话总结 (TL;DR)

| 能力 | 主数据源 | 备注 |
| --- | --- | --- |
| 日/周 K | **tencent (qt.gtimg.cn 主接口)** | 通过 `tencent.py` 走 |
| 分钟 K / 当日分时 / 集合竞价 | **eltdx** | TDX 协议本机最快 |
| 搜索 / meta / 涨跌家数 | **akshare** (同花顺域) / CFI / eastmoney (封了) | 见 §3 |
| 行业 (90 行业) 实时 / 资金流 | **akshare 同花顺 `stock_fund_flow_industry`** | 90 行业 |
| 行业 (56 行业 TDX) 指数实时 / K 线 | **eltdx `get_index_codes_all` + `get_quote`** | TDX 8803xx 协议 |
| 行业 (90 行业) K 线 | **akshare `stock_board_industry_index_ths`** | 走 10jqka 同花顺域 |
| 行业 (90 行业) 成分股 | **HTML 爬虫** (qs_industry_service) | IP 封后拿全失败; 单页 20 只 OK |
| 行业轮动 Top N 落盘 | **akshare 同花顺 + 落盘 `reference/.../rotation/{date}.json`** | 每天 15:30 |
| 个股主动买卖净额 (实时) | **qt.gtimg.cn 主接口 88 字段** | 主动买卖 = 外盘 - 内盘 |
| 个股所属板块资金流 (30 天) | **eltdx `f10.theme_market(seed, 200742)`** | **不是该股自身**! 200742 接口对个股只能返回其所属板块 |
| 大盘 / 风格 / 阶段 | **akshare + CFI + eltdx** | `market_overview_service` 拼装 |
| MP4 转写 / 润色 | **本地 Whisper + MiniMax** | 不算行情数据源, 单独一类 |

---

## 3. 详细能力表 (每行: 能力 / 接口 / 数据源 / 字段 / 已知坑)

### 3.1 ① 个股行情

| 能力 | API 路由 | 数据源 (主) | 数据源 (fallback) | 字段口径 | 已知坑 |
| --- | --- | --- | --- | --- | --- |
| **日 K / 周 K** | `GET /api/stock-chart/klines?symbol=&period=1d\|1w` | tencent (`tencent.py`) | eastmoney (封了) | 见 `stock-data-source.md` §4.1 | tencent 1d OK; 1w OK |
| **分钟 K** | `GET /api/stock-chart/klines?period=1\|5\|15\|30\|60\|120m` | **eltdx** | mootdx / sina / eastmoney | 同上 | 限 1/5/15/30/60/120 |
| **当日分时** | `GET /api/stock-chart/intraday?symbol=` | **eltdx `get_history_minute`** | 1m bars 构造 | 240 根 / 当日 | — |
| **集合竞价** | `GET /api/stock-chart/auction?symbol=` | **eltdx `f10.theme_market(seed, 1)`** | — | 9:15-9:25 价格 + 量 | eltdx 内部 phase 分类 |
| **个股基础信息** | `GET /api/stock-chart/stock-meta?symbol=` | eastmoney (封) → **akshare** | tencent | 名称 / 流通市值 / 行业 | — |
| **标线 / B/S** | `GET / PUT /api/stock-chart/annotations[/:id]` | 本地 JSON (`reference/self-selected/`) | — | period 命名空间 `bs_signals` | annotation 复用, 不分 B/S 独立表 |
| **工作区** | `GET / PUT /api/stock-chart/workspace?symbol=` | 本地 JSON (`reference/workspace/`) | — | period 列表 + 指标 | 同上 |

### 3.2 ② 个股搜索 / meta

| 能力 | API 路由 | 数据源 | 字段 | 已知坑 |
| --- | --- | --- | --- | --- |
| **搜索** | `GET /api/stock-chart/search?q=&limit=` | eastmoney (封) | name / code | **走不了**, 暂用本地 sectors.json 替代 |
| **个股名称** | `GET /api/stock-chart/f10/stock-info?code=` | eltdx `client.get_quote` | 名称 | 实时但 eltdx v1.0.2 名称可能为空 |
| **个股题材** | `GET /api/stock-chart/f10/stock-topics?code=` | eltdx `f10.theme_market` 200743 | 题材列表 (15 行) | — |

### 3.3 ③ 个股 F10

| 能力 | API 路由 | 数据源 | 字段 | 已知坑 |
| --- | --- | --- | --- | --- |
| **公司简介** | `GET /api/stock-chart/f10/company-profile?code=` | eltdx `get_company_profile` | — | — |
| **业务构成** | `GET /api/stock-chart/f10/business-composition?code=` | eltdx | 主营按行业 / 地区 | — |
| **估值** | `GET /api/stock-chart/f10/valuation?code=` | eltdx | PE / PB / PS | — |
| **财报** | `GET /api/stock-chart/f10/finance-report?code=&type=` | eltdx | 三大表 | — |
| **财务诊断** | `GET /api/stock-chart/f10/finance-diagnosis?code=` | eltdx | 多维诊断 | — |
| **综合打分** | `GET /api/stock-chart/f10/stock-score?code=` | eltdx | 总分 + 维度 | — |
| **业绩预告** | `GET /api/stock-chart/f10/profit-forecast?code=` | eltdx | 预告列表 | — |
| **榜单** | `GET /api/stock-chart/f10/ranking-detail?code=&type=` | eltdx | 涨幅 / 资金 / 换手 | — |
| **公司治理** | `GET /api/stock-chart/f10/governance?code=` | eltdx | 股东 / 高管 | — |
| **题材列表** | `GET /api/stock-chart/f10/topics` | eltdx 200743 | 全部题材 | — |
| **题材比较** | `GET /api/stock-chart/f10/topic-compare?codes=` | eltdx | 多题材对比 | — |
| **题材内个股** | `GET /api/stock-chart/f10/topic-stocks?code=` | eltdx | 题材成分股 | — |

### 3.4 ④ 主力资金 / 资金流

| 能力 | API 路由 | 数据源 | 字段 | **重要限制** |
| --- | --- | --- | --- | --- |
| **个股主动买卖净额 (实时)** | `GET /api/stock-chart/qt/fund-flow?code=sh600519` | **qt.gtimg.cn 主接口 88 字段** | 外盘 / 内盘 / 主动净流入手 / 折算金额 | **无"主力/大/中/小单"分单维度**, 主动买卖 = 外盘 - 内盘 |
| **个股批量 (max 80)** | `GET /api/stock-chart/qt/fund-flow-batch?codes=a,b,c` | 同上批量 | 同上 | 一次 200ms |
| **个股所属板块 30 天资金流** | `GET /api/stock-chart/individual/main-fund-flow?code=sh600519&limit=30` | **eltdx 200742** | main_net / large / medium / small | **eltdx 200742 对个股只能拿到"所属板块"30 天资金, 不是该股自身**! 接口返 `sectorName` 字段标明 |
| **板块资金流 (90 行业)** | `GET /api/stock-chart/market-pulse/capital-flow?topN=20` | **akshare `stock_fund_flow_industry` (同花顺域)** | 流入 / 流出 / 净额 / 领涨股 / 公司家数 (单位: 亿) | — |
| **板块涨速 / 涨速榜** | `GET /api/stock-chart/f10/topic-stocks?code=` | eltdx | — | — |
| **涨跌家数 (大盘)** | `GET /api/stock-chart/market-breadth` | CFI / akshare | 涨 / 跌 / 平 / 停 | — |
| **涨跌家数 (历史)** | `GET /api/stock-chart/market-breadth-series` | 本地缓存 `reference/.../breadth/` | 30 天 series | — |

### 3.5 ⑤ 行业 (申万 / 同花顺 / TDX 三套分类)

> **项目里同时维护 3 套行业分类**:
> - **TDX 56 行业**: TDX 8803xx 指数, 走 eltdx
> - **同花顺 90 行业**: 走 akshare / 10jqka
> - **东财 86 行业**: 走东财 (封了, 不再使用)
> 行情页 `/stock-overview/market` 用 **同花顺 90 行业** (真实资金流); 行业 application 页用 **TDX 56 行业** (指数实时 + AI 分析)

| 能力 | API 路由 | 数据源 | 字段 | 已知坑 |
| --- | --- | --- | --- | --- |
| **TDX 56 行业列表 + 9 项实时** | `GET /api/stock-chart/industry-application/tdx-industry-56` | **eltdx** `get_index_codes_all` + `get_quote` | name / code / last_price / change_pct / amount | 8803xx 协议 |
| **TDX 56 行业 K 线** | `GET /api/stock-chart/industry-application/tdx-industry-kline?code=880471&period=day` | **eltdx `bars.get(sh880471)`** | bars[] | **K 线协议错** (`invalid kline date`) — 实际走 akshare 兜底 |
| **TDX 56 行业 K 线 (akshare 兜底)** | 同上 | **akshare `stock_board_industry_index_ths(name)`** | bars[] | OK, 走 10jqka 域 |
| **TDX 56 行业 9 项实时 (单)** | `GET /api/stock-chart/industry-application/tdx-industry-snapshot?code=880471` | eltdx `get_quote` | 9 项 | — |
| **同花顺 90 行业列表** | `GET /api/stock-chart/ths-industry/list` | **akshare `stock_board_industry_name_ths()`** | name + code (881xxx) | 90 行业 |
| **同花顺 90 行业 9 项实时 (全量聚合)** | `GET /api/stock-chart/ths-industry/payload` | **akshare `stock_board_industry_info_ths(name)`** × 90 (8 并发) | 10 项 | 90 × 65ms 串行, 缓存 |
| **同花顺 90 行业 K 线 (单)** | `GET /api/stock-chart/ths-industry/kline?name=半导体&start_date=20260101` | **akshare `stock_board_industry_index_ths(name)`** | bars[] | 5 年 975 bars |
| **同花顺 90 行业 K 线 (name → code 反查)** | 自动 | `ths_industry_service.name_to_code()` | — | — |
| **同花顺 90 行业 成分股 (单行业)** | `GET /api/stock-chart/ths-industry/constituents?name=半导体` | **HTML 爬虫** `q.10jqka.com.cn/thshy/detail/code/{code}/` | 13 列 (code / name / price / 涨跌幅% / 涨跌 / 涨速% / 换手% / 量比 / 振幅% / 成交额 / 流通股 / 流通市值 / 市盈率) | **IP 封后只能拿 1 页 20 只, 完整 9 页 (180 只) 需 Playwright 翻全页** |
| **同花顺 90 行业 成分股 (全量)** | `GET /api/stock-chart/ths-industry/constituents-all?refresh=1` | 同上 | — | 慢 (4 worker, ~5s/行业 + 8s sleep), 落盘到 `constituents/{code}.json` |
| **行业板块行情 (总)** | `GET /api/stock-chart/sectors-market/industry` | eltdx (TDX 56) | 列表 | — |
| **概念板块行情 (总)** | `GET /api/stock-chart/sectors-market/concept` | eltdx | 列表 | — |
| **板块 K 线 (按行业)** | `GET /api/stock-chart/eltdx/industry-index-kline?code=...` | eltdx | bars[] | — |
| **板块 K 线 (按概念)** | `GET /api/stock-chart/eltdx/concept-index-kline?code=...` | eltdx | bars[] | — |
| **指数 K 线 (通用)** | `GET /api/stock-chart/eltdx/index-kline?code=sh000300` | eltdx | bars[] | 沪深指数 |
| **指数代码列表** | `GET /api/stock-chart/eltdx/index-codes` | eltdx `get_index_codes_all` | — | — |
| **涨停股池** | `GET /api/stock-chart/limit-count` | 本地缓存 + 刷新接口 | list | 每天 `turnover` 跑时落盘 |
| **涨停股池刷新** | `POST /api/stock-chart/limit-count/refresh` | eltdx `f10.zt_pool` | — | — |
| **换手率 / 龙虎榜 (F10 业务)** | `GET /api/stock-chart/turnover` | eltdx | 14 个 | 见 `turnover.py` |

### 3.6 ⑥ 大盘 / 情绪 / 风格

| 能力 | API 路由 | 数据源 | 字段 | 已知坑 |
| --- | --- | --- | --- | --- |
| **大盘概览** | `GET /api/stock-chart/market-overview` | CFI + akshare + eltdx 拼装 | 涨跌家数 / 主流资金 / 板块轮动 | 见 `market_overview_service.py` |
| **市场宽度 (单日)** | `GET /api/stock-chart/market-breadth` | CFI / akshare / eastmoney | — | — |
| **市场宽度 (历史)** | `GET /api/stock-chart/market-breadth-series` | 本地缓存 | 30 天 series | — |
| **市场情绪 / 阶段** | (内部 service `market_overview_service`) | akshare + eltdx | 情绪评分 / 阶段 | 不直接暴露路由, 在 `market-overview` payload 里 |
| **行业强度** | (内部 `industry_strength.py`) | TDX 56 行业 + akshare | 行业涨跌幅 / 资金流 | — |
| **风格轮动** | (内部 `style_rotation.py`) | akshare | 价值 / 成长 / 大盘 / 小盘 | — |
| **相似场景** | (内部 `similar_scenarios.py`) | 本地 K 线历史 | K 线相似度 | — |
| **支撑 / 阻力** | (内部 `support_resistance.py`) | K 线 pivot | 价位 | — |
| **行业 application 概览** | `GET /api/stock-chart/industry-application/overview` | eltdx (TDX 56) | — | — |
| **行业 application heatmap** | `GET /api/stock-chart/industry-application/heatmap` | eltdx | grid | — |
| **行业 application results** | `GET /api/stock-chart/industry-application/results[/<target_id>]` | 本地快照 + AI | — | 见 §3.7 AI |

### 3.7 ⑦ AI / 应用分析 / 集合竞价

| 能力 | API 路由 | 数据源 | 字段 / 模型 | 已知坑 |
| --- | --- | --- | --- | --- |
| **个股当日分时 AI 分析** | `POST /api/stock-chart/application-analysis/refresh` | eltdx + MiniMax | `application_analysis_service.py` | target 列表 / 当日结果 |
| **个股 30 天短趋势 AI** | `GET /api/stock-chart/application-analysis/recent30/<target_id>/full` | eltdx 30 天 K + MiniMax | 见 `recent30/*.json` | — |
| **集合竞价 AI 分析** | `POST /api/stock-chart/auction-ai-analysis` | eltdx + MiniMax | `auction_ai_analysis_service.py` | — |
| **行业 application AI** | `POST /api/stock-chart/industry-application/refresh` | eltdx (TDX 56) + MiniMax | `industry_application_service.py` | — |
| **个股综合打分** | `GET /api/stock-chart/feature-summary?symbol=` | eltdx + 自定义 | `feature_summary.py` | — |
| **MP4 转写** | `POST /api/transcribe` / `POST /api/parse-video` | **本地 Whisper** | 长音频 | 跑在本地 CPU / GPU |
| **MP4 润色 / Ask / metadata / summarize** | `POST /api/ask` / `POST /api/reference/mp4-history/<id>/ask` | **MiniMax** | 4 个 prompt | `polisher.py` 单例 |
| **导出 Markdown** | `GET /api/export-markdown/<task_id>` | 本地组装 | — | — |
| **SSE 进度流** | `GET /api/stream/<task_id>` | 内存态 | — | — |

---

## 4. 数据源能力对比

| 数据源 | 协议 | 颗粒度 | 限速 | 落地 | 在本项目的角色 |
| --- | --- | --- | --- | --- | --- |
| **eltdx v1.0.2** | TDX | 个股 / 行业 / 概念 / 指数 / 资金流 | 1-5 req/s | 内存 + 业务 cache | 主力 (60%) |
| **tencent (qt.gtimg.cn)** | HTTP GBK | 个股 / 港股 | 单只 240ms, 批量 5 只 172ms | 磁盘 | 个股资金流 (实时) |
| **akshare 同花顺系** | 走 10jqka 域 | 90 行业 / 资金流 / K 线 / F10 | OK | 内存 | 行业资金流 + 行业 K 线 |
| **akshare 东财系** | 走 push2 | 全 A 股 | **IP 封** | — | 不使用 |
| **CFI** | HTTP | 大盘 | OK | 磁盘 | 涨跌家数 fallback |
| **mootdx** | TDX mock | 个股 K 线 | OK | 内存 | K 线 fallback 一环 |
| **eastmoney push2** | HTTP | 全 A 股 / 板块 / 资金 | **IP 封** | — | 不使用 |
| **q.10jqka.com.cn** | HTML | 行业 / 成分股 | **IP 封** | 磁盘 | 不再使用 (akshare 替代) |
| **basic.10jqka.com.cn** | HTML | F10 | OK 但返 iframe 壳 | — | 探索过, 不可用 |
| **新浪 hq.sinajs.cn** | HTTP | 分钟 K | 偶尔通 | 内存 | minutes K fallback |

---

## 5. 已知限制 (项目级, 2026-06-07 当前)

### 5.1 数据源层

1. **IP 封禁**:
   - `*eastmoney.com` 整系 → push2 / 板块 / 成分股 / 资金流全失败
   - `q.10jqka.com.cn` 整系 → 行业页 / 成分股全 403 / Nginx forbidden
   - **临时方案**: 同花顺 basic 域 + akshare 10jqka 域 + qt.gtimg.cn

2. **eltdx v1.0.2 协议错误**:
   - `bars.get(sh880471, period='day')` 返 `invalid kline date`
   - 行业指数 K 线必须用 **akshare `stock_board_industry_index_ths(name)`** 兜底
   - 个股 200742 资金流对个股 → 只能返"该股所属板块", **不是该股自身** (项目里**所有相关接口都标 `sectorName` 字段**)

3. **qt.gtimg.cn 接口降级**:
   - 2026-06 实测 `ff_<code>` 返 `v_pv_none_match="1"` (下架)
   - 现用主接口 88 字段 part[7] 外盘 / part[8] 内盘 → 主动净流入手 / 折算金额
   - **无主力 / 大 / 中 / 小单分单维度**

4. **akshare 1.18.46 接口缺**:
   - `stock_board_industry_cons_ths` / `stock_board_cons_ths` (行业成分股) — **本版本没有**
   - 行业成分股必须走 HTML 爬虫 (`q.10jqka.com.cn`)
   - `sw_index_third_cons` (申万) — pandas 长度不匹配 bug

5. **数据更新时效**:
   - akshare 同花顺域平均 200-500ms / req
   - eltdx 本地 TDX 50-200ms / req
   - qt.gtimg.cn 单只 240ms / 批量 5 只 172ms

### 5.2 业务层

- **认证未启用**: 所有 API 默认开放 (生产前补)
- **同一时间只能开一个** TDX Client (eltdx v1.0.2 单例)
- **3 套行业分类并存** (TDX 56 / 同花顺 90 / 东财 86 已废), 路由名带前缀 (`tdx-industry-*` vs `ths-industry-*`)

### 5.3 性能 / 缓存

- `reference/` 落盘会很大; scheduler 每天落盘当日 rotation + 90 行业成分股 → 单日 +500KB-2MB
- 行情页 `/stock-overview/market` 走 akshare 90 行业, 一次接口拉三块, 10 分钟自动刷新
- 大盘 / 板块轮动所有接口**没有专门的 batch**, 一次多行业都走 for-loop

---

## 6. 给新接触项目的开发者 / AI 的实操指南

### 6.1 我想加新能力, 应该接哪个源?

```
需要做                  → 推荐数据源          → 备注
─────────────────────────────────────────────────
个股 K 线 / 分时 / 竞价  → eltdx (主)         → 走 backend/adapters/market/eltdx_adapter.py
个股实时资金             → qt.gtimg.cn (主)   → backend/services/stock/f10/qt_fund_flow_service.py
个股 F10                → eltdx              → backend/services/stock/f10/
个股搜索                → 暂用 sectors.json   → eastmoney 封了, 没有真搜索接口
行业 (TDX 56) 实时       → eltdx              → 8803xx 协议, get_quote
行业 (TDX 56) K 线       → akshare ths        → eltdx 协议错, 必须 fallback
行业 (同花顺 90) 全部     → akshare            → stock_board_industry_*_ths 系列
行业 (同花顺 90) 成分股   → HTML 爬虫 + Playwright → IP 封后只能拿首页 20 只
个股主动净流入手 (实时)  → qt.gtimg.cn        → 88 字段 part[7,8]
个股所属板块 30 天资金    → eltdx 200742        → 标 sectorName, 不是该股自身
大盘 / 涨跌家数 / 风格   → akshare + CFI       → backend/services/stock/market_overview/
AI 跑                   → MiniMax            → backend/services/ + prompt/*.md
```

### 6.2 我想加新路由, 应该改哪里?

1. **API 路由**: `backend/api/stock_chart.py` (主力 / 个股 / 行业 / 行情页) 或 `backend/api/stock/f10.py` (F10 业务)
2. **Service**: `backend/services/stock/<area>/`
3. **数据源适配**:
   - 行情: `backend/adapters/market/`
   - 第三方库 (akshare / qstock): `backend/services/stock/f10/<data_source>_service.py`
4. **持久化**: `reference/stock-universe/<area>/` (数据落盘)
5. **scheduler**: `backend/services/scheduler/<area>_scheduler.py` + `backend/bootstrap.py` + `scheduler/<area>_job.json`
6. **前端**:
   - 路由: `frontend/src/router/index.tsx`
   - API 调用: `frontend/src/lib/api.ts` (按 view 分段)
   - 页面: `frontend/src/views/<view>/`
7. **同步文档**:
   - `infra/index.md` §3.2 (路由表) / §4.2 (页面表) / §3.1 (目录树)
   - `design/backend/data-source-capability-matrix.md` 本文 (能力)
   - `design/backend/stock-data-source.md` (旧 K 线协议)
   - `prompt/index.md` (如果动 prompt)

### 6.3 我想换数据源 (例如 AKShare 升版本 / 加个新源)

1. 装新源 → `requirements.txt` 加包
2. 新建 `backend/services/stock/f10/<new>_service.py` (复用 akshare / 同花顺域 / qt 模板)
3. 加 API 路由, 字段**先和老源一致** (前端无感切换)
4. 在 `service` 里加 `provider` 切换 (走 `reference/stock/index/stock_chart_config.json` 的现有模式)
5. **更新本文档 §3 / §4 / §5**

### 6.4 我想加 scheduler 周期任务

1. 新建 `backend/services/scheduler/<area>_scheduler.py`
2. 用 `apscheduler.BackgroundScheduler`, `CronTrigger.from_crontab(...)`
3. 状态写 `scheduler/<area>_job.json`, 注册到 `scheduler/jobs.json`
4. `backend/bootstrap.py` 条件启动 (环境变量 `MINIMAX_*_SCHEDULER_ENABLED=0` 关闭)
5. 在 `infra/index.md` §3.1 / §3.2 / §3.3 同步
6. 在 `frontend/src/views/settings/scheduler/` 加 UI (走 `/api/scheduler/jobs/...` 通用接口)

---

## 7. 维护 checklist (本文档)

- [ ] 任何能力新增 / 删除 / 字段变更 → §3 对应表
- [ ] 任何数据源启用 / 废弃 / 切换 → §1 / §4
- [ ] 任何 IP 封禁 / 解封 → §5.1 (已知限制)
- [ ] 任何路由 / 页面 / service 变动 → 同时更新 `infra/index.md` §3.2 / §4.2
- [ ] 任何 prompt 变动 → 同时更新 `prompt/index.md`
