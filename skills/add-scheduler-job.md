---
name: add-scheduler-job
description: |
  在 mp4-to-word-new 项目里添加一个新的定时 job 的标准化流程.
  适用: 用户说"添加一个 job", "加个定时任务", "实现 XX scheduler", "注册到 scheduler".
  不适用: 改既有 job (直接读对应 *_scheduler.py 改即可), 或临时一次性脚本 (放 scripts/ 跑就行).
---

# 添加新 Scheduler Job (本项目标准化流程)

## 0. 先问清 3 件事

在动手之前, 必须确认:

| 字段 | 问用户什么 | 默认值 |
|---|---|---|
| **触发时间** | "几点跑? 每天 / 周末也要 / 跟其他工作日 job 同步?" | 工作日 17:00 (跟 daily_eod_incremental 同节奏) |
| **做什么** | "要落 duckdb / 落 JSON / 调子脚本 / 调 API?" | 落 duckdb 选 daily_eod_incremental 模板, 落 JSON 选 tdx_hsjday_download 模板 |
| **失败行为** | "失败要不要回滚 / 重试 / 跳过周末?" | 失败记录 last_error, 不重试, 周末自动 skip |

**禁止假设!** 这 3 个问题没问清就动手 = 必返工.

## 1. 必须改/新增的 6 个文件 (缺一不可)

```
1. scripts/<job_name>.py              ← 业务脚本 (subprocess 调) [新建]
2. backend/services/scheduler/<job_name>_scheduler.py   ← APScheduler 单文件 [新建]
3. scheduler/<job_name>_job.json      ← 状态文件 (其他 job 都有) [新建]
4. scheduler/jobs.json                ← 注册表 [改: 加 1 条]
5. backend/config/settings.py         ← SCHEDULER_<JOB_NAME>_JOB_FILE 常量 [改]
6. backend/bootstrap.py               ← is_xxx_enabled / start_xxx 注册 [改]
7. backend/api/scheduler.py           ← 6 个 dispatch 点 (按需触发/启停/启禁用) [改]
```

注: 第 7 项是给前端 /settings/scheduler 页面用的, 不需要前端接入就**可以省略** (但强烈建议加上, 否则 UI 上看不到这个 job, 也无法手动触发).

## 2. 业务脚本模板 `scripts/<job_name>.py`

要点:
- 接受 `--dry-run` / `--skip-X` flags (测试用, 跑通 1 步验证另 1 步)
- 关键节点 `log.info` 打印, 供 scheduler 抓 stdout 写状态
- 失败抛异常, 不 sys.exit(1) 静默退出 (让 scheduler 抓到 traceback)
- 不引入新依赖 (stdlib + 项目已有的库)

骨架:
```python
"""<job 描述>.

用法:
    python scripts/<job_name>.py
    python scripts/<job_name>.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("<job_name>")

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    log.info("start")
    if args.dry_run:
        log.info("[dry-run] no-op")
        return 0
    # 实际工作 ...
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 3. Scheduler 模板 `backend/services/scheduler/<job_name>_scheduler.py`

**直接照抄 `daily_eod_incremental_scheduler.py` 改 4 处**:

| 改点 | 改成什么 |
|---|---|
| 文件 docstring 顶 | 描述新 job 的触发时间 + 调哪个脚本 |
| `JOB_ID` 常量 | job id (跟 jobs.json 一致, 小写蛇形) |
| `STATUS_FILE_NAME` 常量 | 状态文件名 (跟 settings.py 的常量一致) |
| `<CRON>` 常量 | `cron 表达式 * * *` + 工作日 (例如 `"0 17 * * mon-fri"`) |
| `_job_run_xxx()` 函数 | 调 `subprocess.run([sys.executable, "-u", script_path], cwd=repo_root, timeout=...)` |
| `_default_script_path()` | `return str(_repo_root() / "scripts" / "<job_name>.py")` |
| `start_xxx_scheduler()` | 改所有日志里的 job 名字 |
| `run_xxx_now()` | 返回 `{ok, items, count, failed_count}` 形态 (给前端) |

**关键约束**:
- 业务永远走 `subprocess.run` 调脚本, **不在 scheduler 进程里直接 import 业务模块** (避免 duckdb / playwright 文件锁冲突)
- `timeout` 必填, 不要无限等. 经验值: 1-2 min 任务给 10 min, 5 min 任务给 30 min
- `cwd=str(_repo_root())` 必填, 业务脚本读相对路径
- `capture_output=True, text=True` 必填, 失败时 `r.stderr` 拿 traceback 写状态
- 状态文件用 `tmp` 文件 + `replace` 原子写 (避免半写状态)
- `_register_job` 调一次即可, 启动时自动写 jobs.json

## 4. 状态文件 `scheduler/<job_name>_job.json`

照抄 `scheduler/daily_eod_incremental_job.json`, 改 `name` / `description` / `schedule.run_time` / cron 字段. 空状态用 `null` 占位:

```json
{
  "name": "<job_id>",
  "description": "<中文描述, 含触发时间和调什么>",
  "enabled": true,
  "schedule": {
    "workday_only": true,
    "run_time": "HH:MM",
    "run_once_per_day": true
  },
  "timezone_offset_hours": 8,
  "tick_seconds": 60,
  "lastRunAt": null,
  "lastRunOk": null,
  "lastRunError": null,
  "lastDurationSeconds": null,
  "totalRuns": 0,
  "totalFailures": 0,
  "schedulerStartedAt": null
}
```

业务特有的字段 (例如 `lastMaxTradeDate`, `lastDayFileCount`) 加在末尾, 业务函数自己写.

## 5. 注册表 `scheduler/jobs.json`

在 `jobs` 数组里**末尾** (在 `test_scheduler_demo` 之前) 插一条:

```json
{
  "id": "<job_id>",
  "name": "<人类可读中文名>",
  "description": "<一段话, 含触发时间 + 调什么脚本 + 业务目的 + 预计耗时>",
  "config_file": "<job_id>_job.json",
  "service_module": "backend.services.scheduler.<job_name>_scheduler",
  "service_class": "<JobName>Scheduler",
  "enabled": true,
  "registered_at": "<今天日期 ISO>"
}
```

`description` 写**详细点**, 前端 /settings/scheduler 页面会原样展示. 至少含: cron 表达式 + 调什么脚本 + 业务目的 + 周末/节假日策略 + 预计耗时.

## 6. `backend/config/settings.py`

加 1 个常量 (跟现有 8 个 `SCHEDULER_*_JOB_FILE` 同位置):

```python
SCHEDULER_<JOB_NAME>_JOB_FILE = SCHEDULER_DIR / '<job_id>_job.json'
```

## 7. `backend/bootstrap.py`

加 import + start 调用 (在 `register_blueprints` 末尾加):

```python
from backend.services.scheduler.<job_name>_scheduler import (
    is_<job_name>_scheduler_enabled,
    start_<job_name>_scheduler,
)

# ... 在 register_blueprints 末尾
if is_<job_name>_scheduler_enabled():
    try:
        start_<job_name>_scheduler()
    except Exception as exc:
        logger.exception('<Job name> scheduler start failed: %s', exc)
```

## 8. `backend/api/scheduler.py` (给前端用)

如果前端 /settings/scheduler 要看这个 job, 在 **6 个 dispatch 点**加分支 (按 `_KNOWN_JOB_IDS` 顺序插):

| Dispatch 函数 | 加什么 |
|---|---|
| 顶部 import | `from backend.services.scheduler.<job_name>_scheduler import (...4 个)` |
| `_KNOWN_JOB_IDS` set | `+'<job_id>'` (gate, 不加这一行 404) |
| `_supports_enable()` set | `+'<job_id>'` (UI 启禁用按钮) |
| `_get_live_status()` | `+elif job_id == '<job_id>': return get_<job_name>_scheduler_status()` |
| `_start_scheduler()` | `+elif job_id == '<job_id>': start_<job_name>_scheduler()` |
| `_stop_scheduler()` | `+elif job_id == '<job_id>': stop_<job_name>_scheduler()` |
| `_trigger_scheduler()` | `+if job_id == '<job_id>': return run_<job_name>_now()` |

**漏掉第 1 行 (`_KNOWN_JOB_IDS`) 是最常见的错**: UI 点击会报 `unknown job_id: <job_id>`.

## 9. 自检清单 (提交前 1 分钟过一遍)

```
[ ] scripts/<job_name>.py  --dry-run 跑通
[ ] scripts/<job_name>.py  业务部分实际跑通 (手动下载数据 / 跑 1 次)
[ ] scheduler/<job_id>_job.json 存在 + 是合法 JSON
[ ] scheduler/jobs.json 末尾加了 1 条注册
[ ] backend/config/settings.py 加了常量
[ ] backend/services/scheduler/<job_name>_scheduler.py 存在
    [ ] start_xxx / stop_xxx / get_xxx_status / run_xxx_now 4 个函数都导出
    [ ] run_xxx_now 返回 {ok, count, failed_count, items}
    [ ] status file 用 tmp+replace 原子写
    [ ] subprocess 跑脚本带 cwd=repo_root + timeout
[ ] backend/bootstrap.py 接 start (try/except 包住)
[ ] backend/api/scheduler.py 6 个 dispatch 点都加 (如果需要前端)
[ ] 后端: python -c "from backend.services.scheduler.<job_name>_scheduler import start_xxx; start_xxx(); ..."
    [ ] running=True
    [ ] scheduler/jobs.json 自动多一条
    [ ] scheduler/<job_id>_job.json 写了 schedulerStartedAt
    [ ] stop 后 running=False
[ ] 前端: (可选) python -c "from flask import Flask; ... ; get_job('<job_id>')" 返 ok=True
```

## 10. 常见踩坑

| 症状 | 根因 | 修法 |
|---|---|---|
| 前端报 `unknown job_id: xxx` | `_KNOWN_JOB_IDS` 漏加 | 加进去 |
| 状态文件写一半损坏 | 直接覆盖没原子写 | 用 `tmp + replace` |
| subprocess 跑脚本但 import 找不到 | `cwd` 没设 | 加 `cwd=str(_repo_root())` |
| 周末/节假日也在跑 | cron 表达式忘了 `* * mon-fri` | 改 cron + 加 `is_trading_day` 二次过滤 |
| DuckDB 锁冲突 | scheduler 进程持锁 + 子进程又开 | subprocess 调脚本 (子进程独立连接) |
| 6.15/16 tencent 数据把 .day 数据冲掉 | 没限定 source | backfill 走 `INSERT OR IGNORE` + 走 tdx_day source |
| Playwright 报 120ms timeout | 写错单位 (是 ms 不是 s) | 改 `timeout=300_000` |
| 日志中文乱码 (终端显示 ???) | cmd 编码问题 | 不是代码问题, PowerShell 用 `chcp 65001` 即可, 不影响功能 |

## 11. 参考实现 (本项目里现成的模板)

- **简单 + 单 job + 落 duckdb** → `daily_eod_incremental_scheduler.py` + `scripts/daily_eod_incremental.py`
- **复杂 + 多阶段 (下载→解压→替换) + 有回滚** → `tdx_hsjday_download_scheduler.py` + `scripts/download_tdx_hsjday.py`
- **多 job 共用 1 个 scheduler** → `market_overview_scheduler.py` (6 个 job 在 1 个 APScheduler 实例里)
- **API 端到端接入** → `backend/api/scheduler.py` (找现有 job 的 dispatch 模式照抄)

## 12. 调用方式

用户在 prompt 里直接说: "用 /add-scheduler-job 加一个 job, X 点跑, 调 Y 脚本" 即可. skill 加载后, 我会按上面 12 节流程走, 一气呵成出 6-7 个文件 + 通过自检.
