# 股票数据源 技术方案

> 适用范围：`backend/adapters/market/` + `backend/services/stock/{kline_service, market_data_provider, auction_service, search_service, config_service}.py` + `backend/repositories/stock/workspace_repo.py`
> 维护原则：数据源增减、缓存协议变更、provider 顺序调整，**必须同步更新本文档**。

> **新加的同花顺 90 行业 / akshare / qt.gtimg.cn 等** 新数据源 + 行情页 / F10 / 资金流等新能力已**不只走 `adapters/market/` 单一目录**,
> 而是散落在 `backend/services/stock/f10/<source>_service.py` 和 `backend/services/stock/market_pulse_service.py` 等多个 service.
> 这些能力 + 数据源映射的全景, 见 **[`data-source-capability-matrix.md`](./data-source-capability-matrix.md)**.
> 本文聚焦**老的 K 线 / 分时 / 集合竞价 / 搜索 / meta** 6 个核心能力 (3.1-3.5 节之前) 的协议 / 缓存 / 兜底.

---

## 1. 目标 & 边界

把 A 股 / 港股 / 指数 / 板块 / 集合竞价的行情数据**多源聚合 + 缓存兜底**地喂给前端，**不直接渲染**。
数据源全部走 HTTP / TDX 协议（无数据库），所有状态落到 [`reference/stock/`](file:///f:/dev-repo/mp4-to-word-new/reference/stock/) 下。

---

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│ API 层  backend/api/stock_chart.py                          │
│   /api/stock-chart/{klines,intraday,auction,search,...}     │
│   /api/stock-chart/feature-summary / stock-meta             │
│   /api/stock-chart/market-breadth[-series]                  │
└──────────────┬──────────────────────────────────────────────┘
               │ 调用
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Service / Provider 层                                       │
│   market_data_provider.py   ← 统一协议，封装 fallback       │
│   kline_service.py          ← K线 + 分时 + 聚合             │
│   auction_service.py        ← 集合竞价 phase 构造            │
│   search_service.py         ← 标的搜索 + 行业映射           │
│   config_service.py         ← stock_chart_config.json 读取  │
└──────────────┬──────────────────────────────────────────────┘
               │ 调用
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Adapter 层  backend/adapters/market/                        │
│   common.py            ← 公共：时区、timestamp 解析、量比    │
│   eastmoney.py         ← K线 / 搜索 / 财务 / 涨跌家数 / meta│
│   sina.py              ← 分钟 K 线（1/5/15/30/60/120m）    │
│   tencent.py           ← 日/周 K 线（带前复权 / 后复权）     │
│   eltdx_adapter.py     ← TDX：集合竞价 + 历史分时 + K线     │
│   mootdx_adapter.py    ← TDX：K线（仅做 fallback 链一环）  │
└──────────────┬──────────────────────────────────────────────┘
               │ 网络
               ▼
       [ 东财 / 新浪 / 腾讯 / TDX / CFI / AKShare ]
               │
               │ 兜底读
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Cache  reference/stock/cache/{klines,intraday,auction,breadth}/│
│  workspace_repo.py 维护路径 / 原子读写                      │
└─────────────────────────────────────────────────────────────┘
```

**两套并行入口**：
- `market_data_provider.MarketDataProvider` —— 供其他 service 复用（带 `(data, source_meta)` 元数据）
- `kline_service.resolve_stock_klines / build_intraday_snapshot` —— 直接被 `stock_chart.py` 调用（更重的拼装逻辑）

---

## 3. 数据源能力矩阵

| 数据 | 主力 | fallback 1 | fallback 2 | 兜底 | adapter 函数 |
| --- | --- | --- | --- | --- | --- |
| 日 K `1d` | tencent | eastmoney | —— | cache | `fetch_stock_klines_from_tencent` |
| 周 K `1w` | tencent | eastmoney | —— | cache | `fetch_stock_klines_from_tencent` |
| 分钟 K `1/5/15/30/60/120m` | **eltdx** | mootdx / sina / eastmoney | —— | cache | `fetch_stock_klines_from_eltdx` |
| 当日分时 | eltdx `get_history_minute` | 退化用 1m bars 构造 | —— | cache | `fetch_stock_history_timeshare_from_eltdx` |
| 集合竞价 | **eltdx** | —— | —— | cache | `fetch_stock_auction_from_eltdx` |
| 标的搜索 | eastmoney | —— | —— | —— | `search_stock_chart` |
| 个股 meta | eastmoney | AKShare | tencent | —— | `fetch_stock_meta` |
| 行业指数 | eastmoney search | `_sector_index_symbol_from_industry` 本地表 | —— | —— | `resolve_industry_index` |
| 涨跌家数 | CFI | AKShare | eastmoney | cache | `fetch_market_breadth` |

> **provider 顺序可改**：通过 `reference/stock/index/stock_chart_config.json` 的 `kline.minute_provider / daily_provider / weekly_provider / fallbacks` 动态调整。**默认** 见 [§6 配置](#6-配置)。

---

## 4. 协议 / 数据契约

### 4.1 K 线 bar（统一格式）

所有 adapter 输出的 K 线都规整成下面这个 schema，service 层不再转换：

```python
{
    "timestamp": 1705300800000,        # int，毫秒，北京时间
    "trade_date": "2024-01-15",        # str，YYYY-MM-DD（按北京时间）
    "open": 10.0,
    "close": 10.2,
    "high": 10.3,
    "low": 9.9,
    "volume": 12345.0,                 # float，**手**（A 股 1 手 = 100 股）
    "turnover": 1234567.0,             # float，**元**（成交流水）
    "volume_ratio": 1.23,              # float，量比（`common.build_volume_ratio` 算）
    "turnover_rate": 0.5,              # float，%（部分源可能没有，如 sina 缺）
}
```

### 4.2 当日分时 point

```python
{
    "timestamp": 1705300800000,
    "trade_date": "2024-01-15",
    "time_label": "09:35",             # str，HH:MM
    "price": 10.2,
    "avg_price": 10.18,                # float or None（成交量/额反推）
    "volume": 12345.0,
    "turnover": 1234567.0,
    "turnover_rate": 0.5,              # 来自 K 线；如缺失 None
}
```

构造逻辑：[`kline_service.build_intraday_timeshare`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/kline_service.py) 累加 turnover/volume 反推均价。
**历史分时**（非今日）走 [eltdx.get_history_minute](file:///f:/dev-repo/mp4-to-word-new/backend/adapters/market/eltdx_adapter.py) 单点拉。

### 4.3 个股 meta

```python
{
    "symbol": "000001",
    "name": "平安银行",
    "totalMarketCap": 1.2e11,
    "circMarketCap": 1.1e11,
    "industry": "银行",                 # 行业（东财 f100）
    "capStyle": "large",               # large / mid / small / micro（按流通市值）
    "sectorIndexSymbol": "沪深300",     # str or None
    "sectorIndexName": "沪深300",
    "source": "akshare | tencent | eastmoney",
    "_source": { "source": "...", "stale": false, "dataQuality": "ok" }
}
```

### 4.4 集合竞价 phase snapshot

来源：[`auction_service.build_stock_auction_phase_snapshot`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/auction_service.py) 构造。
结构：开盘 / 收盘两个 phase，包含 `price / volume / amount / matchPrice / unmatchedBuyVolume / unmatchedSellVolume / gapRate / auctionVolumeRatio / unmatchedDelta / strengthLabel / anchorExact / anchorSource / phaseMetrics`。

### 4.5 元数据返回规范

带 fallback 的函数（`_get_*_with_fallback`）**统一返回 `(data, meta)` 元组**：

```python
meta = {
    "source": "eastmoney | cache | none | 某 provider 名",
    "stale": False,                     # True 即来自 cache
    "dataQuality": "ok | stale | error"
}
```

所有 adapter 自己抛 `ValueError` 表达"这一源失败"，**不要** 在 adapter 内做静默 fallback。

---

## 5. 缓存策略

### 5.1 路径

| 用途 | 路径 | 读 | 写 |
| --- | --- | --- | --- |
| K 线 | `reference/stock/cache/klines/{target}-{symbol}-{period}-{adjust}.json` | [`workspace_repo.read_cached_stock_klines`](file:///f:/dev-repo/mp4-to-word-new/backend/repositories/stock/workspace_repo.py) | `stock_chart_klines()` 主流程 |
| 当日分时 | `reference/stock/cache/intraday/{target}-{symbol}-{YYYY-MM-DD}.json` | `kline_service.build_intraday_snapshot` | 同上 |
| 集合竞价 | `reference/stock/cache/auction/{symbol}.json` | 无显式 cache 读取 | `auction_service.fetch_stock_auction` |
| 涨跌家数 | `reference/stock/cache/breadth/latest.json` | `market_data_provider._get_breadth_with_fallback` | 同上（每次 `fetch_market_breadth` 成功后覆盖） |

### 5.2 兜底顺序

```
live 任意 provider 成功 → 返回  meta.stale=False
        ↓ 失败
读 cache（按上面路径）    → 返回  meta.stale=True, dataQuality=stale
        ↓ 也无
返回空 + meta.dataQuality=error
```

### 5.3 持久化工具

读写一律走 [`backend/utils/json_io.py:read_json_file / write_json_file`](file:///f:/dev-repo/mp4-to-word-new/backend/utils/json_io.py) —— 带原子写、缺失返回 `None`。

### 5.4 TODO（已知 cache 缺陷）

- ❌ K 线 cache 写到主流程**没区分 provider**（被 overwrite），导致不同源的差异被覆盖；建议 cache 文件名带 provider 后缀
- ❌ 当日分时 cache 命中条件是"指定 trade_date + period 子集"才算，periods 参数变化时不会失效
- ❌ `reference/stock/cache/breadth/latest.json` 没有按交易日分文件，长时间累计易读到陈旧数据

---

## 6. 配置

### 6.1 文件

`reference/stock/index/stock_chart_config.json`，**首次读取时自动生成默认值**（[config_service.get_stock_chart_config](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/config_service.py)）。

```json
{
  "version": 1,
  "kline": {
    "minute_provider": "eltdx",
    "daily_provider": "tencent",
    "weekly_provider": "tencent",
    "fallbacks": {
      "minute": ["eltdx", "mootdx", "sina", "eastmoney"],
      "daily": ["tencent", "eastmoney"],
      "weekly": ["tencent", "eastmoney"]
    },
    "mootdx": {
      "servers": [
        ["110.41.147.114", 7709],
        ["8.129.13.54", 7709],
        ["124.70.176.52", 7709]
      ],
      "timeout": 10,
      "minute_adjust_mode": "none_only"
    }
  }
}
```

### 6.2 调整 provider 顺序

修改 `minute_provider` / `fallbacks.minute` 即可，`resolve_stock_klines` / `market_data_provider` 会按顺序试。

### 6.3 TDX 通道

- `mootdx.servers`：TDX 行情服务器列表，按顺序试
- `mootdx.minute_adjust_mode`：`none_only` 时分钟 K 强制不复权
- 没有 server 配置时走 `TdxClient()` 默认（不可控，**生产别用**）

---

## 7. 错误处理

### 7.1 adapter 失败

每个 adapter 函数只做单源拉取：
- 网络错误 → 抛 `requests.RequestException`（调用方吞掉转 fallback）
- 数据为空 / 解析失败 → 抛 `ValueError`，错误信息含"哪个 adapter 失败"
- 标点 / 类型转换 → 内部 try/except 跳过该行，不抛

### 7.2 全源失败

`resolve_stock_klines` 行为：
- 真实数据全失败 → 读 cache；cache 有 → 返回并标 `stale`
- cache 也无 → 走 `sample_loader` 兜底（仅非分钟）
- 分钟 K 全失败 → **直接抛 `ValueError`**，让上层 502

### 7.3 前端 meta 字段

`dataQuality=stale` 时前端应给用户**明确的提示**（当前 stock-chart 已展示 "来自缓存"）。

---

## 8. 扩展点

### 8.1 新增数据源

1. 在 [`backend/adapters/market/`](file:///f:/dev-repo/mp4-to-word-new/backend/adapters/market/) 新增 `xxx.py`
2. 实现 1~2 个函数：`fetch_stock_klines_from_xxx(target_type, symbol, period, adjust) -> list[dict]`
3. 在 [`kline_service.providers`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/kline_service.py) 字典 + [`market_data_provider.providers`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/market_data_provider.py) 字典注册
4. 在 `stock_chart_config.json` 的 `kline.fallbacks` 加入名字
5. 更新本文档 §3 矩阵 + §4 协议

### 8.2 新增数据维度

- 比如加"分钟 level-2 行情"：在 adapter 加函数 + 在 `kline_service` 加拼装 + 缓存路径 + API 路由
- 保持 §4 schema 风格，timestamp 毫秒、trade_date YYYY-MM-DD 北京时间

### 8.3 加新 target_type

当前支持 `stock` / `index` / `sector`。
- `_sector_index_symbol_from_industry` 是 sector 派生自行业的查表，要加新行业就改 [`eastmoney.py:INDUSTRY_INDEX_SYMBOL_MAP`](file:///f:/dev-repo/mp4-to-word-new/backend/adapters/market/eastmoney.py)
- 加 `fund` / `future` 等需要：[`search_service.eastmoney_search_to_target_type`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/search_service.py) 补分类 + adapter 处理 secid 前缀

---

## 9. 已知问题 / TODO

- [ ] **mootdx 重复造轮子**：[`mootdx_adapter.py`](file:///f:/dev-repo/mp4-to-word-new/backend/adapters/market/mootdx_adapter.py) 已经写了一套，但 [market_data_provider.py 的 providers 表](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/market_data_provider.py) 没注册（仅 kline_service 用了它），需要统一
- [ ] **eltdx 客户端无连接池**：每次 fetch 都 `_build_client()` 新建，建议在 `_Impl` 持有一个长连接
- [ ] **eastmoney `f100` 行业字段经常为空**：fallback 到 name 关键词推断，但 `NAME_INDUSTRY_KEYWORDS` 表只有 ~20 条，覆盖不全
- [ ] **CFI 涨跌家数 POST 表单容易 403**：失败时已经自动 fallback AKShare，但 AKShare 启动慢（依赖多），首次会比较卡
- [ ] **行情抓取无并发控制**：高 QPS 时各 adapter 会触发风控，建议加 token-bucket / Redis 限流
- [ ] **auction 0925 数据是 eltdx 私有**，没有 fallback；未来要支持多个源

---

## 10. 相关索引

- 项目结构：[infra/index.md](file:///f:/dev-repo/mp4-to-word-new/infra/index.md) §3
- Prompt 维护：[prompt/index.md](file:///f:/dev-repo/mp4-to-word-new/prompt/index.md)
