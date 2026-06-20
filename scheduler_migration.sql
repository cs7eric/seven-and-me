-- ============================================================
-- scheduler_migration.sql (refactored per /sql skill spec)
-- ============================================================
-- 把 scheduler/jobs.json (注册表) + scheduler/<job_id>_job.json
-- (每 job 状态/历史) 从文件迁到 Postgres. 跑完后再切代码.
--
-- 目标库: postgres@127.0.0.1:25432/postgres
-- 用法:   psql -h 127.0.0.1 -p 25432 -U postgres -d postgres -f scheduler_migration.sql
--         或直接进 pgAdmin / DBeaver 跑
--
-- 重构要点 (相对前一版):
--   1. 全部表迁到 app schema (skill §8)
--   2. 主键全改 uuid + code varchar(64) UNIQUE alive (skill §11, §21)
--      原 jobs.json 的 id 字段保留为 code, 不再做 PK
--   3. 去掉所有物理 FOREIGN KEY (skill §20: 默认不加物理 FK, 用 xxx_id 表达关联)
--   4. deleted_at 软删除字段 + 部分唯一索引 (skill §13, §21)
--   5. updated_at 自动触发器 + app.set_updated_at() (skill §23)
--   6. status varchar(32) + CHECK (skill §18)
--   7. jsonb 加 GIN partial 索引 (skill §22)
--   8. mapping 表 (xxx_id, yyy_id) 走部分唯一索引 (skill §25.3)
--   9. 数值字段加精度 numeric(12,3) (skill §14)
--  10. 字段名规范化:
--        start_at  -> started_at
--        end_at    -> ended_at
--        error     -> error_message
--        running   -> is_running
--  11. 字典表加 code (intraday / ai / data_collection / eod_backfill / composite / test)
--
-- 幂等: CREATE IF NOT EXISTS + ON CONFLICT DO NOTHING, 重跑安全.
--
-- 注意 (相对前一版的兼容性变化):
--   - 表名带 app. 前缀, 跟旧 public.scheduler_* 不冲突, 但应用层切换前必须
--     先确认旧 public.scheduler_* 已下线或不会同时被读.
--   - scheduler_jobs.id 不再是 TEXT ('turnover_refresh'), 改 uuid, 业务标识走 code.
--     应用层需要按 code (string) 做 join, 不要按 id.
--   - status 字典从后端 JOB_CATEGORIES list 改成 DB 持久化, mapping 表自动 join.
--     但前端 tab 仍依赖 API 返回的 category, 字典变更不影响前端代码.
--   - 已知边界 (沿用前一版):
--       3 个隐式 job (risk_appetite / ma_count / volatility_sentiment) 没在
--       jobs.json 注册, 仅被 daily_eod pipeline 触发, 不进 scheduler_jobs.
--       他们的 status JSON 在本次迁移里丢弃. 后续若想统一管理, 加进 jobs.json 即可.
-- ============================================================

BEGIN;

-- ============================================================
-- §A. Required initialization (skill §3)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS app;

CREATE OR REPLACE FUNCTION app.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- 1. app.scheduler_jobs
--    替代 scheduler/jobs.json. 注册表 (master data).
-- ============================================================
-- 与 scheduler_job_statuses 拆表依据 (skill §25.1):
--   - 注册字段很少改, 运行时状态每跑都改, 生命周期不同
--   - 结构高频变 (status JSON 字段差异大, 拆表后 extra jsonb 自由发挥)
-- is_enabled 仅做运行时开关, 不引入冗余的 status 字段 (skill §24: 不用就不留).

CREATE TABLE IF NOT EXISTS app.scheduler_jobs (
    id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    code            varchar(64)  NOT NULL,
    name            varchar(128) NOT NULL,
    description     text,
    service_module  varchar(128),
    service_class   varchar(128),
    config_file     varchar(255),
    is_enabled      boolean      NOT NULL DEFAULT true,
    registered_at   timestamptz,
    extra           jsonb        NOT NULL DEFAULT '{}'::jsonb,
    remark          text,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE UNIQUE INDEX uk_scheduler_jobs_code_alive
    ON app.scheduler_jobs (code)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_jobs_enabled
    ON app.scheduler_jobs (is_enabled)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_jobs_extra_gin
    ON app.scheduler_jobs USING gin (extra)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_scheduler_jobs_updated_at
    BEFORE UPDATE ON app.scheduler_jobs
    FOR EACH ROW
    EXECUTE FUNCTION app.set_updated_at();

COMMENT ON TABLE  app.scheduler_jobs                       IS 'Scheduler 注册表 (替代 scheduler/jobs.json). 每个 job 一行, 字段很少改.';
COMMENT ON COLUMN app.scheduler_jobs.code                  IS '业务标识, 原 jobs.json 的 id 字段 (e.g. turnover_refresh). UNIQUE alive.';
COMMENT ON COLUMN app.scheduler_jobs.service_module        IS 'Python 模块路径, 例: backend.services.scheduler.turnover_scheduler.';
COMMENT ON COLUMN app.scheduler_jobs.service_class         IS 'Python 类名, 例: TurnoverRefreshScheduler.';
COMMENT ON COLUMN app.scheduler_jobs.config_file           IS '该 job 的配置文件相对路径 (相对项目根), 例: turnover_job.json. 空字符串表示无配置.';
COMMENT ON COLUMN app.scheduler_jobs.is_enabled            IS '运行时开关. false 时 scheduler 跳过本 job.';
COMMENT ON COLUMN app.scheduler_jobs.extra                 IS '异构扩展字段, 例如 service_kwargs / next_run_time.';


-- ============================================================
-- 2. app.scheduler_job_statuses
--    替代 scheduler/<job_id>_job.json. 每 job 一行的运行时状态.
-- ============================================================
-- 1:1 detail (skill §25.1). 用 UNIQUE INDEX (job_id) WHERE deleted_at IS NULL 表达.
-- 不加物理 FK, 由应用层保证 job_id 指向有效 scheduler_jobs.id (skill §20).

CREATE TABLE IF NOT EXISTS app.scheduler_job_statuses (
    id                      uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  uuid         NOT NULL,
    is_enabled              boolean      NOT NULL DEFAULT true,
    is_running              boolean      NOT NULL DEFAULT false,
    schedule                jsonb        NOT NULL DEFAULT '{}'::jsonb,
    timezone_offset_hours   integer,
    tick_seconds            integer,
    last_run_at             timestamptz,
    last_run_ok             boolean,
    last_run_status         varchar(32),
    last_run_error_message  text,
    last_duration_seconds   numeric(12,3),
    last_targets_processed  integer,
    total_runs              integer      NOT NULL DEFAULT 0,
    total_failures          integer      NOT NULL DEFAULT 0,
    scheduler_started_at    timestamptz,
    stopped_at              timestamptz,
    extra                   jsonb        NOT NULL DEFAULT '{}'::jsonb,
    remark                  text,
    created_at              timestamptz  NOT NULL DEFAULT now(),
    updated_at              timestamptz  NOT NULL DEFAULT now(),
    deleted_at              timestamptz,

    CONSTRAINT ck_scheduler_job_statuses_last_run_status CHECK (
        last_run_status IS NULL
        OR last_run_status IN ('pending', 'running', 'success', 'failed', 'skipped')
    ),
    CONSTRAINT ck_scheduler_job_statuses_total CHECK (
        total_runs >= 0
        AND total_failures >= 0
        AND total_failures <= total_runs
    ),
    CONSTRAINT ck_scheduler_job_statuses_duration CHECK (
        last_duration_seconds IS NULL OR last_duration_seconds >= 0
    )
);

CREATE UNIQUE INDEX uk_scheduler_job_statuses_job_alive
    ON app.scheduler_job_statuses (job_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_job_statuses_last_run_at
    ON app.scheduler_job_statuses (last_run_at DESC NULLS LAST)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_job_statuses_extra_gin
    ON app.scheduler_job_statuses USING gin (extra)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_scheduler_job_statuses_updated_at
    BEFORE UPDATE ON app.scheduler_job_statuses
    FOR EACH ROW
    EXECUTE FUNCTION app.set_updated_at();

COMMENT ON TABLE  app.scheduler_job_statuses                          IS '每 job 的运行时状态 (替代 scheduler/<id>_job.json). 高频写, 与注册表拆开 (skill §25.1).';
COMMENT ON COLUMN app.scheduler_job_statuses.job_id                   IS '逻辑外键 -> app.scheduler_jobs.id. 不加物理 FK (skill §20).';
COMMENT ON COLUMN app.scheduler_job_statuses.last_run_status          IS '上次执行结果状态. 见 ck_scheduler_job_statuses_last_run_status.';
COMMENT ON COLUMN app.scheduler_job_statuses.last_run_ok               IS 'Denormalized snapshot: last_run_status IN (success, skipped). 用于前端快速过滤 (skill §28 allowed denormalization).';
COMMENT ON COLUMN app.scheduler_job_statuses.last_run_error_message   IS '上次执行失败的错误文本. 成功或跳过时为 NULL.';
COMMENT ON COLUMN app.scheduler_job_statuses.extra                     IS '异构扩展, 例如 market_pulse 的 lastTopN / market_overview 的 lastInside. 注意: 旧 status JSON 用 camelCase key (lastRunAt / lastRunOk), 新代码接入时需自行转换.';


-- ============================================================
-- 3. app.scheduler_job_run_history
--    替代每 status JSON 顶层 history[]. append-only record (skill §29.8).
-- ============================================================
-- 不带 updated_at (append-only, skill §12). 不带 deleted_at (审计用, 不应删).
-- UNIQUE 走完整约束 (无 deleted_at, 用普通 UNIQUE).

CREATE TABLE IF NOT EXISTS app.scheduler_job_run_history (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id           uuid         NOT NULL,
    started_at       timestamptz  NOT NULL,
    ended_at         timestamptz  NOT NULL,
    trigger_type     varchar(32)  NOT NULL,
    status           varchar(32)  NOT NULL,
    error_message    text,
    duration_seconds numeric(12,3),
    remark           text,
    created_at       timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT ck_scheduler_job_run_history_trigger CHECK (
        trigger_type IN ('auto', 'manual')
    ),
    CONSTRAINT ck_scheduler_job_run_history_status CHECK (
        status IN ('success', 'failed', 'skipped', 'running')
    ),
    CONSTRAINT ck_scheduler_job_run_history_time_range CHECK (
        ended_at >= started_at
    ),
    CONSTRAINT ck_scheduler_job_run_history_duration CHECK (
        duration_seconds IS NULL OR duration_seconds >= 0
    ),

    CONSTRAINT uk_scheduler_job_run_history_natural UNIQUE (job_id, started_at, trigger_type)
);

CREATE INDEX idx_scheduler_job_run_history_job_started
    ON app.scheduler_job_run_history (job_id, started_at DESC);

CREATE INDEX idx_scheduler_job_run_history_status
    ON app.scheduler_job_run_history (status)
    WHERE status IN ('failed', 'running');

COMMENT ON TABLE  app.scheduler_job_run_history             IS '每 job 每次执行的明细记录 (替代 status JSON 顶层 history[]). append-only, 不支持软删.';
COMMENT ON COLUMN app.scheduler_job_run_history.job_id      IS '逻辑外键 -> app.scheduler_jobs.id. 不加物理 FK (skill §20).';
COMMENT ON COLUMN app.scheduler_job_run_history.trigger_type IS 'auto = scheduler 定时触发; manual = 人工/API 触发.';


-- ============================================================
-- 4. app.scheduler_job_categories
--    分类字典 (替代 backend/api/scheduler.py 的 JOB_CATEGORIES list).
-- ============================================================
-- Dictionary table (skill §29.5). 加 code (intraday / ai / ...) 作业务标识,
--   label 允许重命名, code UNIQUE alive 防止重名.
-- 保留 status 字段, 用于停用某个 category (不下线, 只隐藏).

CREATE TABLE IF NOT EXISTS app.scheduler_job_categories (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    code        varchar(64)  NOT NULL,
    label       varchar(128) NOT NULL,
    icon_hint   varchar(64),
    sort_order  integer      NOT NULL DEFAULT 0,
    description text,
    status      varchar(32)  NOT NULL DEFAULT 'active',
    remark      text,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    deleted_at  timestamptz,

    CONSTRAINT ck_scheduler_job_categories_status CHECK (
        status IN ('active', 'disabled')
    )
);

CREATE UNIQUE INDEX uk_scheduler_job_categories_code_alive
    ON app.scheduler_job_categories (code)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_job_categories_sort
    ON app.scheduler_job_categories (sort_order)
    WHERE deleted_at IS NULL AND status = 'active';

CREATE TRIGGER trg_scheduler_job_categories_updated_at
    BEFORE UPDATE ON app.scheduler_job_categories
    FOR EACH ROW
    EXECUTE FUNCTION app.set_updated_at();

COMMENT ON TABLE  app.scheduler_job_categories            IS 'Scheduler 分类字典 (替代 backend/api/scheduler.py 的 JOB_CATEGORIES list).';
COMMENT ON COLUMN app.scheduler_job_categories.code       IS '业务标识 (e.g. intraday / ai / data_collection / eod_backfill / composite / test). UNIQUE alive.';
COMMENT ON COLUMN app.scheduler_job_categories.icon_hint  IS '前端图标 hint, 例如 activity / sparkles / database. 前端 ICON_MAP 映射.';
COMMENT ON COLUMN app.scheduler_job_categories.sort_order IS 'tab 渲染顺序, 升序. 同 sort_order 时按 id 稳定排序.';


-- ============================================================
-- 5. app.scheduler_job_category_mappings
--    job ↔ category 多对多. 当前每个 job 只属 1 个 category, 保留扩展空间.
-- ============================================================
-- Mapping table (skill §25.3). 不加 sort_order (当前无序需求, skill §24).

CREATE TABLE IF NOT EXISTS app.scheduler_job_category_mappings (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      uuid         NOT NULL,
    category_id uuid         NOT NULL,
    remark      text,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    deleted_at  timestamptz
);

CREATE UNIQUE INDEX uk_scheduler_job_category_mappings_alive
    ON app.scheduler_job_category_mappings (job_id, category_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_job_category_mappings_job
    ON app.scheduler_job_category_mappings (job_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_scheduler_job_category_mappings_category
    ON app.scheduler_job_category_mappings (category_id)
    WHERE deleted_at IS NULL;

CREATE TRIGGER trg_scheduler_job_category_mappings_updated_at
    BEFORE UPDATE ON app.scheduler_job_category_mappings
    FOR EACH ROW
    EXECUTE FUNCTION app.set_updated_at();

COMMENT ON TABLE app.scheduler_job_category_mappings IS 'job ↔ category 多对多. 当前 1:1, 保留扩展.';


-- ============================================================
-- 6. Data: app.scheduler_jobs  (23 条, 从 scheduler/jobs.json)
-- ============================================================
-- 显式写 code (原 jobs.json 的 id), uuid 由 DEFAULT gen_random_uuid() 自动生成.
-- ON CONFLICT 必须显式带 WHERE 子句匹配 partial unique index, 否则推断不到.

INSERT INTO app.scheduler_jobs
    (code, name, description, config_file, service_module, service_class, is_enabled, registered_at)
VALUES
    ('turnover_refresh',                       '换手率刷新',                              '工作日盘内每半小时 (09:30-15:00) + 16:00 收盘后刷新换手率',                                                                              'turnover_job.json',                       'backend.services.scheduler.turnover_scheduler',                       'TurnoverRefreshScheduler',          TRUE, '2026-06-08T20:20:00+08:00'),
    ('stock_universe_refresh',                 'A 股全市场持久化',                        '工作日 17:00 拉全 A 股行情 + 题材 + 行业归一, 持久化到 reference/stock-universe/',                                                    'stock_universe_job.json',                 'backend.services.scheduler.stock_universe_scheduler',                 'StockUniverseRefreshScheduler',    TRUE, '2026-06-08T20:20:00+08:00'),
    ('auction_ai_analysis',                    '集合竞价 AI 分析',                        '工作日 09:26 后对 enabled 标的生成集合竞价 AI 解读',                                                                                    'auction_analysis_job.json',               'backend.services.scheduler.auction_analysis_scheduler',                'AuctionAnalysisScheduler',          TRUE, '2026-06-08T20:20:00+08:00'),
    ('ths_industry_constituents_weekly',       '同花顺 90 行业成分股 (每周六 hexin-v 重爬)', '每周六 18:00 全量重爬 90 行业成分股',                                                                                                'ths_industry_constituents_job.json',      'backend.services.scheduler.ths_industry_constituents_scheduler',      'ThsIndustryConstituentsScheduler',  TRUE, '2026-06-08T20:20:00+08:00'),
    ('ths_industry_constituents_daily',        '同花顺 90 行业成分股 (每个交易日 17:00 收盘后 hexin-v 抓快照)', '每个交易日 17:00 全量重爬 90 行业成分股',                                                                       'ths_industry_constituents_daily_job.json', 'backend.services.scheduler.ths_industry_constituents_daily_scheduler', 'ThsIndustryConstituentsDailyScheduler', TRUE, '2026-06-10T22:30:00+08:00'),
    ('application_analysis',                   '个股应用分析',                            '对 enabled 标的按 interval_minutes 节奏生成 AI 分析 + 盘后 15:30 跑 recent30',                                                        'reference/application-analysis/scheduler.json', 'backend.services.stock.application_analysis_scheduler',         'ApplicationAnalysisScheduler',      TRUE, '2026-06-08T20:20:00+08:00'),
    ('market_pulse_inside',                    'market_pulse_inside_refresh (10min)',     'market_pulse_scheduler 调度, 交易时间内每 10 分钟跑 snapshot_today_rotation(top_n=10)',                                              'market_pulse_job.json',                   'backend.services.scheduler.market_pulse_scheduler',                   'MarketPulseScheduler',              TRUE, '2026-06-08T20:20:47+08:00'),
    ('market_pulse_close',                     'market_pulse_close_snapshot (15:30)',     'market_pulse_scheduler 调度, 每个交易日 15:30 强制落盘当日完整 Top 10 + 涨跌停 daily',                                               'market_pulse_job.json',                   'backend.services.scheduler.market_pulse_scheduler',                   'MarketPulseScheduler',              TRUE, '2026-06-08T20:20:47+08:00'),
    ('market_pulse_constituents',              'market_pulse_constituents_refresh (15:35)','market_pulse_scheduler 调度, 每个交易日 15:35 拉 90 行业全量成分股',                                                                'market_pulse_job.json',                   'backend.services.scheduler.market_pulse_scheduler',                   'MarketPulseScheduler',              TRUE, '2026-06-08T20:20:47+08:00'),
    ('market_overview_inside',                 'market_overview_inside_refresh (5min)',   'market_overview_scheduler 调度, 交易时间内每 5 分钟拉 akshare fund-flow snapshot',                                                   'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:10:00+08:00'),
    ('market_overview_close',                  'market_overview_close_snapshot (15:35)',  'market_overview_scheduler 调度, 每个交易日 15:35 强制拉一次 fund-flow snapshot 并归档',                                              'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:10:00+08:00'),
    ('market_overview_warmup',                 'market_overview_warmup (09:00 开盘前)',   'market_overview_scheduler 调度, 每个交易日 09:00 开盘前 warmup 强制拉一次 fund-flow',                                                 'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:10:00+08:00'),
    ('eltdx_overview_inside',                  'eltdx_overview_inside (5min)',            'market_overview_scheduler 调度, 交易时间内每 5 分钟跑 capture_overview (eltdx gateway)',                                              'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:10:00+08:00'),
    ('eltdx_overview_close',                   'eltdx_overview_close (15:35)',            'market_overview_scheduler 调度, 每个交易日 15:35 强制跑 capture_overview',                                                            'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:26:00+08:00'),
    ('eltdx_overview_warmup',                  'eltdx_overview_warmup (09:00 开盘前)',    'market_overview_scheduler 调度, 每个交易日 09:00 开盘前 warmup force 跑 capture_overview',                                            'market_overview_job.json',                'backend.services.scheduler.market_overview_scheduler',                'MarketOverviewScheduler',           TRUE, '2026-06-13T14:26:00+08:00'),
    ('tdx_hsjday_download',                    'TDX hsjday.zip 下载 + 覆盖 (16:30 工作日)','工作日 16:30 下载 hsjday.zip, 解压, 备份旧 reference/tdx/day/hsjday, mv 新 hsjday 覆盖',                                            'tdx_hsjday_download_job.json',            'backend.services.scheduler.tdx_hsjday_download_scheduler',            'TdxHsjdayDownloadScheduler',        TRUE, '2026-06-17T22:00:00+08:00'),
    ('daily_eod_incremental',                  '每日 EOD 增量入 duckdb (17:00 工作日)',   '工作日 17:00 增量入 duckdb (daily_raw + limit_emotion_summary), 缺则跑 initial_backfill.py 全量补',                                    'daily_eod_incremental_job.json',          'backend.services.scheduler.daily_eod_incremental_scheduler',          'DailyEodIncrementalScheduler',      TRUE, '2026-06-17T21:00:00+08:00'),
    ('market_overview_daily',                  '大盘概况 / 行业 90 回填 duckdb (17:10)','工作日 17:10 把 akshare 资金流 + 90 行业 涨跌幅/流入流出 全部 upsert 到 duckdb',                                                       'market_overview_daily_job.json',          'backend.services.scheduler.market_overview_daily_scheduler',          'MarketOverviewDailyScheduler',      TRUE, '2026-06-17T22:00:00+08:00'),
    ('ths_industry_fund_flow_daily',           '同花顺 90 行业资金流回填 duckdb (17:15)','工作日 17:15 把同花顺 90 行业资金流 upsert 到 duckdb (ths_industry_fund_flow_daily)',                                                  'ths_industry_fund_flow_daily_job.json',   'backend.services.scheduler.ths_industry_fund_flow_daily_scheduler',   'ThsIndustryFundFlowDailyScheduler', TRUE, '2026-06-17T22:50:00+08:00'),
    ('test_scheduler_demo',                    '[测试] scheduler 删除演示',              '测试用 entry, 没有对应 scheduler 模块, 用来演示 jobs.json CRUD',                                                                       '',                                        '(无 - 测试 entry)',                                                      'TestSchedulerDemo',                 TRUE, '2026-06-15T11:00:00+08:00'),
    ('style_risk_appetite_refresh',            '风格风险偏好 duckdb 回填 (17:08)',       '工作日 17:08 增量回填风格风险偏好 (中证1000 - 沪深300 5日收益) 到 duckdb',                                                            'style_risk_appetite_job.json',            'backend.services.scheduler.style_risk_appetite_scheduler',            'style_risk_appetite_scheduler',     TRUE, '2026-06-18T13:30:00+08:00'),
    ('profit_effect_refresh',                  '赚钱效应 duckdb 回填 (17:09)',          '工作日 17:09 增量回填赚钱效应 (近5日上涨占比+60日新低反向合成) 到 duckdb',                                                            'profit_effect_job.json',                  'backend.services.scheduler.profit_effect_scheduler',                  'profit_effect_scheduler',           TRUE, '2026-06-18T13:45:00+08:00'),
    ('market_sentiment_index_refresh',         '市场情绪指数 composite duckdb 回填 (17:10)','工作日 17:10 增量合成市场情绪指数 (9 张卡加权) 到 duckdb',                                                                            'market_sentiment_index_job.json',         'backend.services.scheduler.market_sentiment_index_scheduler',         'market_sentiment_index_scheduler',  TRUE, '2026-06-18T14:00:00+08:00')
ON CONFLICT (code) WHERE deleted_at IS NULL DO NOTHING;


-- ============================================================
-- 7. Data: app.scheduler_job_statuses  (23 条, 从每 status JSON 抽)
-- ============================================================
-- 用 INSERT ... SELECT ... JOIN app.scheduler_jobs ON code 把 job_id (uuid) 拿到.
-- 原 last_run_status='skipped_non_trading_day' 归一化为 'skipped', 原因保留在 extra.
-- market_pulse 3 个 job / market_overview + eltdx_overview 6 个 job 共享 status JSON,
--   跟原版一致, extra 字段同步保留 (camelCase key: lastRunAt / lastRunOk).

INSERT INTO app.scheduler_job_statuses (
    job_id, is_enabled, is_running, schedule, timezone_offset_hours, tick_seconds,
    last_run_at, last_run_ok, last_run_status, last_duration_seconds,
    last_targets_processed, total_runs, total_failures, scheduler_started_at, stopped_at,
    extra, updated_at
)
SELECT
    j.id, v.is_enabled, v.is_running, v.schedule, v.timezone_offset_hours, v.tick_seconds,
    v.last_run_at::timestamptz, v.last_run_ok, v.last_run_status, v.last_duration_seconds::numeric(12,3),
    v.last_targets_processed, v.total_runs, v.total_failures, v.scheduler_started_at::timestamptz, v.stopped_at::timestamptz,
    v.extra, v.updated_at::timestamptz
FROM (VALUES
    -- turnover_refresh
    ('turnover_refresh',                       TRUE,  FALSE, '{"workday_only": true, "intraday_windows": [{"start": "09:30", "end": "11:30", "every_minutes": 30}, {"start": "13:00", "end": "15:00", "every_minutes": 30}], "post_close_run": "16:00"}'::jsonb, 8,  30, '2026-06-19T16:00:25.547580+08:00', TRUE,  'success', 1.681,   1,   147, 0, NULL,                                NULL,                                '{"job_name": "turnover_refresh", "last_run_slot": "16:00", "last_run_date": "2026-06-19", "total_targets_processed": 189}'::jsonb, '2026-06-20T11:36:40.261598+08:00'),
    -- auction_ai_analysis
    ('auction_ai_analysis',                    TRUE,  FALSE, '{"workday_only": true, "run_time": "09:26", "run_once_per_day": true}'::jsonb,                                                                8,  30, '2026-06-19T09:26:12.093941+08:00', TRUE,  'success', 0.001,   0,   25,  2, NULL,                                NULL,                                '{"job_name": "auction_ai_analysis", "last_run_date": "2026-06-19", "total_targets_processed": 26}'::jsonb, '2026-06-20T11:36:40.265743+08:00'),
    -- stock_universe_refresh
    ('stock_universe_refresh',                 TRUE,  FALSE, '{"workday_only": true, "run_time": "17:00", "run_once_per_day": true}'::jsonb,                                                                8,  60, '2026-06-19T17:30:43.009024+08:00', TRUE,  'success', 1819.009,11,  2,   0, NULL,                                NULL,                                '{"job_name": "stock_universe_refresh", "last_run_slot": "17:00", "last_run_date": "2026-06-19", "last_stock_count": 0, "last_industry_count": 0, "last_topic_count": 0, "last_file": "F:\\dev-repo\\mp4-to-word-new\\reference\\stock-universe\\2026-06-19.json", "last_log_file": "F:\\dev-repo\\mp4-to-word-new\\reference\\stock-universe\\_logs\\2026-06-19-slot-1700.log", "last_exit_code": 0}'::jsonb, '2026-06-20T11:36:40.267066+08:00'),
    -- market_pulse 3 个 job (共享 status JSON)
    ('market_pulse_inside',                    TRUE,  FALSE, '{"workday_only": true, "every_minutes": 10, "intraday_windows": [{"start": "09:30", "end": "11:30"}, {"start": "13:00", "end": "15:00"}]}'::jsonb,    NULL,NULL,'2026-06-18T14:15:10+08:00',         TRUE,  'success', NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": true, "lastRunError": null, "lastInsideRefreshAt": "2026-06-18T14:15:10", "lastCloseSnapshotAt": "2026-06-18T15:30:00", "totalInside": 303, "totalClose": 8, "schedulerStartedAt": "2026-06-20T11:36:40", "lastTopN": [{"name": "非金属材料", "changePct": 4.99}, {"name": "金属新材料", "changePct": 2.45}, {"name": "半导体", "changePct": 2.29}, {"name": "小金属", "changePct": 2.28}, {"name": "医疗服务", "changePct": 1.96}], "lastLimitEmotionDailyAt": "2026-06-18T15:30:00", "job_kind": "shared_market_pulse"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('market_pulse_close',                     TRUE,  FALSE, '{"workday_only": true, "cron": "30 15 * * mon-fri"}'::jsonb,                                                                                    NULL,NULL,'2026-06-18T15:30:00+08:00',         TRUE,  'success', NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": true, "lastRunError": null, "lastInsideRefreshAt": "2026-06-18T14:15:10", "lastCloseSnapshotAt": "2026-06-18T15:30:00", "totalInside": 303, "totalClose": 8, "schedulerStartedAt": "2026-06-20T11:36:40", "lastTopN": [{"name": "非金属材料", "changePct": 4.99}, {"name": "金属新材料", "changePct": 2.45}, {"name": "半导体", "changePct": 2.29}, {"name": "小金属", "changePct": 2.28}, {"name": "医疗服务", "changePct": 1.96}], "lastLimitEmotionDailyAt": "2026-06-18T15:30:00", "job_kind": "shared_market_pulse"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('market_pulse_constituents',              TRUE,  FALSE, '{"workday_only": true, "cron": "35 15 * * mon-fri"}'::jsonb,                                                                                    NULL,NULL,'2026-06-18T15:35:00+08:00',         TRUE,  'success', NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": true, "lastRunError": null, "lastInsideRefreshAt": "2026-06-18T14:15:10", "lastCloseSnapshotAt": "2026-06-18T15:30:00", "totalInside": 303, "totalClose": 8, "schedulerStartedAt": "2026-06-20T11:36:40", "lastTopN": [{"name": "非金属材料", "changePct": 4.99}, {"name": "金属新材料", "changePct": 2.45}, {"name": "半导体", "changePct": 2.29}, {"name": "小金属", "changePct": 2.28}, {"name": "医疗服务", "changePct": 1.96}], "lastConstituentsAt": "2026-06-18T15:35:00", "lastConstituentsOk": true, "lastConstituentsError": null, "lastConstituentsElapseMs": 528095, "lastConstituentsIndustriesOk": 90, "lastConstituentsIndustriesTotal": 90, "lastLimitEmotionDailyAt": "2026-06-18T15:30:00", "job_kind": "shared_market_pulse"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- market_overview + eltdx_overview 6 个 job (上次跑失败)
    ('market_overview_inside',                 TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T14:59:50+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('market_overview_close',                  TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T15:35:00+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('market_overview_warmup',                 TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T09:00:00+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('eltdx_overview_inside',                  TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T14:59:50+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('eltdx_overview_close',                   TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T15:35:00+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    ('eltdx_overview_warmup',                  TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL,'2026-06-18T09:00:00+08:00',         FALSE, 'failed',  NULL,   NULL, 0,   0, '2026-06-20T11:36:40+08:00',         '2026-06-13T15:04:35+08:00',         '{"lastRunAt": "2026-06-18T15:35:00", "lastRunOk": false, "lastRunError": "force snapshot returned None", "lastInsideRefreshAt": "2026-06-18T14:59:50", "lastCloseSnapshotAt": "2026-06-18T15:35:00", "lastWarmupAt": "2026-06-18T09:00:00", "totalInside": 41, "totalClose": 1, "totalWarmup": 0, "lastInside": {"tradingDate": "2026-06-18", "totalAmount": null, "mainNetInflow": 45.88, "elapsedMs": 18102}, "lastClose": {"tradingDate": "2026-06-12", "totalAmount": 32361.31, "mainNetInflow": 1066444.8, "elapsedMs": 93174}, "job_kind": "shared_market_overview"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- ths_industry_constituents_weekly
    ('ths_industry_constituents_weekly',       TRUE,  FALSE, '{"weekday": 5, "run_time": "18:00", "run_once_per_week": true}'::jsonb,                                                                       8,  60, '2026-06-09T00:45:38.805165+08:00', TRUE,  'success', 380.012, 4666, 1,   0, NULL,                                NULL,                                '{"job_name": "ths_industry_constituents_weekly", "last_run_week": "2026-W24", "last_run_weekday": 1, "last_industry_count": 90, "last_total_rows": 4666, "last_failed_codes": [], "inter_industry_sleep_seconds": 1.5, "inter_industry_sleep_jitter": 0.5, "total_industries_crawled": 90}'::jsonb, '2026-06-20T11:36:40.304519+08:00'),
    -- ths_industry_constituents_daily (原 skipped_non_trading_day 归一化为 skipped, 原因放 extra)
    ('ths_industry_constituents_daily',        TRUE,  FALSE, '{"run_time": "17:00", "trading_day_only": true}'::jsonb,                                                                                    8,  60, '2026-06-19T17:00:24.016373+08:00', TRUE,  'skipped', 374.627, 4666, 8,   0, NULL,                                NULL,                                '{"job_name": "ths_industry_constituents_daily", "last_run_date": "2026-06-19", "last_skip_reason": "non_trading_day", "last_industry_count": 90, "last_total_rows": 4666, "last_failed_codes": [], "inter_industry_sleep_seconds": 1.5, "inter_industry_sleep_jitter": 0.5, "total_trading_day_runs": 7, "total_industries_crawled": 720, "total_skipped_non_trading_day": 3}'::jsonb, '2026-06-20T11:36:40.306885+08:00'),
    -- application_analysis (状态在 reference/application-analysis/scheduler.json)
    ('application_analysis',                   TRUE,  TRUE,  '{}'::jsonb,                                                                                                                          NULL,NULL, NULL,                                NULL,  NULL,     NULL,   NULL, 0,   0, '2026-06-20T11:36:40.256717+08:00', NULL,                                '{"running": true, "started_at": "2026-06-20T11:36:40.256717", "tick_count": 1, "runs_count": 0, "last_tick_at": "2026-06-20T11:36:40.256967", "last_run": {}, "targets_total": 4, "history": [], "_source_file": "reference/application-analysis/scheduler.json"}'::jsonb, '2026-06-20T11:36:40.256717+08:00'),
    -- daily_eod_incremental
    ('daily_eod_incremental',                  TRUE,  FALSE, '{"workday_only": true, "run_time": "17:00", "run_once_per_day": true}'::jsonb,                                                                8,  60, '2026-06-20T10:40:30+08:00',         TRUE,  'success', 4.9,    NULL, 4,   3, '2026-06-20T11:36:40+08:00',         '2026-06-17T21:39:07+08:00',         '{"job_name": "daily_eod_incremental", "lastMaxTradeDate": "2026-06-17", "lastLimitEmotionMaxDate": "2026-06-18", "lastBackfillOk": null, "lastSummaryOk": null, "lastTargetTradeDate": "2026-06-18", "running": true}'::jsonb, '2026-06-17T21:39:08.436318+08:00'),
    -- tdx_hsjday_download
    ('tdx_hsjday_download',                    TRUE,  TRUE,  '{"workday_only": true, "run_time": "16:30", "run_once_per_day": true}'::jsonb,                                                                8,  60, '2026-06-18T16:30:00+08:00',         TRUE,  'success', 54.9,   2,    2,   0, '2026-06-20T11:36:40+08:00',         '2026-06-17T21:51:58+08:00',         '{"job_name": "tdx_hsjday_download", "lastRunDate": "2026-06-18", "lastZipPath": "F:\\dev-repo\\mp4-to-word-new\\reference\\stock\\download\\2026-06-18\\hsjday.zip", "lastDayFileCount": null, "lastDownloadBytes": null}'::jsonb, '2026-06-17T21:51:58.156389+08:00'),
    -- market_overview_daily
    ('market_overview_daily',                  TRUE,  TRUE,  '{"workday_only": true, "run_time": "17:10", "run_once_per_day": true}'::jsonb,                                                                8,  60, '2026-06-20T10:41:16+08:00',         TRUE,  'success', 6.3,    1,    1,   0, '2026-06-20T11:36:40+08:00',         NULL,                                '{"job_name": "market_overview_daily", "lastDaysRequested": 60, "lastAkshareUpserted": null, "lastEltdxUpserted": null, "lastSectorDays": null, "lastOverviewCoverage": {"firstDate": "2023-06-01", "lastDate": "2026-06-18", "rowCount": 739}, "lastSectorCoverage": {"firstDate": "2026-06-07", "lastDate": "2026-06-19", "rowCount": 274, "tradeDayCount": 11}, "lastTargetTradeDate": "2026-06-18"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- ths_industry_fund_flow_daily
    ('ths_industry_fund_flow_daily',           TRUE,  TRUE,  '{"workday_only": true, "run_time": "17:15", "run_once_per_day": true}'::jsonb,                                                                8,  60, '2026-06-20T10:41:03+08:00',         TRUE,  'success', 7.3,    1,    1,   0, '2026-06-20T11:36:40+08:00',         NULL,                                '{"job_name": "ths_industry_fund_flow_daily", "lastDaysRequested": 60, "lastDaysUpserted": null, "lastRowsUpserted": null, "lastCoverage": {"firstDate": "2026-06-09", "lastDate": "2026-06-18", "rowCount": 721, "tradeDayCount": 8}, "lastTargetTradeDate": "2026-06-18", "lastSectorBreadthDays": 8}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- style_risk_appetite_refresh (外部脚本 job, 无 last_run)
    ('style_risk_appetite_refresh',            TRUE,  FALSE, '{"workday_only": true, "run_time": "17:08", "run_once_per_day": true}'::jsonb,                                                                8,  60, NULL,                                NULL,  NULL,     NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"job_name": "style_risk_appetite_refresh", "command": "python -u scripts/backfill_style_risk_appetite.py --days=2 --force", "_note": "外部脚本 job, status JSON 无 last_run 字段"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- profit_effect_refresh
    ('profit_effect_refresh',                  TRUE,  FALSE, '{"workday_only": true, "run_time": "17:09", "run_once_per_day": true}'::jsonb,                                                                8,  60, NULL,                                NULL,  NULL,     NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"job_name": "profit_effect_refresh", "command": "python -u scripts/backfill_profit_effect.py --days=2 --force", "_note": "外部脚本 job, status JSON 无 last_run 字段"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- market_sentiment_index_refresh
    ('market_sentiment_index_refresh',         TRUE,  FALSE, '{"workday_only": true, "run_time": "17:10", "run_once_per_day": true}'::jsonb,                                                                8,  60, NULL,                                NULL,  NULL,     NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"job_name": "market_sentiment_index_refresh", "command": "python -u scripts/backfill_market_sentiment_index.py --days=2 --force", "_note": "外部脚本 job, status JSON 无 last_run 字段"}'::jsonb, '2026-06-20T11:36:40+08:00'),
    -- test_scheduler_demo (无 status 文件)
    ('test_scheduler_demo',                    TRUE,  FALSE, '{}'::jsonb,                                                                                                                          NULL,NULL, NULL,                                NULL,  NULL,     NULL,   NULL, 0,   0, NULL,                                NULL,                                '{"_note": "测试 entry, 没有 status 文件"}'::jsonb, '2026-06-15T11:00:00+08:00')
) AS v(job_code, is_enabled, is_running, schedule, timezone_offset_hours, tick_seconds,
       last_run_at, last_run_ok, last_run_status, last_duration_seconds,
       last_targets_processed, total_runs, total_failures, scheduler_started_at, stopped_at,
       extra, updated_at)
JOIN app.scheduler_jobs j
    ON j.code = v.job_code
   AND j.deleted_at IS NULL
ON CONFLICT (job_id) WHERE deleted_at IS NULL DO NOTHING;


-- ============================================================
-- 8. Data: app.scheduler_job_run_history  (4 条, 从 status JSON history[])
-- ============================================================

INSERT INTO app.scheduler_job_run_history
    (job_id, started_at, ended_at, trigger_type, status, error_message, duration_seconds)
SELECT
    j.id, v.started_at::timestamptz, v.ended_at::timestamptz, v.trigger_type, v.status, v.error_message, v.duration_seconds::numeric(12,3)
FROM (VALUES
    ('daily_eod_incremental',          '2026-06-20T02:24:39+08:00', '2026-06-20T02:24:51+08:00', 'manual', 'failed',
     '_duckdb.IOException: IO Error: Cannot open file "F:\dev-repo\mp4-to-word-new\reference\stock\duckdb\market_data.duckdb": 另一个程序正在使用此文件，进程无法访问。 File is already open in C:\Python313\python.exe (PID 13772)',
     12.2),
    ('daily_eod_incremental',          '2026-06-20T10:40:30+08:00', '2026-06-20T10:40:35+08:00', 'manual', 'success', NULL, 4.9),
    ('market_overview_daily',          '2026-06-20T10:41:16+08:00', '2026-06-20T10:41:23+08:00', 'manual', 'success', NULL, 6.3),
    ('ths_industry_fund_flow_daily',   '2026-06-20T10:41:03+08:00', '2026-06-20T10:41:13+08:00', 'manual', 'success', NULL, 7.3)
) AS v(job_code, started_at, ended_at, trigger_type, status, error_message, duration_seconds)
JOIN app.scheduler_jobs j
    ON j.code = v.job_code
   AND j.deleted_at IS NULL
ON CONFLICT (job_id, started_at, trigger_type) DO NOTHING;


-- ============================================================
-- 9. Data: app.scheduler_job_categories  (6 条)
-- ============================================================
-- 加 code (skill §29.5): intraday / ai / data_collection / eod_backfill / composite / test.
-- INSERT 顺序就是 UI tab 顺序, sort_order 显式指定, 不依赖 uuid 大小.

INSERT INTO app.scheduler_job_categories (code, label, icon_hint, sort_order, description) VALUES
    ('intraday',         '盘内实时', 'activity',  10, '工作时间内 (盘内/盘后) 持续刷新的 job'),
    ('ai',               'AI 分析',  'sparkles',  20, 'AI 解读 / 标的级应用分析'),
    ('data_collection',  '数据采集', 'database',  30, '爬虫 / 离线下载 (A 股全市场 / 同花顺行业成分股 / TDX 历史)'),
    ('eod_backfill',     'EOD 回填', 'refresh',   40, '工作日盘后增量回填 duckdb'),
    ('composite',        '合成指标', 'trending',  50, '多张子表加权合成 (style_risk / profit_effect / sentiment_index)'),
    ('test',             '测试',     'flask',     99, '测试用 entry, 用来演示 jobs.json 注册表 CRUD')
ON CONFLICT (code) WHERE deleted_at IS NULL DO NOTHING;


-- ============================================================
-- 10. Data: app.scheduler_job_category_mappings  (23 条)
-- ============================================================
-- 不硬编码 category uuid. 用 JOIN scheduler_job_categories c ON c.code = m.category_code
-- 把 23 条 mapping 一把 INSERT. 优点: 9. 的 categories 顺序 / 数量变了, 这里不用动.

INSERT INTO app.scheduler_job_category_mappings (job_id, category_id)
SELECT j.id, c.id
FROM (VALUES
    ('turnover_refresh',                       'intraday'),
    ('market_pulse_inside',                    'intraday'),
    ('market_pulse_close',                     'intraday'),
    ('market_pulse_constituents',              'intraday'),
    ('market_overview_inside',                 'intraday'),
    ('market_overview_close',                  'intraday'),
    ('market_overview_warmup',                 'intraday'),
    ('eltdx_overview_inside',                  'intraday'),
    ('eltdx_overview_close',                   'intraday'),
    ('eltdx_overview_warmup',                  'intraday'),
    ('application_analysis',                   'ai'),
    ('auction_ai_analysis',                    'ai'),
    ('stock_universe_refresh',                 'data_collection'),
    ('ths_industry_constituents_weekly',       'data_collection'),
    ('ths_industry_constituents_daily',        'data_collection'),
    ('tdx_hsjday_download',                    'data_collection'),
    ('daily_eod_incremental',                  'eod_backfill'),
    ('market_overview_daily',                  'eod_backfill'),
    ('ths_industry_fund_flow_daily',           'eod_backfill'),
    ('style_risk_appetite_refresh',            'composite'),
    ('profit_effect_refresh',                  'composite'),
    ('market_sentiment_index_refresh',         'composite'),
    ('test_scheduler_demo',                    'test')
) AS m(job_code, category_code)
JOIN app.scheduler_jobs j
    ON j.code = m.job_code
   AND j.deleted_at IS NULL
JOIN app.scheduler_job_categories c
    ON c.code = m.category_code
   AND c.deleted_at IS NULL
ON CONFLICT (job_id, category_id) WHERE deleted_at IS NULL DO NOTHING;


-- ============================================================
-- 11. 校验
-- ============================================================
-- 应该看到:
--   scheduler_jobs                : 23
--   scheduler_job_statuses        : 23
--   scheduler_job_run_history     :  4
--   scheduler_job_categories      :  6
--   scheduler_job_category_mappings: 23
--   mapping_by_category intraday  : 10
--   mapping_by_category ai        :  2
--   mapping_by_category data_collection : 4
--   mapping_by_category eod_backfill    : 3
--   mapping_by_category composite       : 3
--   mapping_by_category test            : 1

SELECT 'scheduler_jobs'                 AS table_name, COUNT(*) AS row_count FROM app.scheduler_jobs
UNION ALL
SELECT 'scheduler_job_statuses',                  COUNT(*)                FROM app.scheduler_job_statuses
UNION ALL
SELECT 'scheduler_job_run_history',               COUNT(*)                FROM app.scheduler_job_run_history
UNION ALL
SELECT 'scheduler_job_categories',                COUNT(*)                FROM app.scheduler_job_categories
UNION ALL
SELECT 'scheduler_job_category_mappings',         COUNT(*)                FROM app.scheduler_job_category_mappings
UNION ALL
SELECT 'mapping_by_category=' || c.code,          COUNT(*)
FROM   app.scheduler_job_category_mappings m
JOIN   app.scheduler_job_categories c ON c.id = m.category_id
GROUP  BY c.code
ORDER  BY 1;

COMMIT;