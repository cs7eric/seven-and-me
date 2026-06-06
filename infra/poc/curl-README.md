# Eastmoney 板块/概念/行业 POC cURL 列表

把 POC 跑过的所有 endpoint 转成 cURL 给你自己跑。脚本在 [curl.sh](./curl.sh)。

## 跑法

```bash
# bash / git bash / WSL
bash infra/poc/curl.sh

# Windows PowerShell（要换行符 + 单引号转义，复杂一点）
# 建议用 git bash 或 WSL
```

## 我这边测过的结果（仅供参考）

| 能力 | endpoint | 状态 | 备注 |
|---|---|---|---|
| 个股 → 所属板块 (29 条) | `emweb...CoreConception/PageAjax?code=SH600519` | ✅ 通了 | `ssbk` 数组，每个含 `BOARD_CODE` (数字) / `BOARD_NAME` / `BOARD_RANK` / `IS_PRECISE` |
| 个股 → 核心题材 (8 条) | 同上 | ✅ 通了 | `hxtc` 数组，含 `KEYWORD` / `MAINPOINT` / `MAINPOINT_CONTENT` |
| 个股 F10 基础信息 | `emweb...CompanySurvey/PageAjax?code=SH600519` | ✅ 通了 | `jbzl` / `fxxg`，无板块 |
| 板块 → 成分股 | `push2.../clist/get?fs=b:BK0438` | ❌ 公司网络拦了 | 你那边如果能连 `push2.eastmoney.com` 应该能通 |
| 全量申万行业 | `push2.../clist/get?fs=m:90+t:1/2` | ❌ 同上 | 同上 |
| 全量概念板块 | `push2.../clist/get?fs=m:90+t:4` | ❌ 同上 | 同上 |
| datacenter 报表 | `datacenter-web.../api/data/v1/get?...RPT_F10_RELATED_THM_MAP` | ❌ 报 9501 | 报表下线了 |

## 哪些 endpoint 一定能跑（基于实跑）

✅ **核心数据源 — `emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax`**

实测返回值（贵州茅台 600519）：

```
ssbk (29 条): 食品饮料 / 白酒Ⅱ / 白酒Ⅲ / 白酒概念 / 沪股通 / 证金持股 / MSCI中国 / ...
hxtc (8 条):  经营范围 / 茅台酒及系列酒 / 白酒行业 / 行业领先地位 / ...
```

每条 `ssbk` 字段：
```json
{
  "BOARD_CODE": "438",        // 板块 BK code
  "BOARD_NAME": "食品饮料",    // 板块名
  "SECUCODE": "600519.SH",
  "SECURITY_CODE": "600519",
  "SECURITY_NAME_ABBR": "贵州茅台",
  "IS_PRECISE": "0",          // 1 = 精确归类，0 = 概念归类
  "BOARD_RANK": "1"           // 在板块内的排名
}
```

`BOARD_CODE` 是数字（不是 `BK` 前缀）。要拿这个 code 去 push2 查成分股时，记得拼成 `BK0438` 这种格式（push2 的 `fs` 接受 `b:BK0438`）。

## 哪些需要你这边验证

❌ **push2.eastmoney.com** — 我公司网络拦了

跑 curl.sh 时留意第 12 / 22 / 28 / 32 行那几条。如果都通，把输出贴给我，我直接把：
1. Eastmoney 板块 / 概念 / 行业 全量表 写一个 `infra/data/eastmoney-sectors.json` 持久化
2. `helpers.py` 加 4 个 Python 函数：
   - `stock_sectors(symbol) → [{bk_code, bk_name, is_precise, rank}]`
   - `sector_constituents(bk_code) → [{symbol, name, ...}]`
   - `list_industries() / list_concepts() → [{bk_code, bk_name}, ...]`
3. 加 3 个 API endpoint：`/api/eastmoney/sectors/...`
4. 更新 `infra/openapi.yaml`

## 备选：AKShare（如果 push2 真连不上）

```python
# pip install akshare
import akshare as ak

ak.stock_board_industry_name_em()         # 行业列表
ak.stock_board_concept_name_em()          # 概念列表
ak.stock_board_industry_cons_em("BK0438")  # 行业成分股
ak.stock_board_concept_cons_em("BK1033")   # 概念成分股
ak.stock_individual_info_em("600519")      # 个股基础（含行业）
```

项目里 [backend/adapters/market/eastmoney.py:268](file:///f:/dev-repo/mp4-to-word-new/backend/adapters/market/eastmoney.py#L268) 已经在用 AKShare 的 `stock_zh_a_spot_em` 做行情回退，AKShare 是项目内已验证的方案。

## 关于 push2 连不上的进一步处理

如果只能走 AKShare 而不能走 push2，差距主要在：
- **行情实时性**：AKShare 行情数据走同源 push2，也是 5-10s 刷新，体验上差不多
- **全板块列表**：AKShare 有 `stock_board_industry_name_em` / `stock_board_concept_name_em`，能直接拿全量
- **成分股**：AKShare 有 `stock_board_industry_cons_em` / `stock_board_concept_cons_em`，直接给所有成员

所以即便 push2 在你那边也连不上，**AKShare 足够覆盖这三个能力**。跑 `bash curl.sh` 之后告诉我哪些通 / 哪些不通，我用通的来落地。
