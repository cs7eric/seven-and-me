"""Scheduler 管理 API。

给前端 ``/settings/scheduler`` 页用：列出 Postgres ``app.scheduler_jobs`` 表中所有注册的 job，
展示每个 job 的实时调度器状态、配置 + 上次运行情况，并提供 enable / disable / trigger /
start / stop 五个动作。

维护前请先看:
- `F:\dev-repo\mp4-to-word-new\design\backend\index.md`
- `F:\dev-repo\mp4-to-word-new\design\backend\scheduler-registry-runtime.md`

约定：
- ``app.scheduler_jobs`` 是 job 注册表，所有 job 元数据 + 配置 (extra JSONB) 都在这里
- enable / disable 通过改写对应 job 的 ``extra`` JSONB 中的 ``enabled`` 字段 + ``is_enabled`` 列实现
- start / stop / trigger 走各 scheduler service 暴露的方法
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

from backend.services.scheduler.auction_analysis_scheduler import (
    get_auction_analysis_scheduler,
    get_auction_analysis_scheduler_status,
    start_auction_analysis_scheduler,
    stop_auction_analysis_scheduler,
)
from backend.services.scheduler.status_store import load_status
from backend.services.scheduler.config_store import sync_job_descriptions
from backend.services.scheduler.target_date import normalize_target_date
from backend.services.scheduler.daily_eod_incremental_scheduler import (
    get_daily_eod_incremental_scheduler_status,
    run_daily_eod_incremental_now,
    start_daily_eod_incremental_scheduler,
    stop_daily_eod_incremental_scheduler,
)
from backend.services.scheduler.initial_backfill_scheduler import (
    get_initial_backfill_scheduler_status,
    run_initial_backfill_now,
    start_initial_backfill_scheduler,
    stop_initial_backfill_scheduler,
)
from backend.services.scheduler.limit_emotion_scheduler import (
    get_limit_emotion_scheduler_status,
    run_limit_emotion_now,
    start_limit_emotion_scheduler,
    stop_limit_emotion_scheduler,
)
from backend.services.scheduler.ma_count_scheduler import (
    get_ma_count_scheduler_status,
    run_ma_count_now,
    start_ma_count_scheduler,
    stop_ma_count_scheduler,
)
from backend.services.scheduler.market_overview_daily_scheduler import (
    get_market_overview_daily_scheduler_status,
    run_market_overview_daily_now,
    start_market_overview_daily_scheduler,
    stop_market_overview_daily_scheduler,
)
from backend.services.scheduler.market_overview_scheduler import (
    get_market_overview_scheduler_status,
    run_market_overview_snapshot_now,
    start_market_overview_scheduler,
    stop_market_overview_scheduler,
)
from backend.services.scheduler.market_pulse_scheduler import (
    get_market_pulse_scheduler_status,
    start_market_pulse_scheduler,
    stop_market_pulse_scheduler,
    trigger_market_pulse_close_snapshot_now,
    trigger_market_pulse_constituents_now,
    trigger_market_pulse_snapshot_now,
)
from backend.services.scheduler.market_sentiment_index_scheduler import (
    get_market_sentiment_index_scheduler_status,
    run_market_sentiment_index_now,
    start_market_sentiment_index_scheduler,
    stop_market_sentiment_index_scheduler,
)
from backend.services.scheduler.market_sentiment_chain_scheduler import (
    get_market_sentiment_chain_scheduler_status,
    run_market_sentiment_chain_now,
    start_market_sentiment_chain_scheduler,
    stop_market_sentiment_chain_scheduler,
)
from backend.services.scheduler.risk_appetite_scheduler import (
    get_risk_appetite_scheduler_status,
    run_risk_appetite_now,
    start_risk_appetite_scheduler,
    stop_risk_appetite_scheduler,
)
from backend.services.scheduler.profit_effect_scheduler import (
    get_profit_effect_scheduler_status,
    run_profit_effect_now,
    start_profit_effect_scheduler,
    stop_profit_effect_scheduler,
)
from backend.services.scheduler.volatility_sentiment_scheduler import (
    get_volatility_sentiment_scheduler_status,
    run_volatility_sentiment_now,
    start_volatility_sentiment_scheduler,
    stop_volatility_sentiment_scheduler,
)
from backend.services.scheduler.stock_universe_scheduler import (
    get_stock_universe_scheduler,
    get_stock_universe_scheduler_status,
    start_stock_universe_scheduler,
    stop_stock_universe_scheduler,
)
from backend.services.scheduler.qfq_reconciliation_scheduler import (
    get_qfq_reconciliation_scheduler_status,
    run_qfq_reconciliation_now,
    start_qfq_reconciliation_scheduler,
    stop_qfq_reconciliation_scheduler,
)
from backend.services.scheduler.sector_breadth_scheduler import (
    get_sector_breadth_scheduler_status,
    run_sector_breadth_now,
    start_sector_breadth_scheduler,
    stop_sector_breadth_scheduler,
)
from backend.services.scheduler.style_risk_appetite_scheduler import (
    get_style_risk_appetite_scheduler_status,
    run_style_risk_appetite_now,
    start_style_risk_appetite_scheduler,
    stop_style_risk_appetite_scheduler,
)
from backend.services.scheduler.turnover_activity_scheduler import (
    get_turnover_activity_scheduler_status,
    run_turnover_activity_now,
    start_turnover_activity_scheduler,
    stop_turnover_activity_scheduler,
)
from backend.services.scheduler.tdx_hsjday_download_scheduler import (
    get_tdx_hsjday_download_scheduler_status,
    run_tdx_hsjday_download_now,
    start_tdx_hsjday_download_scheduler,
    stop_tdx_hsjday_download_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_daily_scheduler import (
    get_ths_industry_constituents_daily_scheduler_status,
    start_ths_industry_constituents_daily_scheduler,
    stop_ths_industry_constituents_daily_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_scheduler import (
    get_ths_industry_constituents_scheduler,
    get_ths_industry_constituents_scheduler_status,
    start_ths_industry_constituents_scheduler,
    stop_ths_industry_constituents_scheduler,
)
from backend.services.scheduler.ths_industry_fund_flow_daily_scheduler import (
    get_ths_industry_fund_flow_daily_scheduler_status,
    run_ths_industry_fund_flow_daily_now,
    start_ths_industry_fund_flow_daily_scheduler,
    stop_ths_industry_fund_flow_daily_scheduler,
)
from backend.services.scheduler.turnover_scheduler import (
    get_turnover_scheduler,
    get_turnover_scheduler_status,
    start_turnover_scheduler,
    stop_turnover_scheduler,
)
from backend.services.stock.application_analysis_scheduler import (
    get_application_analysis_scheduler_status,
    scheduler as application_analysis_scheduler,
    start_application_analysis_scheduler,
    stop_application_analysis_scheduler,
)
from backend.services.stock.market_overview_eltdx_service import capture_overview

scheduler_bp = Blueprint('scheduler_mgmt', __name__)

logger = logging.getLogger(__name__)

LEGACY_JOB_ID_ALIASES: dict[str, str] = {
    "ma_count": "ma_count_refresh",
    "risk_appetite": "risk_appetite_refresh",
    "volatility_sentiment": "volatility_sentiment_refresh",
}

MARKET_SENTIMENT_COMPONENT_JOB_IDS = {
    'tdx_hsjday_download',
    'initial_backfill_refresh',
    'qfq_reconciliation_refresh',
    'limit_emotion_refresh',
    'risk_appetite_refresh',
    'ma_count_refresh',
    'volatility_sentiment_refresh',
    'style_risk_appetite_refresh',
    'profit_effect_refresh',
    'market_overview_daily',
    'turnover_activity_refresh',
    'ths_industry_fund_flow_daily',
    'sector_breadth_refresh',
    'market_sentiment_index_refresh',
}


def _canonical_job_id(job_id: str | None) -> str | None:
    if not job_id:
        return job_id
    return LEGACY_JOB_ID_ALIASES.get(job_id, job_id)


def _candidate_job_ids(job_id: str | None) -> list[str]:
    canonical = _canonical_job_id(job_id)
    items: list[str] = []
    for value in (job_id, canonical):
        if value and value not in items:
            items.append(value)
    if canonical:
        for legacy, current in LEGACY_JOB_ID_ALIASES.items():
            if current == canonical and legacy not in items:
                items.append(legacy)
    return items

# ---------------------------------------------------------------------------
# Job category: 给前端 /settings/scheduler 渲染 tab 用.
# ---------------------------------------------------------------------------
# 两份映射:
#   1. JOB_CATEGORIES      -- list[CategoryMeta], 顺序即 id (1-based, 跟 SQL BIGSERIAL 对齐)
#   2. JOB_CATEGORY_MAP    -- job_id → [category_id (int), ...] 多对多
#
# 跟 scheduler_migration.sql 的 scheduler_job_categories / scheduler_job_category_mapping
# 两张表对齐 (SQL INSERT 顺序就是这个 list 的顺序). 切到 Postgres 持久化后, 这两个 dict
# 直接换成 SQL 查询即可.

@dataclass(frozen=True)
class CategoryMeta:
    label: str
    icon_hint: str           # lucide 图标名, 前端 ICON_MAP 映射到组件
    sort_order: int
    description: str = ''


# category 定义. list 顺序 = id (1-based), 跟 SQL INSERT 顺序一一对齐.
# 警告: 重排这个 list 会改变所有 job 的 category_id 进而打乱 JOB_CATEGORY_MAP;
# 增/删/改 metadata 是安全的, 不要重排顺序 (除非同时改 JOB_CATEGORY_MAP).
JOB_CATEGORIES: list[CategoryMeta] = [
    CategoryMeta('盘内实时', 'activity',  10, '工作时间内 (盘内/盘后) 持续刷新的 job'),                       # id=1
    CategoryMeta('AI 分析',  'sparkles',  20, 'AI 解读 / 标的级应用分析'),                                  # id=2
    CategoryMeta('数据采集', 'database',  30, '爬虫 / 离线下载 (A 股全市场 / 同花顺行业成分股 / TDX 历史)'),  # id=3
    CategoryMeta('EOD 回填', 'refresh',   40, '工作日盘后增量回填 duckdb'),                                  # id=4
    CategoryMeta('市场情绪', 'activity',  25, 'MSI 9 factor + composite'),                                  # id=5
    CategoryMeta('测试',     'flask',     99, '测试用 entry, 用来演示 jobs.json 注册表 CRUD'),               # id=6
]

# job ↔ category 多对多映射 (仅用于 list_categories 的 DB 不可用回退).
# 注: _categories_for() 已不再使用此映射.
JOB_CATEGORY_MAP: dict[str, list[int]] = {
    'turnover_refresh':                       [1],
    'market_pulse_inside':                    [1],
    'market_pulse_close':                     [1],
    'market_pulse_constituents':              [1],
    'market_overview_inside':                 [1],
    'market_overview_close':                  [1],
    'market_overview_warmup':                 [1],
    'eltdx_overview_inside':                  [1],
    'eltdx_overview_close':                   [1],
    'eltdx_overview_warmup':                  [1],
    'application_analysis':                   [2],
    'auction_ai_analysis':                    [2],
    'stock_universe_refresh':                 [3],
    'ths_industry_constituents_weekly':       [3],
    'ths_industry_constituents_daily':        [3],
    'tdx_hsjday_download':                    [3, 5],
    'daily_eod_incremental':                  [4, 5],
    'market_overview_daily':                  [4, 5],
    'ths_industry_fund_flow_daily':           [4],
    'style_risk_appetite_refresh':            [5],
    'profit_effect_refresh':                  [5],
    'market_sentiment_index_refresh':         [5],
    'volatility_sentiment_refresh':           [5],
    'ma_count_refresh':                               [5],
    'risk_appetite_refresh':                  [5],
    'limit_emotion_refresh':                  [5],
    'sector_breadth_refresh':                 [5],
    'initial_backfill_refresh':               [5],
    'qfq_reconciliation_refresh':             [5],
    'turnover_activity_refresh':              [5],
    'market_sentiment_chain_refresh':         [5],
    'test_scheduler_demo':                    [6],
}


def _categories_for(job_id: str | None) -> list[int]:
    """返 job_id 属于的所有 category id (int, 按 sort_order 排序). 未知 job 返 [].

    数据来源: Postgres ``app.scheduler_job_category_mappings``; DB 不可用时返 [].
    """
    job_id = _canonical_job_id(job_id)
    if not job_id:
        return []
    try:
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            return SchedulerJobRepository(db).category_ids_for_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_categories_for(%s) DB read failed: %s", job_id, exc,
        )
        return []


# ---------------------------------------------------------------------------
# Last-run 字段归一化
# ---------------------------------------------------------------------------
# 仓库里 scheduler 的状态字段名不统一 (历史原因):
#   - 老的 (turnover / auction / stock_universe / ths_industry_*):
#       snake_case: last_run_at / last_status / last_targets_processed /
#                   last_duration_seconds / last_error / total_runs
#   - 新的 (daily_eod_incremental / market_overview_daily / market_overview /
#     market_pulse / risk_appetite / ma_count / volatility_sentiment /
#     tdx_hsjday_download / ths_industry_fund_flow_daily):
#       camelCase: lastRunAt / lastRunOk (bool) / lastRunError / lastDurationSeconds /
#                  totalRuns / totalFailures + 各 job 特定的 lastXxxUpserted 字段
#   - 内存 only: application_analysis (有 per-target last_run map)
#   - 外部脚本: market_sentiment_index / profit_effect / style_risk_appetite
#     (config 文件无 last_run 字段)
#
# 前端 ``/settings/scheduler`` 统一只读 ``item.last_run.*`` 六个字段, 由本函数
# 集中从各 scheduler 的 status / config 抽出. 缺数据时返 None, 不抛错.

def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str) and v.strip():
        return v
    return None


def _coerce_num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


def _first_str(*sources: dict | None, keys: tuple[str, ...]) -> str | None:
    """从多个 dict 里按顺序取第一个非空字符串字段."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in keys:
            v = _coerce_str(src.get(k))
            if v is not None:
                return v
    return None


def _first_num(*sources: dict | None, keys: tuple[str, ...]) -> float | None:
    """从多个 dict 里按顺序取第一个可解析为数字的字段."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in keys:
            v = _coerce_num(src.get(k))
            if v is not None:
                return v
    return None


def _normalize_status_from_bool(ok_val: Any) -> str | None:
    """``lastRunOk`` (True/False/None) → 统一 status 字符串."""
    if ok_val is None:
        return None
    return "success" if bool(ok_val) else "failed"


def _normalize_last_run(job_id: str, status: dict, config: dict) -> dict[str, Any]:
    """把各 scheduler 的异构 status/config 字段归一化为六个标准字段.

    返回 ``{last_run_at, last_status, last_targets_processed, last_duration_seconds,
    last_error, total_runs}`` (可能含 None).

    字段语义:
      - last_run_at: 上次运行完成时间 (ISO 字符串)
      - last_status: "success" | "failed" | "partial_failed" | "skipped_non_trading_day" | "idle" | "unknown"
      - last_targets_processed: 处理的标的数 (按各 job 含义解释: 标的 / 行业 / 行 / 天 / 文件数)
      - last_duration_seconds: 上次耗时
      - last_error: 上次错误信息
      - total_runs: 累计运行次数
    """
    job_id = _canonical_job_id(job_id) or job_id

    # 通用: 从 status + config 联合抽基础字段
    last_run_at = _first_str(status, config, keys=("last_run_at", "lastRunAt"))
    last_status_raw = _first_str(
        status, config,
        keys=("last_status", "lastStatus"),
    )
    last_error = _first_str(
        status, config,
        keys=("last_error", "lastError", "last_run_error", "lastRunError"),
    )
    last_duration = _first_num(
        status, config,
        keys=("last_duration_seconds", "lastDurationSeconds"),
    )
    total_runs = _first_num(
        status, config,
        keys=("total_runs", "totalRuns"),
    )

    # lastRunOk (bool) → status 字符串 (与 last_status 互斥, 优先取字符串, 否则 bool 转换)
    if last_status_raw is None:
        last_status_raw = _normalize_status_from_bool(
            _first_num(status, config, keys=("last_run_ok", "lastRunOk", "lastConstituentsOk"))
        )

    # 处理标的: 各 job 含义不同, 集中映射
    targets: float | None = None

    if job_id in {
        "turnover_refresh", "auction_ai_analysis",
    }:
        targets = _first_num(
            config, status,
            keys=("last_targets_processed", "lastTargetsProcessed"),
        )
    elif job_id == "application_analysis":
        # 内存 last_run 是 dict[target_id -> {status, finished_at, ...}]
        # 这里统计: 总 target 数 / 成功数, 取出最后一次 finished_at 当 last_run_at
        last_run_map = status.get("last_run") if isinstance(status, dict) else None
        if isinstance(last_run_map, dict) and last_run_map:
            total = 0
            succeeded = 0
            latest_finished: str | None = None
            for info in last_run_map.values():
                if not isinstance(info, dict):
                    continue
                total += 1
                if info.get("status") == "success":
                    succeeded += 1
                finished_at = _coerce_str(info.get("finished_at"))
                if finished_at and (latest_finished is None or finished_at > latest_finished):
                    latest_finished = finished_at
            targets = float(total) if total else None
            if last_run_at is None:
                last_run_at = latest_finished
            if last_status_raw is None and total > 0:
                last_status_raw = "success" if succeeded == total else "partial_failed"
    elif job_id == "stock_universe_refresh":
        # 三个维度: 股票 / 行业 / 题材. 取总和.
        s = _first_num(config, status, keys=("last_stock_count",))
        i = _first_num(config, status, keys=("last_industry_count",))
        t = _first_num(config, status, keys=("last_topic_count",))
        parts = [n for n in (s, i, t) if n is not None]
        targets = sum(parts) if parts else None
    elif job_id in {
        "ths_industry_constituents_weekly", "ths_industry_constituents_daily",
    }:
        rows = _first_num(config, status, keys=("last_total_rows",))
        ind = _first_num(config, status, keys=("last_industry_count",))
        # 优先用 last_total_rows (更精确), 缺则用 last_industry_count
        targets = rows if rows is not None else ind
    elif job_id in {
        "market_pulse_inside", "market_pulse_close", "market_pulse_constituents",
    }:
        # market_pulse 共享一份 status. 三个 job 取各自最近刷新时间
        # 标的数: totalInside / totalClose 是累计次数, 不是标的数
        # 用 lastTopN 长度 (排名榜条数, 通常 5) 或 lastConstituentsIndustriesOk
        if job_id == "market_pulse_constituents":
            targets = _first_num(status, keys=("lastConstituentsIndustriesOk", "lastConstituentsIndustriesTotal"))
        else:
            top = status.get("lastTopN") if isinstance(status, dict) else None
            targets = float(len(top)) if isinstance(top, list) else None
        # 三个 job 各自的最近运行时间
        job_specific_at = _first_str(
            status,
            keys=(
                {"market_pulse_inside": "lastInsideRefreshAt",
                 "market_pulse_close": "lastCloseSnapshotAt",
                 "market_pulse_constituents": "lastConstituentsAt"}.get(job_id, "lastLimitEmotionDailyAt"),
            ),
        )
        if last_run_at is None and job_specific_at is not None:
            last_run_at = job_specific_at
        # market_pulse_constituents 单独有 lastConstituentsOk
        if last_status_raw is None:
            ok = _first_num(status, keys=("lastConstituentsOk",))
            if ok is not None:
                last_status_raw = _normalize_status_from_bool(ok)
    elif job_id in {
        "market_overview_inside", "market_overview_close", "market_overview_warmup",
        "eltdx_overview_inside", "eltdx_overview_close", "eltdx_overview_warmup",
    }:
        # 共用 market_overview_scheduler. 标的数 = lastInside / lastClose / lastWarmup
        # 里的 stockCount / industryCount (eltdx snapshot 字段)
        slot_key = {
            "market_overview_inside": "lastInside",
            "market_overview_close": "lastClose",
            "market_overview_warmup": "lastWarmup",
            "eltdx_overview_inside": "lastInside",
            "eltdx_overview_close": "lastClose",
            "eltdx_overview_warmup": "lastWarmup",
        }.get(job_id)
        slot_obj = status.get(slot_key) if isinstance(status, dict) else None
        if isinstance(slot_obj, dict):
            # market_overview (akshare) 字段: tradingDate (1 天), 没标的数
            # eltdx_overview 字段: totalAmount, risingCount, fallingCount, stockCount, limitUpCount
            cand = (
                _first_num(slot_obj, keys=("stockCount", "stock_count")) or
                _first_num(slot_obj, keys=("risingCount", "rising_count")) or
                _first_num(slot_obj, keys=("industryCount", "industry_count"))
            )
            targets = cand
        if last_run_at is None:
            # 没 lastRunAt 但有 lastInsideRefreshAt / lastCloseSnapshotAt / lastWarmupAt
            slot_at_key = {
                "market_overview_inside": "lastInsideRefreshAt",
                "market_overview_close": "lastCloseSnapshotAt",
                "market_overview_warmup": "lastWarmupAt",
                "eltdx_overview_inside": "lastInsideRefreshAt",
                "eltdx_overview_close": "lastCloseSnapshotAt",
                "eltdx_overview_warmup": "lastWarmupAt",
            }.get(job_id)
            if slot_at_key:
                v = _first_str(status, keys=(slot_at_key,))
                if v is not None:
                    last_run_at = v
    elif job_id == "daily_eod_incremental":
        # 没有明确的"标的"概念. 用 lastMaxTradeDate / lastLimitEmotionMaxDate 计数
        # 这里 last_targets_processed 留 None (用 lastMaxTradeDate 在前端另算)
        targets = None
    elif job_id == "tdx_hsjday_download":
        targets = _first_num(config, status, keys=("lastDayFileCount",))
    elif job_id == "market_overview_daily":
        akshare = _first_num(config, status, keys=("lastAkshareUpserted",))
        eltdx = _first_num(config, status, keys=("lastEltdxUpserted",))
        sector_days = _first_num(config, status, keys=("lastSectorDays",))
        parts = [n for n in (akshare, eltdx, sector_days) if n is not None]
        targets = sum(parts) if parts else None
    elif job_id == "ths_industry_fund_flow_daily":
        rows = _first_num(config, status, keys=("lastRowsUpserted",))
        days = _first_num(config, status, keys=("lastDaysUpserted",))
        targets = rows if rows is not None else days
    elif job_id in {"risk_appetite_refresh", "ma_count_refresh", "volatility_sentiment_refresh"}:
        # risk_appetite / volatility_sentiment 有 lastRowsUpserted / lastCoverage
        # ma_count 有 lastMaUpserted + lastIrUpserted
        rows = _first_num(config, status, keys=("lastRowsUpserted",))
        ma = _first_num(config, status, keys=("lastMaUpserted",))
        ir = _first_num(config, status, keys=("lastIrUpserted",))
        cov = _first_num(config, status, keys=("lastCoverage"))
        parts = [n for n in (rows, ma, ir, cov) if n is not None]
        targets = sum(parts) if parts else None
    elif job_id in {
        "market_sentiment_index_refresh", "profit_effect_refresh",
        "style_risk_appetite_refresh",
    }:
        # 外部脚本 (subprocess 调 python -u scripts/...), 状态文件无 last_run 字段
        # targets 留 None, 前端显示 "—"
        targets = None
    elif job_id == "market_sentiment_chain_refresh":
        targets = _first_num(config, status, keys=("lastTargetsProcessed", "last_targets_processed"))
    # test_scheduler_demo 没有 status / config, 全部 None

    return {
        "last_run_at": last_run_at,
        "last_status": last_status_raw,
        "last_targets_processed": targets,
        "last_duration_seconds": last_duration,
        "last_error": last_error,
        "total_runs": int(total_runs) if total_runs is not None else None,
    }


def _supports_enable(job_id: str) -> bool:
    """application_analysis 没有全局 enabled（靠 per-target enabled），所以不暴露.

    market_pulse_* / market_overview_* / eltdx_overview_* 共用同一份 extra JSONB 里的
    enabled 字段，整组共用同一个开关；UI 上"禁用"对应整组停掉.
    """
    job_id = _canonical_job_id(job_id) or job_id
    return job_id in {
        'turnover_refresh', 'auction_ai_analysis', 'application_analysis',
        'stock_universe_refresh',
        'ths_industry_constituents_weekly', 'ths_industry_constituents_daily',
        'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents',
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
        'daily_eod_incremental',
        'market_sentiment_chain_refresh',
        'test_scheduler_demo',
    }


def _job_exists(job_id: str) -> bool:
    """Check if job is registered (alive, not soft-deleted) in app.scheduler_jobs."""
    try:
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            repo = SchedulerJobRepository(db)
            return any(repo.get_job_by_code(candidate) for candidate in _candidate_job_ids(job_id))
    except Exception:
        return False


def _get_live_status(job_id: str) -> dict[str, Any]:
    job_id = _canonical_job_id(job_id) or job_id
    if job_id == 'turnover_refresh':
        return get_turnover_scheduler_status()
    if job_id == 'auction_ai_analysis':
        return get_auction_analysis_scheduler_status()
    if job_id == 'application_analysis':
        return get_application_analysis_scheduler_status()
    if job_id == 'stock_universe_refresh':
        return get_stock_universe_scheduler_status()
    if job_id == 'ths_industry_constituents_weekly':
        return get_ths_industry_constituents_scheduler_status()
    if job_id == 'ths_industry_constituents_daily':
        return get_ths_industry_constituents_daily_scheduler_status()
    # market_pulse: 共用 market_pulse_scheduler 的状态
    if job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        return get_market_pulse_scheduler_status()
    # market_overview / eltdx overview: 共用 market_overview_scheduler 的状态
    if job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        return get_market_overview_scheduler_status()
    if job_id == 'daily_eod_incremental':
        return get_daily_eod_incremental_scheduler_status()
    if job_id == 'tdx_hsjday_download':
        return get_tdx_hsjday_download_scheduler_status()
    if job_id == 'market_overview_daily':
        return get_market_overview_daily_scheduler_status()
    if job_id == 'ths_industry_fund_flow_daily':
        return get_ths_industry_fund_flow_daily_scheduler_status()
    if job_id == 'market_sentiment_chain_refresh':
        return get_market_sentiment_chain_scheduler_status()
    if job_id == 'style_risk_appetite_refresh':
        return get_style_risk_appetite_scheduler_status()
    if job_id == 'profit_effect_refresh':
        return get_profit_effect_scheduler_status()
    if job_id == 'market_sentiment_index_refresh':
        return get_market_sentiment_index_scheduler_status()
    if job_id == 'ma_count_refresh':
        return get_ma_count_scheduler_status()
    if job_id == 'risk_appetite_refresh':
        return get_risk_appetite_scheduler_status()
    if job_id == 'volatility_sentiment_refresh':
        return get_volatility_sentiment_scheduler_status()
    if job_id == 'limit_emotion_refresh':
        return get_limit_emotion_scheduler_status()
    if job_id == 'sector_breadth_refresh':
        return get_sector_breadth_scheduler_status()
    if job_id == 'initial_backfill_refresh':
        return get_initial_backfill_scheduler_status()
    if job_id == 'qfq_reconciliation_refresh':
        return get_qfq_reconciliation_scheduler_status()
    if job_id == 'turnover_activity_refresh':
        return get_turnover_activity_scheduler_status()
    return {}


def _start_scheduler(job_id: str) -> None:
    job_id = _canonical_job_id(job_id) or job_id
    if job_id == 'turnover_refresh':
        start_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        start_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        start_application_analysis_scheduler()
    elif job_id == 'stock_universe_refresh':
        start_stock_universe_scheduler()
    elif job_id == 'ths_industry_constituents_weekly':
        start_ths_industry_constituents_scheduler()
    elif job_id == 'ths_industry_constituents_daily':
        start_ths_industry_constituents_daily_scheduler()
    elif job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        start_market_pulse_scheduler()
    elif job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        # market_overview scheduler 是一个整体, 启动/停止作用于所有 6 个 job
        # (start_market_overview_scheduler 是幂等的, 多次调用安全)
        start_market_overview_scheduler()
    elif job_id == 'daily_eod_incremental':
        start_daily_eod_incremental_scheduler()
    elif job_id == 'tdx_hsjday_download':
        start_tdx_hsjday_download_scheduler()
    elif job_id == 'market_overview_daily':
        start_market_overview_daily_scheduler()
    elif job_id == 'ths_industry_fund_flow_daily':
        start_ths_industry_fund_flow_daily_scheduler()
    elif job_id == 'market_sentiment_chain_refresh':
        start_market_sentiment_chain_scheduler()
    elif job_id == 'style_risk_appetite_refresh':
        start_style_risk_appetite_scheduler()
    elif job_id == 'profit_effect_refresh':
        start_profit_effect_scheduler()
    elif job_id == 'market_sentiment_index_refresh':
        start_market_sentiment_index_scheduler()
    elif job_id == 'ma_count_refresh':
        start_ma_count_scheduler()
    elif job_id == 'risk_appetite_refresh':
        start_risk_appetite_scheduler()
    elif job_id == 'volatility_sentiment_refresh':
        start_volatility_sentiment_scheduler()
    elif job_id == 'limit_emotion_refresh':
        start_limit_emotion_scheduler()
    elif job_id == 'sector_breadth_refresh':
        start_sector_breadth_scheduler()
    elif job_id == 'initial_backfill_refresh':
        start_initial_backfill_scheduler()
    elif job_id == 'qfq_reconciliation_refresh':
        start_qfq_reconciliation_scheduler()
    elif job_id == 'turnover_activity_refresh':
        start_turnover_activity_scheduler()


def _stop_scheduler(job_id: str) -> None:
    job_id = _canonical_job_id(job_id) or job_id
    if job_id == 'turnover_refresh':
        stop_turnover_scheduler()
    elif job_id == 'auction_ai_analysis':
        stop_auction_analysis_scheduler()
    elif job_id == 'application_analysis':
        stop_application_analysis_scheduler()
    elif job_id == 'stock_universe_refresh':
        stop_stock_universe_scheduler()
    elif job_id == 'ths_industry_constituents_weekly':
        stop_ths_industry_constituents_scheduler()
    elif job_id == 'ths_industry_constituents_daily':
        stop_ths_industry_constituents_daily_scheduler()
    elif job_id in {'market_pulse_inside', 'market_pulse_close', 'market_pulse_constituents'}:
        stop_market_pulse_scheduler()
    elif job_id in {
        'market_overview_inside', 'market_overview_close', 'market_overview_warmup',
        'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup',
    }:
        # 整体停掉 market_overview_scheduler (会暂停 APScheduler)
        stop_market_overview_scheduler()
    elif job_id == 'daily_eod_incremental':
        stop_daily_eod_incremental_scheduler()
    elif job_id == 'tdx_hsjday_download':
        stop_tdx_hsjday_download_scheduler()
    elif job_id == 'market_overview_daily':
        stop_market_overview_daily_scheduler()
    elif job_id == 'ths_industry_fund_flow_daily':
        stop_ths_industry_fund_flow_daily_scheduler()
    elif job_id == 'market_sentiment_chain_refresh':
        stop_market_sentiment_chain_scheduler()
    elif job_id == 'style_risk_appetite_refresh':
        stop_style_risk_appetite_scheduler()
    elif job_id == 'profit_effect_refresh':
        stop_profit_effect_scheduler()
    elif job_id == 'market_sentiment_index_refresh':
        stop_market_sentiment_index_scheduler()
    elif job_id == 'ma_count_refresh':
        stop_ma_count_scheduler()
    elif job_id == 'risk_appetite_refresh':
        stop_risk_appetite_scheduler()
    elif job_id == 'volatility_sentiment_refresh':
        stop_volatility_sentiment_scheduler()
    elif job_id == 'limit_emotion_refresh':
        stop_limit_emotion_scheduler()
    elif job_id == 'sector_breadth_refresh':
        stop_sector_breadth_scheduler()
    elif job_id == 'initial_backfill_refresh':
        stop_initial_backfill_scheduler()
    elif job_id == 'qfq_reconciliation_refresh':
        stop_qfq_reconciliation_scheduler()
    elif job_id == 'turnover_activity_refresh':
        stop_turnover_activity_scheduler()


def _trigger_scheduler(job_id: str, target_date: date | None = None) -> dict[str, Any]:
    """手动触发一次。返回 dict 给前端展示。

    整段包在 ``trigger_type("manual")`` context 里, 让所有子调用的 scheduler /
    record_run 都标记 trigger=manual, 区分 cron 自动跑和用户手动跑.
    """
    from backend.services.scheduler.job_history import trigger_type
    with trigger_type("manual"):
        return _trigger_scheduler_inner(_canonical_job_id(job_id) or job_id, target_date=target_date)


def _trigger_scheduler_inner(job_id: str, target_date: date | None = None) -> dict[str, Any]:
    job_id = _canonical_job_id(job_id) or job_id
    if job_id == 'turnover_refresh':
        sched = get_turnover_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'auction_ai_analysis':
        sched = get_auction_analysis_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'stock_universe_refresh':
        sched = get_stock_universe_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'application_analysis':
        targets = application_analysis_scheduler.trigger_all(source='settings_manual')
        if not targets:
            msg = '当前没有启用的标的，请在 application-analysis 页添加并启用至少一个标的'
            print(f'[scheduler] application_analysis trigger skipped: {msg}', flush=True)
            return {
                'ok': False,
                'items': [],
                'count': 0,
                'error': msg,
                'error_code': 'no_enabled_targets',
            }
        ok = all((r.get('ok') for r in targets))
        failed = [r for r in targets if not r.get('ok')]
        if failed:
            print(
                f'[scheduler] application_analysis trigger partial: '
                f'{len(failed)}/{len(targets)} failed, errors='
                f'{[r.get("error") for r in failed]}',
                flush=True,
            )
        return {
            'ok': ok,
            'items': targets,
            'count': len(targets),
            'failed_count': len(failed),
        }
    if job_id == 'ths_industry_constituents_weekly':
        sched = get_ths_industry_constituents_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    if job_id == 'ths_industry_constituents_daily':
        sched = get_ths_industry_constituents_daily_scheduler()
        if sched is None:
            return {'ok': False, 'error': 'scheduler not initialized'}
        return sched.trigger_now()
    # market_pulse_*: 三个 job 走同一 scheduler, trigger 时分别对应不同刷新动作
    if job_id == 'market_pulse_inside':
        return trigger_market_pulse_snapshot_now()
    if job_id == 'market_pulse_close':
        return trigger_market_pulse_close_snapshot_now()
    if job_id == 'market_pulse_constituents':
        return trigger_market_pulse_constituents_now()
    # market_overview_*  (fund-flow, eastmoney 数据源)
    if job_id in {'market_overview_inside', 'market_overview_close', 'market_overview_warmup'}:
        snap = run_market_overview_snapshot_now(force=True)
        if snap is None:
            return {'ok': False, 'error': 'fund-flow fetch failed (eastmoney unreachable?)'}
        return {
            'ok': True,
            'items': [snap],
            'count': 1,
            'failed_count': 0,
        }
    # eltdx_overview_*  (全A成交额/涨跌家数, eltdx 数据源)
    if job_id in {'eltdx_overview_inside', 'eltdx_overview_close', 'eltdx_overview_warmup'}:
        snap = capture_overview(force=True)
        if snap is None:
            return {'ok': False, 'error': 'eltdx fetch failed (TCP/TDX gateway unreachable?)'}
        return {
            'ok': True,
            'items': [snap],
            'count': 1,
            'failed_count': 0,
        }
    if job_id == 'daily_eod_incremental':
        return run_daily_eod_incremental_now(target_date=target_date)
    if job_id == 'tdx_hsjday_download':
        return run_tdx_hsjday_download_now(target_date=target_date)
    if job_id == 'market_overview_daily':
        return run_market_overview_daily_now(target_date=target_date)
    if job_id == 'ths_industry_fund_flow_daily':
        return run_ths_industry_fund_flow_daily_now(target_date=target_date)
    if job_id == 'market_sentiment_chain_refresh':
        return run_market_sentiment_chain_now(target_date=target_date)
    if job_id == 'style_risk_appetite_refresh':
        return run_style_risk_appetite_now(target_date=target_date)
    if job_id == 'profit_effect_refresh':
        return run_profit_effect_now(target_date=target_date)
    if job_id == 'market_sentiment_index_refresh':
        return run_market_sentiment_index_now(target_date=target_date)
    if job_id == 'ma_count_refresh':
        return run_ma_count_now(target_date=target_date)
    if job_id == 'risk_appetite_refresh':
        return run_risk_appetite_now(target_date=target_date)
    if job_id == 'volatility_sentiment_refresh':
        return run_volatility_sentiment_now(target_date=target_date)
    if job_id == 'limit_emotion_refresh':
        return run_limit_emotion_now(target_date=target_date)
    if job_id == 'sector_breadth_refresh':
        return run_sector_breadth_now(target_date=target_date)
    if job_id == 'initial_backfill_refresh':
        return run_initial_backfill_now(target_date=target_date)
    if job_id == 'qfq_reconciliation_refresh':
        return run_qfq_reconciliation_now(target_date=target_date)
    if job_id == 'turnover_activity_refresh':
        return run_turnover_activity_now(target_date=target_date)
    # test_scheduler_demo: 测试 entry, 没有对应 scheduler, trigger / start / stop 都返回错误
    if job_id == 'test_scheduler_demo':
        return {'ok': False, 'error': 'test_scheduler_demo 是测试 entry, 没有对应 scheduler 模块; 用来演示 jobs.json 注册表 CRUD'}
    return {'ok': False, 'error': f'unknown job_id {job_id}'}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/history', methods=['GET'])
def get_job_history(job_id: str):
    """读指定 job 的 history 列表 (新→旧, 限 limit 条, 默认 50, 上限 200).

    Response shape::

        {
            "ok": true,
            "job_id": "...",
            "items": [
                {
                    "start_at": "2026-06-20T17:00:12",
                    "end_at": "2026-06-20T17:01:30",
                    "trigger_type": "auto" | "manual",
                    "status": "success" | "failed" | "skipped" | "running" | "processing",
                    "error": "..." | null,
                    "duration_seconds": 78.4,
                    // application_analysis 还会带:
                    "target_count": 5,
                    "succeeded": 4,
                },
                ...
            ],
            "count": N,
            "error": "...",  // 仅失败时
        }
    """
    from backend.services.scheduler.job_history import get_history
    try:
        limit = int(request.args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    if not _job_exists(job_id):
        return jsonify({"ok": False, "error": f"unknown job_id: {job_id}"}), 404
    try:
        items = get_history(job_id, limit=limit)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "items": items,
        "count": len(items),
    })


@scheduler_bp.route('/api/scheduler/stats/daily', methods=['GET'])
def daily_stats():
    """近 N 天每天 run_history 聚合 (按 status 分类).

    Query param ``days`` (默认 14, 最大 90).

    Response::

        {
            "ok": true,
            "items": [
                {"date": "2026-06-07", "total": 5, "success": 4, "failed": 1, "skipped": 0},
                ...
            ],
            "summary": {
                "total": 42,
                "failed": 3,
                "success_rate": 0.93
            }
        }
    """
    days = request.args.get("days", 14, type=int)
    days = max(1, min(days, 90))

    try:
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            items = SchedulerJobRepository(db).daily_stats(days=days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_stats DB read failed: %s", exc)
        return jsonify({"ok": True, "items": [], "summary": {"total": 0, "failed": 0, "success_rate": 1.0}})

    total = sum(it["total"] for it in items)
    failed = sum(it["failed"] for it in items)
    success_rate = round((total - failed) / total, 4) if total > 0 else 1.0

    return jsonify({
        "ok": True,
        "items": items,
        "summary": {"total": total, "failed": failed, "success_rate": success_rate},
    })


@scheduler_bp.route('/api/scheduler/categories', methods=['GET'])
def list_categories():
    """列出所有 job category + 每类 job 数.

    给前端 /settings/scheduler 渲染 tab 用, 不用在前端硬编码 CATEGORY_TABS.
    数据来源: Postgres ``app.scheduler_job_categories`` JOIN
    ``app.scheduler_job_category_mappings``. DB 连不上时回退到 ``JOB_CATEGORIES`` +
    ``JOB_CATEGORY_MAP``.

    Response shape::

        {
            "ok": true,
            "items": [
                {"id": 1, "label": "盘内实时", "icon_hint": "activity",
                 "sort_order": 10, "description": "...", "count": 10},
                ...
            ],
            "count": N
        }
    """
    try:
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            items = SchedulerJobRepository(db).list_categories_with_counts()
        return jsonify({'ok': True, 'items': items, 'count': len(items)})
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "list_categories DB read failed, fallback to JOB_CATEGORIES: %s", exc,
        )
        counts: dict[int, int] = {}
        for cats in JOB_CATEGORY_MAP.values():
            for cid in cats:
                counts[cid] = counts.get(cid, 0) + 1
        items = []
        for cid, meta in enumerate(JOB_CATEGORIES, start=1):
            items.append({
                'id': cid,
                'label': meta.label,
                'icon_hint': meta.icon_hint,
                'sort_order': meta.sort_order,
                'description': meta.description,
                'count': counts.get(cid, 0),
            })
        return jsonify({'ok': True, 'items': items, 'count': len(items)})


@scheduler_bp.route('/api/scheduler/jobs', methods=['GET'])
def list_jobs():
    """列出所有 job + 各自 config + 实时 status.

    Response shape::

        {
            "ok": true,
            "items": [
                {
                    "id": "...",
                    "name": "...",
                    "description": "...",
                    "config_file": "...",
                    "service_module": "...",
                    "service_class": "...",
                    "registered_at": "...",
                    "supports_enable": true|false,
                    "enabled": true|false,            // 注册表里的开关
                    "config_enabled": true|false,     // extra JSONB 里的 enabled（控制调度器是否启动）
                    "config": { ... },                // 整个 extra JSONB 内容
                    "live": { ... },                  // scheduler.status() 的实时返回值
                },
                ...
            ]
        }
    """
    try:
        sync_job_descriptions()
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            registry_entries = SchedulerJobRepository(db).list_jobs()
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'DB read failed: {exc}'}), 500

    items: list[dict[str, Any]] = []
    for entry in registry_entries:
        raw_job_id = entry.get('id')
        job_id = _canonical_job_id(raw_job_id)
        if not job_id:
            continue

        config = load_status(job_id) or load_status(raw_job_id) or {}
        try:
            live = _get_live_status(job_id)
        except Exception as exc:
            live = {'error': f'get live status failed: {exc}'}

        categories_value = entry.get('_category_ids') or []
        category_sort_orders = entry.get('_category_sort_orders') or {}
        enabled_in_registry = bool(entry.get('enabled', True))
        config_enabled = config.get('enabled') if config else None
        # 对于 application_analysis 来说，没有独立 config；显示 live.running 即可
        if job_id == 'application_analysis':
            config_enabled = enabled_in_registry

        # 不要把内部字段漏到 API 响应里
        entry_for_response = {
            k: v for k, v in entry.items()
            if k not in ('_category_ids', '_category_sort_orders')
        }
        entry_for_response['id'] = job_id

        items.append({
            **entry_for_response,
            'supports_enable': _supports_enable(job_id) and job_id not in MARKET_SENTIMENT_COMPONENT_JOB_IDS,
            'categories': categories_value,
            'categorySortOrders': category_sort_orders,
            'enabled': enabled_in_registry,
            'config_enabled': bool(config_enabled) if config_enabled is not None else True,
            'config': config,
            'live': live,
            'last_run': _normalize_last_run(job_id, live or {}, config or {}),
        })

    return jsonify({'ok': True, 'items': items, 'count': len(items)})


@scheduler_bp.route('/api/scheduler/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    try:
        sync_job_descriptions()
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            repo = SchedulerJobRepository(db)
            entry = None
            for candidate in _candidate_job_ids(job_id):
                entry = repo.get_job_by_code(candidate)
                if entry is not None:
                    break
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'DB read failed: {exc}'}), 500

    if entry is None:
        return jsonify({'ok': False, 'error': f'job {job_id} not registered'}), 404

    canonical_job_id = _canonical_job_id(job_id) or job_id
    config = load_status(canonical_job_id) or load_status(job_id) or {}
    live = _get_live_status(canonical_job_id)
    categories_value = entry.get('_category_ids') or []
    category_sort_orders = entry.get('_category_sort_orders') or {}
    entry_for_response = {
        k: v for k, v in entry.items()
        if k not in ('_category_ids', '_category_sort_orders')
    }
    entry_for_response['id'] = canonical_job_id
    return jsonify({
        'ok': True,
        'item': {
            **entry_for_response,
            'supports_enable': _supports_enable(canonical_job_id) and canonical_job_id not in MARKET_SENTIMENT_COMPONENT_JOB_IDS,
            'categories': categories_value,
            'categorySortOrders': category_sort_orders,
            'enabled': bool(entry.get('enabled', True)),
            'config_enabled': bool(config.get('enabled', True)) if canonical_job_id != 'application_analysis' else True,
            'config': config,
            'live': live,
            'last_run': _normalize_last_run(canonical_job_id, live or {}, config or {}),
        },
    })


def _flip_enabled(job_id: str, enabled: bool) -> dict[str, Any]:
    canonical_job_id = _canonical_job_id(job_id) or job_id
    if not _supports_enable(canonical_job_id):
        return {'ok': False, 'error': f'job {canonical_job_id} does not support enable/disable toggle'}

    enabled_bool = bool(enabled)

    # 直接 UPDATE is_enabled 列, 不动 extra JSONB (避免全量替换导致数据丢失).
    # save_status() 会走 UPSERT + ON CONFLICT DO UPDATE, set_ 包含 extra,
    # 若传入的 config 只有少数 key 会把 extra 写回成残缺的 dict.
    status_updated = False
    try:
        from backend.config.database import session_scope
        from backend.models.scheduler import SchedulerJob, SchedulerJobStatus
        from sqlalchemy import func, select, update

        with session_scope() as db:
            job_uuid = db.execute(
                select(SchedulerJob.id).where(
                    SchedulerJob.code.in_(_candidate_job_ids(job_id)),
                    SchedulerJob.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if job_uuid is not None:
                result = db.execute(
                    update(SchedulerJobStatus)
                    .where(
                        SchedulerJobStatus.job_id == job_uuid,
                        SchedulerJobStatus.deleted_at.is_(None),
                    )
                    .values(is_enabled=enabled_bool, updated_at=func.now())
                )
                db.flush()
                status_updated = result.rowcount > 0
            else:
                logger.warning(
                    "_flip_enabled(%s): job not found in app.scheduler_jobs, "
                    "skipping status update", canonical_job_id,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "_flip_enabled(%s): failed to update app.scheduler_job_statuses.is_enabled: %s",
            canonical_job_id, exc,
        )

    # 同时更新 scheduler_jobs.is_enabled (UI 注册表开关)
    try:
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            repo = SchedulerJobRepository(db)
            for candidate in _candidate_job_ids(job_id):
                if repo.set_enabled_by_code(candidate, enabled_bool):
                    break
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_flip_enabled(%s) DB is_enabled sync skipped: %s",
            canonical_job_id, exc,
        )

    # 如果两个 DB 操作都失败了, 仍在前端提示成功 (start/stop 是进程内操作, DB 状态是辅助)
    if not status_updated:
        logger.warning(
            "_flip_enabled(%s): neither scheduler_jobs nor scheduler_job_statuses "
            "was updated; start/stop may fail on next bootstrap", canonical_job_id,
        )

    return {'ok': True, 'job_id': canonical_job_id, 'enabled': enabled_bool, 'status_updated': status_updated}


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/enable', methods=['POST'])
def enable_job(job_id: str):
    if not _supports_enable(job_id):
        return jsonify({'ok': False, 'error': f'job {job_id} does not support enable/disable toggle'}), 400
    canonical_job_id = _canonical_job_id(job_id) or job_id
    if canonical_job_id in MARKET_SENTIMENT_COMPONENT_JOB_IDS:
        return jsonify({'ok': False, 'error': f'job {canonical_job_id} is manual-only; enable market_sentiment_chain_refresh instead'}), 400
    try:
        _flip_enabled(job_id, True)
        _start_scheduler(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/disable', methods=['POST'])
def disable_job(job_id: str):
    if not _supports_enable(job_id):
        return jsonify({'ok': False, 'error': f'job {job_id} does not support enable/disable toggle'}), 400
    canonical_job_id = _canonical_job_id(job_id) or job_id
    if canonical_job_id in MARKET_SENTIMENT_COMPONENT_JOB_IDS:
        return jsonify({'ok': False, 'error': f'job {canonical_job_id} is manual-only; disable market_sentiment_chain_refresh instead'}), 400
    try:
        _stop_scheduler(job_id)
        _flip_enabled(job_id, False)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/trigger', methods=['POST'])
def trigger_job(job_id: str):
    if not _job_exists(job_id):
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    try:
        payload = request.get_json(silent=True) or {}
        raw_target_date = payload.get("target_date") or payload.get("targetDate")
        try:
            target_date = normalize_target_date(raw_target_date)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        result = _trigger_scheduler(job_id, target_date=target_date)
        # 兼容前端 notification 组件: 把 count/failed_count 提升到顶层.
        # application_analysis 的 result 自带 count/failed_count;
        # stock_universe / turnover / auction 的 result 是 status 形态, 这里兜底算 1.
        if "count" in result:
            top_count = result["count"]
            top_failed = result.get("failed_count", 0)
        else:
            top_count = 1
            top_failed = 0 if result.get("status") == "success" else 1
        return jsonify({
            "ok": True,
            "job_id": job_id,
            "target_date": target_date.isoformat() if target_date else None,
            "count": top_count,
            "failed_count": top_failed,
            "result": result,
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/start', methods=['POST'])
def start_job(job_id: str):
    if not _job_exists(job_id):
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    canonical_job_id = _canonical_job_id(job_id) or job_id
    if canonical_job_id in MARKET_SENTIMENT_COMPONENT_JOB_IDS:
        return jsonify({'ok': False, 'error': f'job {canonical_job_id} is manual-only; use market_sentiment_chain_refresh for automatic scheduling'}), 400
    try:
        _flip_enabled(job_id, True)
        _start_scheduler(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>/stop', methods=['POST'])
def stop_job(job_id: str):
    if not _job_exists(job_id):
        return jsonify({'ok': False, 'error': f'unknown job_id: {job_id}'}), 404
    try:
        _flip_enabled(job_id, False)
        _stop_scheduler(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'status': _get_live_status(job_id)})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@scheduler_bp.route('/api/scheduler/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id: str):
    """从 DB 软删一个 job (同时停掉运行中的调度器线程).

    前端 /settings/scheduler 页面 "删除" 按钮用.
    """
    # 1) 先尝试停掉运行中的调度器 (不抛错, 失败也不影响删除)
    try:
        _stop_scheduler(job_id)
    except Exception as exc:
        traceback.print_exc()
        logger.warning("delete_job: stop scheduler for %s failed: %s", job_id, exc)

    # 2) DB 软删 (deleted_at = now)
    try:
        from backend.config.database import session_scope
        from backend.repositories.scheduler import SchedulerJobRepository

        with session_scope() as db:
            removed = SchedulerJobRepository(db).soft_delete_by_code(job_id)
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'DB soft-delete failed: {exc}'}), 500

    if not removed:
        return jsonify({'ok': False, 'error': f'job {job_id} not found in registry'}), 404

    logger.info("delete_job: soft-deleted %s from app.scheduler_jobs", job_id)
    return jsonify({'ok': True, 'job_id': job_id, 'removed': 1})
