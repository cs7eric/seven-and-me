---
name: add-duckdb-persistence
description: |
  在 mp4-to-word-new 项目里给"实时拉 / JSON 落库"的业务数据加 duckdb 持久化.
  适用: 用户说"XX 落 duckdb", "XX 持久化", "把 XX 数据入库", "加 duckdb 落库",
       "数据要跨日查询", "历史回测需要", "市场指标要能查 60 天序列".
  不适用: K 线 / 分钟 K / 行情 (走 initial_backfill.py), 已有 duckdb 表的表 (直接复用),
       一次性 JSON 报告 (走 reference/).
---

# 添加 duckdb 持久化 (本项目标准化流程)

## 0. 先问清 4 件事

动手前必须确认:

| 字段 | 问用户什么 | 默认值 |
|---|---|---|
| **数据源** | "现在数据从哪儿来? JSON 落盘 / 实时拉 / service 现算?" | 默认实时拉, 走 service 改造 |
| **粒度** | "一行 = 1 只股票 / 1 个交易日 / 1 个行业?" | 一日一行业 / 一日一只 (跟数据源对齐) |
| **覆盖范围** | "近 N 天够吗? 还是从开市起全量?" | 近 60 天 (backfill 脚本默认) |
| **写穿 vs 写后** | "实时拉时就 upsert 进去, 还是先 JSON, 收盘后 batch 回填?" | 写穿 + 收盘后双保险 (本项目模式) |

**禁止假设!** 这 4 个问题没问清就动手 = 表设计返工.

## 1. 必须改/新增的文件清单 (6 个文件 + 1 个调度可选)

```
1. reference/stock/duckdb/schema.sql        ← 追加新表 + bump schema_version [改]
2. backend/repositories/market/<name>_repo.py   ← 仓储层 (upsert + get + history) [新建]
3. backend/services/stock/<name>_service.py  ← 业务 service 末尾追加 1 行 upsert [改]
4. scripts/backfill_<name>.py              ← 历史回填 (扫 JSON archive) [新建]
5. backend/api/stock_chart.py              ← 历史读 API 端点 (不动原 API) [改]
6. scripts/smoke_test_<name>.py            ← 端到端 smoke test [新建]
```

可选 (跟"挂到 scheduler"绑定, 走 add-scheduler-job):
```
7. backend/services/scheduler/<name>_scheduler.py  [新建]
   + scheduler/<name>_job.json
   + scheduler/jobs.json (注册)
   + backend/config/settings.py (常量)
   + backend/bootstrap.py (start)
   + backend/api/scheduler.py (6 个 dispatch 点)
   + scripts/daily_eod_incremental.py (挂到现有 daily job 末尾, 双保险)
```

## 2. schema.sql 追加新表

### 2.1 表名 + PK 选型

| 业务 | 表名 | PK |
|---|---|---|
| 大盘概况 (1 日 1 行) | `market_overview_daily` | `trade_date` |
| 90 行业 (1 日 90 行) | `market_pulse_sector_daily` | `(trade_date, sector_name)` |
| 单只股票指标 (1 日 N 行) | `<indicator>_daily` | `(trade_date, code)` |
| 全市场单值 (1 日 1 行) | `<name>_daily` | `trade_date` |

**单列 PK** 用 `trade_date`; **复合 PK** 用 `(trade_date, 维度字段)`. 不要用自增 ID (回填困难).

### 2.2 字段类型 + 单位约定

```sql
-- 模板 (单日单行)
CREATE TABLE IF NOT EXISTS <name>_daily (
    trade_date        DATE          PRIMARY KEY,
    -- 数值字段
    total_amount      DECIMAL(18, 4),                  -- 资金 / 成交额: 单位"亿"
    total_volume      DECIMAL(18, 4),                  -- 成交量: 单位"万手"
    -- 整数字段
    rising_count      INTEGER,
    falling_count     INTEGER,
    -- 比例字段
    pct_ma20          DECIMAL(6, 2),                   -- 百分比, 2 位小数 (0-100)
    return_pct        DECIMAL(8, 4),                   -- 收益率, 4 位小数 (-100 ~ +100)
    -- 元数据
    source            VARCHAR(32),                     -- 'akshare' | 'eltdx' | 'manual'
    ingested_at       TIMESTAMP     NOT NULL DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_<name>_date ON <name>_daily(trade_date);
```

```sql
-- 模板 (一日多行, 90 行业 / 多只股票)
CREATE TABLE IF NOT EXISTS <name>_daily (
    trade_date        DATE          NOT NULL,
    sector_name       VARCHAR(64)   NOT NULL,         -- 维度字段
    change_pct        DECIMAL(8, 4) NOT NULL,
    inflow            DECIMAL(18, 4) NOT NULL DEFAULT 0,
    outflow           DECIMAL(18, 4) NOT NULL DEFAULT 0,
    main_net          DECIMAL(18, 4) NOT NULL DEFAULT 0,
    -- 元数据
    source            VARCHAR(32)   NOT NULL,
    ingested_at       TIMESTAMP     NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (trade_date, sector_name)
);
CREATE INDEX IF NOT EXISTS idx_<name>_date ON <name>_daily(trade_date);
```

### 2.3 字段命名约定 (跟现有 repo 保持一致)

| 业务字段 | 表字段 | 备注 |
|---|---|---|
| `totalAmount` | `total_amount` | snake_case |
| `mainNetInflow` | `main_net_inflow` | |
| `changePct` | `change_pct` | |
| `limitUpCount` | `limit_up_count` | |
| `industry name` | `sector_name` | 中文行业名用 VARCHAR(64) |

### 2.4 schema_version bump

```sql
-- 文件末尾 INSERT OR REPLACE (原来 1.5.0 → 加表后 1.6.0)
INSERT OR REPLACE INTO schema_meta(key, value) VALUES
    ('schema_version', '1.6.0'),
    ('created_at', current_timestamp::VARCHAR);
```

### 2.5 老数据迁移 (如果有 ALTER TABLE)

DuckDB 不支持 ADD COLUMN 时加 NOT NULL DEFAULT, 用 nullable + UPDATE 兜底:

```sql
ALTER TABLE <name>_daily ADD COLUMN IF NOT EXISTS new_col DECIMAL(6, 2);
UPDATE <name>_daily SET new_col = 0 WHERE new_col IS NULL;
```

## 3. 仓储层 (新建 1 个 repo, 4 个函数)

```python
# backend/repositories/market/<name>_repo.py
"""<业务> duckdb 仓储.

数据源:
  - service 层: 实时拉 → upsert (写穿)
  - backfill 脚本: 扫 JSON archive → upsert (历史回填)

upsert 策略: INSERT OR REPLACE by PK (幂等).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn  # 注意: 不用 conn() contextmanager, 业务层避免 DuckDBPyConnection.__exit__ close 陷阱

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# 1. 批量 upsert (给 service + backfill 用)
def upsert_<name>(rows: list[dict[str, Any]], source: str = "...") -> int:
    """批量写入. 走 INSERT OR REPLACE by PK, 重复跑幂等.

    rows 元素含: tradeDate (或 date 字段) + 业务字段.
    """
    if not rows:
        return 0
    con = get_conn()
    sql = """INSERT OR REPLACE INTO <name>_daily (...) VALUES (...)"""
    n = 0
    for r in rows:
        td = _to_date(r.get("tradeDate") or r.get("trade_date"))
        if td is None:
            continue
        con.execute(sql, [td, ..., source])
        n += 1
    return n


# 2. 字段级 upsert (多源合并, 字段级 COALESCE 保护)
def upsert_<name>_akshare(payload: dict[str, Any]) -> None:
    """字段级 COALESCE 保护: 新值非 NULL 时, COALESCE 保留已有值.
    
    用途: akshare + eltdx 同一表不同字段 (akshare 资金流 + eltdx 涨跌家数),
    互相不覆盖.
    """
    td = _to_date(payload.get("tradingDate"))
    if td is None:
        return
    con = get_conn()
    con.execute("INSERT OR IGNORE INTO <name>_daily (trade_date, source) VALUES (?, ?)", [td, "akshare"])
    set_clauses = []
    params = []
    for col, key, cast in _FIELDS:
        v = payload.get(key)
        if v is None:
            continue
        if cast.startswith("DECIMAL"):
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS {cast}))")
            params.append(float(v))
        elif cast == "INTEGER":
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS INTEGER))")
            params.append(int(v))
    if set_clauses:
        params.append(td)
        con.execute(f"UPDATE <name>_daily SET {', '.join(set_clauses)} WHERE trade_date = ?", params)


# 3. 单日查
def get_<name>(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(f"SELECT ... FROM <name>_daily WHERE trade_date = ?", [td]).fetchone()
    return _row_to_payload(r) if r else None


# 4. 区间查 (历史序列, 趋势图用)
def get_<name>_history(
    start: date | str, end: date | str | None = None, limit: int = 60,
) -> list[dict[str, Any]]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    limit = max(1, min(limit, 500))
    con = get_conn()
    rows = con.execute(
        f"SELECT ... FROM <name>_daily WHERE trade_date BETWEEN ? AND ? "
        f"ORDER BY trade_date DESC LIMIT ?",
        [s, e, limit],
    ).fetchall()
    return [_row_to_payload(r) for r in reversed(rows)]


# 5. 覆盖度 (运维用, 跟 scheduler status 一起写)
def coverage() -> dict[str, Any]:
    con = get_conn()
    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM <name>_daily").fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
    }
```

## 4. service 层追加 1 行 upsert

**关键**: 不破坏现有 service 行为, 只是末尾**追加 1 个 try/except 包住的 upsert 调用**.

```python
# 现有 service 末尾 (比如 _save_snapshot / save_overview / build_capital_flow 之后)
archive = _save_snapshot(payload)  # 不动
# ... 现有日志 ...
# 新增 ↓↓↓ (字段级 upsert, 失败不影响主流程)
try:
    from backend.repositories.market.<name>_repo import upsert_<name>_akshare
    upsert_<name>_akshare(payload)
except Exception as exc:
    logger.debug("upsert_<name> to duckdb failed (non-fatal): %s", exc)
return payload  # 不动
```

**多源合并 (akshare + eltdx 同一表)**: 在 eltdx service 里同样追加一行, 字段级 COALESCE 保护避免互相覆盖.

## 5. backfill 脚本 (历史回填)

**用途**: 一次性回填历史 + 每日增量兜底 (防止 service 写穿漏掉的日子).

```python
# scripts/backfill_<name>.py
"""<业务> duckdb 一次性回填 + 每日增量.

数据源 (扫本地 JSON, 不走网络):
  1. reference/<...>/archive/YYYYMMDD.json
  2. reference/<...>/YYYY-MM-DD.json

幂等: 全部走 INSERT OR REPLACE / 字段级 UPSERT, 重复跑不写脏.

用法:
    python scripts/backfill_<name>.py
    python scripts/backfill_<name>.py --days=60
    python scripts/backfill_<name>.py --date=2026-06-16  # 单日
    python scripts/backfill_<name>.py --dry-run
"""
from __future__ import annotations

import argparse, json, logging, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_<name>")

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = REPO_ROOT / "reference" / "<...>" / "archive"


def _yyyymmdd_to_iso(stem: str) -> str | None:
    if len(stem) != 8 or not stem.isdigit():
        return None
    try:
        return date(int(stem[:4]), int(stem[4:6]), int(stem[6:8])).isoformat()
    except ValueError:
        return None


def _scan_archive(days: int) -> list[dict]:
    """扫 archive/YYYYMMDD.json, 倒序取最近 N 天, 返回 list[dict]."""
    out = []
    if not ARCHIVE_DIR.exists():
        return out
    for f in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True):
        iso = _yyyymmdd_to_iso(f.stem)
        if not iso:
            continue
        d = date.fromisoformat(iso)
        if d < date.today() - timedelta(days=days):
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("%s parse failed: %s", f.name, exc)
            continue
        if isinstance(data, dict):
            if not data.get("tradingDate"):
                data["tradingDate"] = iso
            out.append(data)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--date", type=str, default=None, help="单日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log.info("start: days=%s dry_run=%s", args.days, args.dry_run)

    from backend.adapters.market.duckdb_store import init_schema
    init_schema()

    items = _scan_archive(args.days)
    log.info("archive 命中 %d 天", len(items))

    if args.dry_run:
        log.info("[dry-run] 没写任何东西")
        return 0

    n = 0
    from backend.repositories.market.<name>_repo import upsert_<name>
    for it in items:
        try:
            upsert_<name>(it)  # 单条 upsert
            n += 1
        except Exception as exc:
            log.warning("upsert %s failed: %s", it.get("tradingDate"), exc)
    log.info("done. upserted=%d", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 6. 挂到 scheduler (双保险)

走 `add-scheduler-job` skill, 关键点:

| 项 | 设定 |
|---|---|
| 触发时间 | **17:10 工作日** (在 17:00 daily_eod 之后) — 双保险, 主路径在 service 写穿 |
| timeout | 5 min (扫 60 天 archive, 实测 < 1s) |
| 脚本 | `python scripts/backfill_<name>.py --days=60` |
| 业务字段 | `lastUpserted / lastCoverage` 等覆盖度字段, 写进 status.json 给前端展示 |
| jobs.json id | `<name>_daily` (跟 `_daily` 表对齐) |

**额外**: 在 `scripts/daily_eod_incremental.py` 末尾追加 Step 3 (双保险, 主路径在 17:10 scheduler):

```python
# 现有 daily_eod_incremental.py 末尾
if not args.no_summary and les_gap > 0:
    # ... limit_emotion_summary backfill

# 新增 step 3
if not args.no_<name>:
    ok &= _run(
        [str(SCRIPTS / "backfill_<name>.py"), "--days=3"],
        "Step 3  backfill_<name>.py --days=3  (<业务> → duckdb)",
    )
```

## 7. API 端点 (新增, 不动原 API)

```python
# backend/api/stock_chart.py 末尾追加
@stock_chart_bp.route('/api/stock-chart/<name>/history')
def <name>_history():
    """读 duckdb.<name>_daily 的近 N 天历史 (新增, 跟原 /<name> 不冲突).

    URL: ?days=60 (1-365, 默认 60) &start=YYYY-MM-DD &end=YYYY-MM-DD
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.<name>_repo import get_<name>_history
    try:
        end_str = (request.args.get("end") or "").strip()
        start_str = (request.args.get("start") or "").strip()
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        if start_str:
            start = _date.fromisoformat(start_str)
        else:
            days_arg = int(request.args.get("days") or 60)
            days_arg = max(1, min(days_arg, 365))
            start = end - timedelta(days=days_arg)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    try:
        items = get_<name>_history(start, end)
        return jsonify({"ok": True, "start": start.isoformat(),
                        "end": end.isoformat(), "count": len(items), "items": items})
    except Exception as exc:
        logger.exception("<name> history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200
```

**前端不动**: 前端继续调原 API 拿 JSON 实时数据. duckdb 落库对前端透明, 给后端做历史查询 / 跨日趋势 / 回测用.

## 8. 端到端 smoke test

```python
# scripts/smoke_test_<name>.py
"""<name>_daily 端到端 smoke test."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 重要: 用 conn() contextmanager, 不用 get_conn() 直接 with
# (DuckDBPyConnection.__exit__ 会 close, 导致后续 _local.conn 失效)
from backend.adapters.market.duckdb_store import conn
from backend.repositories.market.<name>_repo import (
    upsert_<name>, upsert_<name>_akshare, get_<name>,
    get_<name>_history, coverage,
)

# 1. 字段级 COALESCE 保护测试
with conn() as c:
    c.execute("DELETE FROM <name>_daily WHERE trade_date = '2026-06-16'")

upsert_<name>_akshare({"tradingDate": "2026-06-16", "field1": 100, "source": "akshare"})
upsert_<name>     ({"tradingDate": "2026-06-16", "field2": 200, "source": "manual"})

# 期望: 两次写都保留, source='akshare+manual'
row = get_<name>("2026-06-16")
assert row["field1"] == 100, f"COALESCE 保护失效: field1={row['field1']}"
assert row["field2"] == 200
print("✓ 字段级 COALESCE 保护 OK")

# 2. 区间查
hist = get_<name>_history("2026-06-10", "2026-06-16", limit=5)
print(f"✓ history 返回 {len(hist)} 条")

# 3. 覆盖度
print(f"✓ coverage: {coverage()}")
```

跑通后, 跑一次 `python scripts/backfill_<name>.py --days=60` 实际回填.

## 9. 常见踩坑

| 症状 | 根因 | 修法 |
|---|---|---|
| `Connection already closed!` | `with get_conn() as c:` 触发 `DuckDBPyConnection.__exit__` close, 关闭 thread-local 连接, 后续全挂 | 改用 `with conn() as c:` (contextmanager 不 close) |
| eltdx 字段覆盖了 akshare 字段 | upsert 走 `SET col = val` 直接覆盖 | 改 `SET col = COALESCE(col, CAST(? AS ...))` 字段级保护 |
| 老 archive 字段是 None 把已有值冲掉 | `payload.get(key)` 是 None 也写, INSERT OR REPLACE 直接覆盖成 None | upsert 循环里 `if v is None: continue` 跳过 |
| backfill 重复跑写脏 | INSERT INTO 重复 | 全部走 `INSERT OR REPLACE by PK` (幂等) |
| DuckDB 锁冲突 (scheduler + 子进程同时开) | scheduler 持锁 + 子进程 backfill 又开 | backfill 走 subprocess (子进程独立连接, 用 `subprocess.run` 调脚本) |
| 中文乱码 (终端显示 ???) | cmd 编码 | 不是代码问题, PowerShell `chcp 65001` 即可, 不影响功能 |
| 前端用旧字段名 (camelCase) 取不到数据 | repo 返 snake_case, 前端要 camelCase | `_row_to_payload` 里手动转 dict key: `"totalAmount": row[...]` |
| 跑 backfill 报 `relation does not exist` | schema 没跑 | 脚本开头 `init_schema()` (幂等) |

## 10. 参考实现 (本项目里现成的模板)

| 业务 | schema 表 | repo | service 加 upsert | backfill |
|---|---|---|---|---|
| **大盘概况 + 资金流 + 涨跌家数** | `market_overview_daily` | `market_overview_repo.py` (字段级 COALESCE) | `market_overview_akshare_service` + `market_overview_eltdx_service` | `backfill_market_overview_daily.py` |
| **市场脉搏 90 行业** | `market_pulse_sector_daily` | `market_pulse_sector_repo.py` | `market_pulse_service.build_capital_flow` | (同上) |
| **MA 计数 + 市场宽度** | `ma_count_daily` | `indicator_repo.calc_ma_count + save_ma_count + calc_ma_count_cached` | cache-aside (API 触发) | `backfill_ma_count_and_returns.py` |
| **涨跌停情绪综合分** | `limit_emotion_summary_daily` | `limit_repo.calc_limit_emotion_summary + save_*_cached` | cache-aside | `backfill_limit_emotion_summary.py` |
| **风险偏好** | `risk_appetite_daily` | `risk_appetite_repo.py` (cache-aside) | (cache-aside) | (scripts/backfill_risk_appetite.py) |
| **宽基指数 N 日收益** | `index_returns_daily` | `index_repo.get_index_returns_cached` | cache-aside | `backfill_ma_count_and_returns.py` |
| **宽基指数日线** | `index_daily_raw` | `index_repo.upsert_index_daily` | `fetch_index_history.py` | (同左) |

## 11. 调用方式

用户在 prompt 里直接说: "用 /add-duckdb-persistence 把 XX 数据落 duckdb" 即可. skill 加载后, 我会按上面 11 节流程走, 一气呵成出 6 个文件 + smoke test + 可选挂调度.
