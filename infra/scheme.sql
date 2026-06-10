-- ============================================================================
-- seven-and-me PostgreSQL Schema v2
-- 目标: 从本地 JSON 文件持久化迁移到 PostgreSQL
-- PG 版本: 15+
-- schema: seven_and_me
--
-- 使用方式:
--   psql "$DATABASE_URL" -f seven_and_me_postgres_schema_v2.sql
--
-- 注意:
--   1. 本脚本默认不 DROP 旧对象，适合新库/空 schema 初始化。
--   2. 如果你已经执行过旧版 DDL，并希望重建，请先备份，然后手动执行:
--        DROP SCHEMA IF EXISTS seven_and_me CASCADE;
--   3. 设计重点:
--        - instruments 统一标的 ID
--        - 缓存类保留 JSONB raw cache
--        - K 线增加可查询明细表 kline_bars
--        - annotation 兼容旧备注模型 + 新 overlay 模型
--        - scheduler 状态收敛为 scheduler_job_state
--        - updated_at 统一 trigger 维护
--        - ths_industry_constituents / stock_universe_daily 预留分区
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS seven_and_me;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- 公共函数
-- ============================================================================

CREATE OR REPLACE FUNCTION seven_and_me.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- §0 统一标的表
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.instruments (
    id              TEXT PRIMARY KEY, -- stock-600415 / index-000001 / industry-sh880301 / concept-xxxx
    target_type     TEXT NOT NULL CHECK (target_type IN ('stock','index','sector','industry','concept','style')),
    market          TEXT CHECK (market IN ('SH','SZ','BJ','HK','US','THS','TDX','UNKNOWN')),
    symbol          TEXT NOT NULL,    -- 600415 / 000001 / 881121
    full_code       TEXT,             -- sh600415 / sz000001 / bj920022 / 881121
    name            TEXT,
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_type, symbol),
    UNIQUE (full_code)
);

COMMENT ON TABLE seven_and_me.instruments IS '统一标的字典，统一 stock/index/industry/concept 等 ID 体系';

CREATE INDEX IF NOT EXISTS idx_instruments_type_symbol
ON seven_and_me.instruments (target_type, symbol);

CREATE INDEX IF NOT EXISTS idx_instruments_full_code
ON seven_and_me.instruments (full_code);

-- ============================================================================
-- §4 MP4 转写历史
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.mp4_history (
    id           TEXT PRIMARY KEY, -- mp4-{uuid}
    task_id      TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('pending','running','done','error')),
    file_name    TEXT,
    transcript   TEXT,
    polished     TEXT,
    summary      TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    sort_order   INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.mp4_history IS 'MP4 转写历史，兼容 reference/parse/data/*.json 与 index.json';

CREATE INDEX IF NOT EXISTS idx_mp4_history_created_at
ON seven_and_me.mp4_history (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mp4_history_sort
ON seven_and_me.mp4_history (sort_order, created_at DESC);

-- 可选全文检索，后续如果做搜索接口可以启用。
CREATE INDEX IF NOT EXISTS idx_mp4_history_text_search
ON seven_and_me.mp4_history
USING GIN (
    to_tsvector(
        'simple',
        coalesce(title,'') || ' ' ||
        coalesce(transcript,'') || ' ' ||
        coalesce(polished,'') || ' ' ||
        coalesce(summary,'')
    )
);

-- ============================================================================
-- §5 个股 workspace + 渲染配置 + 标线
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.stock_workspaces (
    id            TEXT PRIMARY KEY REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    target_type   TEXT NOT NULL CHECK (target_type IN ('stock','index','sector')),
    symbol        TEXT NOT NULL,
    name          TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_workspaces IS '个股/指数工作区';

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_workspaces_type_symbol
ON seven_and_me.stock_workspaces (target_type, symbol);

CREATE INDEX IF NOT EXISTS idx_stock_workspaces_updated_at
ON seven_and_me.stock_workspaces (updated_at DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.workspace_configs (
    workspace_id         TEXT PRIMARY KEY REFERENCES seven_and_me.stock_workspaces(id) ON DELETE CASCADE,
    period               TEXT NOT NULL DEFAULT '1d' CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust               TEXT NOT NULL DEFAULT 'qfq' CHECK (adjust IN ('none','qfq','hfq')),
    indicators           TEXT[] NOT NULL DEFAULT '{}',
    drawing_tool         TEXT,
    show_auction_panel   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.workspace_configs IS '工作区渲染配置';

CREATE TABLE IF NOT EXISTS seven_and_me.annotations (
    id             TEXT PRIMARY KEY,
    target_id      TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    period         TEXT NOT NULL DEFAULT '1d',
    overlay_type   TEXT NOT NULL DEFAULT 'note'
                   CHECK (overlay_type IN ('note','bs_point','trend_line','custom')),
    title          TEXT,
    content        TEXT,
    bar_time       TIMESTAMPTZ,
    x              NUMERIC,
    y              NUMERIC,
    color          TEXT,
    points         JSONB NOT NULL DEFAULT '[]'::jsonb,
    styles         JSONB NOT NULL DEFAULT '{}'::jsonb,
    legacy_payload JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(points) = 'array'),
    CHECK (jsonb_typeof(styles) = 'object'),
    CHECK (
        overlay_type <> 'bs_point'
        OR (styles ? 'side' AND styles->>'side' IN ('B','S'))
    )
);

COMMENT ON TABLE seven_and_me.annotations IS '标线、B/S 标记、旧版点位备注，兼容 reference/stock/data/annotations/*.json';

CREATE INDEX IF NOT EXISTS idx_annotations_target_period
ON seven_and_me.annotations (target_id, period, overlay_type);

CREATE INDEX IF NOT EXISTS idx_annotations_target_time
ON seven_and_me.annotations (target_id, bar_time DESC);

-- ============================================================================
-- §6 行情缓存 + 可查询 K 线明细
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.kline_cache (
    target_id    TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    period       TEXT NOT NULL CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust       TEXT NOT NULL CHECK (adjust IN ('none','qfq','hfq')),
    source       TEXT,
    items        JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, period, adjust),
    CHECK (jsonb_typeof(items) = 'array')
);

COMMENT ON TABLE seven_and_me.kline_cache IS 'K 线原始缓存，复刻 reference/stock/cache/klines/*.json';

CREATE TABLE IF NOT EXISTS seven_and_me.kline_bars (
    target_id    TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    period       TEXT NOT NULL CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust       TEXT NOT NULL CHECK (adjust IN ('none','qfq','hfq')),
    bar_time     TIMESTAMPTZ NOT NULL,
    trade_date   DATE,
    open         NUMERIC,
    high         NUMERIC,
    low          NUMERIC,
    close        NUMERIC,
    volume       NUMERIC,
    amount       NUMERIC,
    source       TEXT,
    payload      JSONB,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, period, adjust, bar_time)
);

COMMENT ON TABLE seven_and_me.kline_bars IS '可查询 K 线明细，供 SQL 查询/聚合/回测使用';

CREATE INDEX IF NOT EXISTS idx_kline_bars_target_time
ON seven_and_me.kline_bars (target_id, period, adjust, bar_time DESC);

CREATE INDEX IF NOT EXISTS idx_kline_bars_trade_date
ON seven_and_me.kline_bars (trade_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.intraday_cache (
    target_id               TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    trade_date              DATE NOT NULL,
    requested_trade_date    DATE,
    effective_adjust        TEXT CHECK (effective_adjust IN ('none','qfq','hfq')),
    requested_adjust        TEXT CHECK (requested_adjust IN ('none','qfq','hfq')),
    timeshare               JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, trade_date),
    CHECK (jsonb_typeof(timeshare) = 'array')
);

COMMENT ON TABLE seven_and_me.intraday_cache IS '分时原始缓存';

CREATE INDEX IF NOT EXISTS idx_intraday_cache_date
ON seven_and_me.intraday_cache (trade_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.intraday_ticks (
    target_id    TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    trade_date   DATE NOT NULL,
    tick_time    TIMESTAMPTZ NOT NULL,
    price        NUMERIC,
    volume       NUMERIC,
    amount       NUMERIC,
    payload      JSONB,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, trade_date, tick_time)
);

COMMENT ON TABLE seven_and_me.intraday_ticks IS '可选分时明细，适合后续做分时统计/查询';

CREATE INDEX IF NOT EXISTS idx_intraday_ticks_target_time
ON seven_and_me.intraday_ticks (target_id, tick_time DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.auction_cache (
    target_id    TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    trade_date   DATE NOT NULL,
    opening      JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, trade_date),
    CHECK (jsonb_typeof(opening) = 'object')
);

COMMENT ON TABLE seven_and_me.auction_cache IS '集合竞价快照';

CREATE INDEX IF NOT EXISTS idx_auction_cache_date
ON seven_and_me.auction_cache (trade_date DESC);

-- ============================================================================
-- §7 涨跌家数
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.market_breadth_latest (
    id                          INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    up_count                    INT,
    down_count                  INT,
    limit_up_count              INT,
    limit_down_count            INT,
    total_count                 INT,
    break_rate                  NUMERIC,
    max_lian_ban                INT,
    yesterday_limit_up_return   NUMERIC,
    total_turnover              NUMERIC,
    down_over5_count            INT,
    new20_high_count            INT,
    new20_low_count             INT,
    source                      TEXT,
    cached_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.market_breadth_latest IS '涨跌家数最新单例';

CREATE TABLE IF NOT EXISTS seven_and_me.market_breadth_series (
    trade_date          DATE PRIMARY KEY,
    up_count            INT,
    down_count          INT,
    limit_up_count      INT,
    limit_down_count    INT,
    total_count         INT,
    source              TEXT,
    payload             JSONB,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.market_breadth_series IS '涨跌家数历史序列';

CREATE INDEX IF NOT EXISTS idx_market_breadth_series_date
ON seven_and_me.market_breadth_series (trade_date DESC);

-- ============================================================================
-- §8 F10 业务缓存
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.f10_cache (
    category     TEXT NOT NULL,
    cache_key    TEXT NOT NULL,
    payload      JSONB NOT NULL,
    source       TEXT,
    expires_at   TIMESTAMPTZ,
    payload_hash TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category, cache_key)
);

COMMENT ON TABLE seven_and_me.f10_cache IS 'F10 通用业务缓存';

CREATE INDEX IF NOT EXISTS idx_f10_cache_category
ON seven_and_me.f10_cache (category);

CREATE INDEX IF NOT EXISTS idx_f10_cache_expires_at
ON seven_and_me.f10_cache (expires_at)
WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS seven_and_me.f10_limit_count (
    trade_date         DATE PRIMARY KEY,
    up_count           INT NOT NULL DEFAULT 0,
    down_count         INT NOT NULL DEFAULT 0,
    flat_count         INT NOT NULL DEFAULT 0,
    limit_up_count     INT NOT NULL DEFAULT 0,
    limit_down_count   INT NOT NULL DEFAULT 0,
    total_count        INT NOT NULL,
    threshold_rules    JSONB,
    payload            JSONB,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.f10_limit_count IS '涨跌停统计';

-- ============================================================================
-- §9 行业 index 覆盖
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.industry_index_overrides (
    code    TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    kind    TEXT NOT NULL CHECK (kind IN ('sector','concept','industry','style'))
);

COMMENT ON TABLE seven_and_me.industry_index_overrides IS '行业 index 手动覆盖';

-- ============================================================================
-- §10 换手率
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.turnover_files (
    target_id           TEXT NOT NULL REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    period              TEXT NOT NULL DEFAULT '1d' CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust              TEXT NOT NULL DEFAULT 'qfq' CHECK (adjust IN ('none','qfq','hfq')),
    target_type         TEXT NOT NULL CHECK (target_type IN ('stock','index')),
    circulating_shares  NUMERIC,
    total_shares        NUMERIC,
    source              TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, period, adjust)
);

COMMENT ON TABLE seven_and_me.turnover_files IS '换手率文件元数据';

CREATE TABLE IF NOT EXISTS seven_and_me.turnover_entries (
    target_id        TEXT NOT NULL,
    period           TEXT NOT NULL DEFAULT '1d',
    adjust           TEXT NOT NULL DEFAULT 'qfq',
    trade_date       DATE NOT NULL,
    turnover_rate    NUMERIC,
    volume           NUMERIC,
    amount           NUMERIC,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, period, adjust, trade_date),
    FOREIGN KEY (target_id, period, adjust)
        REFERENCES seven_and_me.turnover_files(target_id, period, adjust)
        ON DELETE CASCADE
);

COMMENT ON TABLE seven_and_me.turnover_entries IS '换手率明细';

CREATE INDEX IF NOT EXISTS idx_turnover_entries_date
ON seven_and_me.turnover_entries (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_turnover_entries_target
ON seven_and_me.turnover_entries (target_id, trade_date DESC);

-- ============================================================================
-- §11 个股应用分析
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_targets (
    id                TEXT PRIMARY KEY REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    target_type       TEXT NOT NULL CHECK (target_type IN ('stock','index')),
    symbol            TEXT NOT NULL,
    name              TEXT NOT NULL,
    adjust            TEXT NOT NULL DEFAULT 'qfq' CHECK (adjust IN ('none','qfq','hfq')),
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    interval_minutes  INT NOT NULL DEFAULT 60 CHECK (interval_minutes > 0),
    tags              TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.app_analysis_targets IS '应用分析 target 列表';

CREATE INDEX IF NOT EXISTS idx_app_analysis_targets_enabled
ON seven_and_me.app_analysis_targets (enabled)
WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_app_analysis_targets_tags
ON seven_and_me.app_analysis_targets USING GIN (tags);

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_horizon (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    days            INT NOT NULL DEFAULT 120 CHECK (days > 0),
    segments        INT NOT NULL DEFAULT 4 CHECK (segments > 0),
    monthly_keep    INT NOT NULL DEFAULT 6 CHECK (monthly_keep >= 0),
    weekly_keep     INT NOT NULL DEFAULT 12 CHECK (weekly_keep >= 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.app_analysis_horizon IS '应用分析 horizon 全局配置单例';

INSERT INTO seven_and_me.app_analysis_horizon (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_scheduler_state (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    running         BOOLEAN NOT NULL DEFAULT FALSE,
    started_at      TIMESTAMPTZ,
    tick_count      BIGINT NOT NULL DEFAULT 0,
    runs_count      BIGINT NOT NULL DEFAULT 0,
    last_tick_at    TIMESTAMPTZ,
    last_run        JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.app_analysis_scheduler_state IS '应用分析 scheduler 实时状态单例';

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_results (
    target_id       TEXT PRIMARY KEY REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    overlay_count   INT,
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB
);

COMMENT ON TABLE seven_and_me.app_analysis_results IS '应用分析最新结果，target 基础信息通过 view 关联';

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_history (
    id              TEXT PRIMARY KEY,
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('success','error','running')),
    elapsed_seconds NUMERIC,
    source          TEXT,
    finished_at     TIMESTAMPTZ NOT NULL,
    overlay_count   INT,
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_id, finished_at)
);

COMMENT ON TABLE seven_and_me.app_analysis_history IS '应用分析历史';

CREATE INDEX IF NOT EXISTS idx_app_analysis_history_target_time
ON seven_and_me.app_analysis_history (target_id, finished_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_analysis_history_time
ON seven_and_me.app_analysis_history (finished_at DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_auction (
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, trade_date)
);

COMMENT ON TABLE seven_and_me.app_analysis_auction IS '应用分析集合竞价 AI';

CREATE INDEX IF NOT EXISTS idx_app_analysis_auction_date
ON seven_and_me.app_analysis_auction (trade_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.app_analysis_snapshots (
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    snapshot        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, trade_date)
);

COMMENT ON TABLE seven_and_me.app_analysis_snapshots IS '应用分析盘后快照';

CREATE INDEX IF NOT EXISTS idx_app_analysis_snapshots_date
ON seven_and_me.app_analysis_snapshots (trade_date DESC);

-- ============================================================================
-- §12 行业应用分析
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.industry_app_targets (
    id                TEXT PRIMARY KEY REFERENCES seven_and_me.instruments(id) ON DELETE CASCADE,
    target_type       TEXT NOT NULL CHECK (target_type IN ('industry','concept')),
    symbol            TEXT NOT NULL,
    name              TEXT NOT NULL,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    interval_minutes  INT NOT NULL DEFAULT 60 CHECK (interval_minutes > 0),
    tags              TEXT[] NOT NULL DEFAULT '{}',
    horizon_days      INT NOT NULL DEFAULT 120 CHECK (horizon_days > 0),
    horizon_segments  INT NOT NULL DEFAULT 4 CHECK (horizon_segments > 0),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.industry_app_targets IS '行业应用分析 target 列表';

CREATE INDEX IF NOT EXISTS idx_industry_app_targets_enabled
ON seven_and_me.industry_app_targets (enabled)
WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_industry_app_targets_tags
ON seven_and_me.industry_app_targets USING GIN (tags);

CREATE TABLE IF NOT EXISTS seven_and_me.industry_app_results (
    target_id       TEXT PRIMARY KEY REFERENCES seven_and_me.industry_app_targets(id) ON DELETE CASCADE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB
);

COMMENT ON TABLE seven_and_me.industry_app_results IS '行业应用分析最新结果';

CREATE TABLE IF NOT EXISTS seven_and_me.industry_app_history (
    id              TEXT PRIMARY KEY,
    target_id       TEXT NOT NULL REFERENCES seven_and_me.industry_app_targets(id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('success','error','running')),
    elapsed_seconds NUMERIC,
    source          TEXT,
    finished_at     TIMESTAMPTZ NOT NULL,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_id, finished_at)
);

COMMENT ON TABLE seven_and_me.industry_app_history IS '行业应用分析历史';

CREATE INDEX IF NOT EXISTS idx_industry_app_history_target_time
ON seven_and_me.industry_app_history (target_id, finished_at DESC);

CREATE INDEX IF NOT EXISTS idx_industry_app_history_time
ON seven_and_me.industry_app_history (finished_at DESC);

-- ============================================================================
-- §13 自选股
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.self_selected_groups (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    color       TEXT NOT NULL DEFAULT 'blue',
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.self_selected_groups IS '自选股分组';

CREATE INDEX IF NOT EXISTS idx_self_selected_groups_sort
ON seven_and_me.self_selected_groups (sort_order, created_at);

CREATE TABLE IF NOT EXISTS seven_and_me.self_selected_items (
    id          TEXT PRIMARY KEY,
    group_id    TEXT NOT NULL REFERENCES seven_and_me.self_selected_groups(id) ON DELETE CASCADE,
    target_id   TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL CHECK (market IN ('SH','SZ','BJ','HK','US')),
    name        TEXT NOT NULL,
    notes       TEXT,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, symbol, market)
);

COMMENT ON TABLE seven_and_me.self_selected_items IS '自选股标的';

CREATE INDEX IF NOT EXISTS idx_self_selected_items_group
ON seven_and_me.self_selected_items (group_id, sort_order);

CREATE INDEX IF NOT EXISTS idx_self_selected_items_target
ON seven_and_me.self_selected_items (target_id)
WHERE target_id IS NOT NULL;

-- ============================================================================
-- §14 同花顺行业 / 资金
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.ths_fund_flow_daily (
    trade_date        DATE PRIMARY KEY,
    ok                BOOLEAN NOT NULL,
    row_count         INT NOT NULL,
    total_pages       INT NOT NULL,
    page_row_counts   INT[] NOT NULL DEFAULT '{}',
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows              JSONB NOT NULL DEFAULT '[]'::jsonb,
    CHECK (jsonb_typeof(rows) = 'array')
);

COMMENT ON TABLE seven_and_me.ths_fund_flow_daily IS '同花顺全行业主力资金';

CREATE INDEX IF NOT EXISTS idx_ths_fund_flow_daily_fetched_at
ON seven_and_me.ths_fund_flow_daily (fetched_at DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industries (
    code              TEXT PRIMARY KEY,
    target_id         TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    name              TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.ths_industries IS '同花顺行业字典';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ths_industries_target
ON seven_and_me.ths_industries (target_id)
WHERE target_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industry_info (
    industry_code    TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    trade_date       DATE NOT NULL,
    data             JSONB NOT NULL,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_code, trade_date),
    CHECK (jsonb_typeof(data) = 'object')
);

COMMENT ON TABLE seven_and_me.ths_industry_info IS '同花顺行业实时信息';

CREATE INDEX IF NOT EXISTS idx_ths_industry_info_date
ON seven_and_me.ths_industry_info (trade_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industry_klines (
    industry_code   TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    data            JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_code, trade_date),
    CHECK (jsonb_typeof(data) = 'object')
);

COMMENT ON TABLE seven_and_me.ths_industry_klines IS '同花顺行业 K 线';

CREATE INDEX IF NOT EXISTS idx_ths_industry_klines_date
ON seven_and_me.ths_industry_klines (trade_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industry_constituents_meta (
    industry_code      TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    snapshot_date      DATE NOT NULL,
    ok                 BOOLEAN NOT NULL,
    total_pages        INT NOT NULL,
    page_row_counts    INT[] NOT NULL DEFAULT '{}',
    row_count          INT NOT NULL,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_code, snapshot_date)
);

COMMENT ON TABLE seven_and_me.ths_industry_constituents_meta IS '同花顺行业成分股 snapshot 元数据';

CREATE INDEX IF NOT EXISTS idx_ths_industry_constituents_meta_date
ON seven_and_me.ths_industry_constituents_meta (snapshot_date DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industry_constituents (
    industry_code     TEXT NOT NULL,
    snapshot_date     DATE NOT NULL,
    seq               INT,
    stock_code        TEXT NOT NULL,
    stock_target_id   TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    stock_name        TEXT NOT NULL,
    payload           JSONB NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_code, snapshot_date, stock_code),
    FOREIGN KEY (industry_code, snapshot_date)
        REFERENCES seven_and_me.ths_industry_constituents_meta(industry_code, snapshot_date)
        ON DELETE CASCADE,
    CHECK (jsonb_typeof(payload) = 'object')
) PARTITION BY RANGE (snapshot_date);

COMMENT ON TABLE seven_and_me.ths_industry_constituents IS '同花顺行业成分股明细，按 snapshot_date 分区';

CREATE TABLE IF NOT EXISTS seven_and_me.ths_industry_constituents_default
PARTITION OF seven_and_me.ths_industry_constituents DEFAULT;

CREATE INDEX IF NOT EXISTS idx_ths_industry_constituents_stock
ON seven_and_me.ths_industry_constituents (stock_code);

CREATE INDEX IF NOT EXISTS idx_ths_industry_constituents_stock_target
ON seven_and_me.ths_industry_constituents (stock_target_id)
WHERE stock_target_id IS NOT NULL;

-- ============================================================================
-- §15 A 股全市场
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_daily (
    trading_day    DATE NOT NULL,
    code           TEXT NOT NULL, -- sh600415 / sz000001 / bj920022
    target_id      TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    name           TEXT,
    industry       TEXT,
    raw            JSONB,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trading_day, code)
) PARTITION BY RANGE (trading_day);

COMMENT ON TABLE seven_and_me.stock_universe_daily IS 'A 股全市场每日快照，按 trading_day 分区';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_daily_default
PARTITION OF seven_and_me.stock_universe_daily DEFAULT;

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_day
ON seven_and_me.stock_universe_daily (trading_day DESC);

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_code
ON seven_and_me.stock_universe_daily (code);

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_target
ON seven_and_me.stock_universe_daily (target_id)
WHERE target_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_daily_topics (
    trading_day    DATE NOT NULL,
    code           TEXT NOT NULL,
    topic_id       TEXT NOT NULL,
    topic_name     TEXT,
    PRIMARY KEY (trading_day, code, topic_id),
    FOREIGN KEY (trading_day, code)
        REFERENCES seven_and_me.stock_universe_daily(trading_day, code)
        ON DELETE CASCADE
);

COMMENT ON TABLE seven_and_me.stock_universe_daily_topics IS 'A 股全市场每日快照 - 题材 M2M';

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_topics_topic
ON seven_and_me.stock_universe_daily_topics (topic_id, trading_day DESC);

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_topics_code
ON seven_and_me.stock_universe_daily_topics (code);

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_codes (
    code            TEXT PRIMARY KEY,
    target_id       TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    listed_market   TEXT NOT NULL CHECK (listed_market IN ('SH','SZ','BJ')),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_codes IS '全 A 股 code 列表';

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_universe_codes_target
ON seven_and_me.stock_universe_codes (target_id)
WHERE target_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_failed_codes (
    code             TEXT PRIMARY KEY,
    last_failed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason           TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_failed_codes IS '全 A 股拉取失败记录';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_progress (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    total           INT,
    completed       INT,
    last_updated_at TIMESTAMPTZ,
    payload         JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_progress IS '全 A 股拉取进度单例';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_groups (
    group_id     TEXT PRIMARY KEY,
    payload      JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_groups IS '全 A 股分片桶';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_quote_cache (
    trade_date   DATE PRIMARY KEY,
    payload      JSONB NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_quote_cache IS '全 A 股行情缓存';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_shares_cache (
    trade_date    DATE PRIMARY KEY,
    shares        JSONB NOT NULL,
    source        TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_universe_shares_cache IS '全 A 股股本缓存';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_universe_qt_fund_flow (
    code           TEXT NOT NULL,
    target_id      TEXT REFERENCES seven_and_me.instruments(id) ON DELETE SET NULL,
    snapshot_date  DATE NOT NULL,
    data           JSONB NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (code, snapshot_date)
);

COMMENT ON TABLE seven_and_me.stock_universe_qt_fund_flow IS 'qt.gtimg.cn 个股资金流';

CREATE INDEX IF NOT EXISTS idx_stock_universe_qt_fund_flow_target
ON seven_and_me.stock_universe_qt_fund_flow (target_id, snapshot_date DESC)
WHERE target_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS seven_and_me.market_pulse_rotation (
    trade_date    DATE PRIMARY KEY,
    top_n         INT NOT NULL,
    items         JSONB NOT NULL,
    source        TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(items) = 'array')
);

COMMENT ON TABLE seven_and_me.market_pulse_rotation IS '行情页轮动 Top N 快照';

CREATE INDEX IF NOT EXISTS idx_market_pulse_rotation_fetched_at
ON seven_and_me.market_pulse_rotation (fetched_at DESC);

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_concepts (
    topic_id          TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.sectors_concepts IS '概念板块字典';

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_industries (
    industry_id       TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.sectors_industries IS '行业板块字典';

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_styles (
    style_id          TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.sectors_styles IS '风格板块字典';

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_index (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    payload         JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.sectors_index IS '板块顶层索引单例';

CREATE TABLE IF NOT EXISTS seven_and_me.tdx_industry_56 (
    industry_code   TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.tdx_industry_56 IS 'TDX 56 行业映射';

-- ============================================================================
-- §16 Scheduler
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.scheduler_jobs (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    config_file     TEXT,
    service_module  TEXT,
    service_class   TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at   TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.scheduler_jobs IS 'Scheduler 注册表';

CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_enabled
ON seven_and_me.scheduler_jobs (enabled)
WHERE enabled = TRUE;

CREATE TABLE IF NOT EXISTS seven_and_me.scheduler_job_state (
    job_id          TEXT PRIMARY KEY REFERENCES seven_and_me.scheduler_jobs(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    last_run_date   DATE,
    last_run_slot   TEXT,
    last_status     TEXT,
    last_error      TEXT,
    total_runs      BIGINT NOT NULL DEFAULT 0,
    total_failures  BIGINT NOT NULL DEFAULT 0,
    state           JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(state) = 'object')
);

COMMENT ON TABLE seven_and_me.scheduler_job_state IS 'Scheduler 统一状态表，替代多个单例状态表';

CREATE INDEX IF NOT EXISTS idx_scheduler_job_state_status
ON seven_and_me.scheduler_job_state (last_status);

CREATE INDEX IF NOT EXISTS idx_scheduler_job_state_updated
ON seven_and_me.scheduler_job_state (updated_at DESC);

-- ============================================================================
-- §17 K 线数据源配置
-- ============================================================================

CREATE TABLE IF NOT EXISTS seven_and_me.stock_chart_config (
    id                   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    minute_provider      TEXT NOT NULL,
    daily_provider       TEXT NOT NULL,
    weekly_provider      TEXT NOT NULL,
    minute_fallback      TEXT[] NOT NULL DEFAULT '{}',
    daily_fallback       TEXT[] NOT NULL DEFAULT '{}',
    weekly_fallback      TEXT[] NOT NULL DEFAULT '{}',
    mootdx_timeout       INT NOT NULL DEFAULT 10 CHECK (mootdx_timeout > 0),
    minute_adjust_mode   TEXT NOT NULL DEFAULT 'none_only',
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_chart_config IS 'K 线数据源配置单例';

CREATE TABLE IF NOT EXISTS seven_and_me.stock_chart_mootdx_servers (
    id          BIGSERIAL PRIMARY KEY,
    host        TEXT NOT NULL,
    port        INT  NOT NULL CHECK (port > 0 AND port <= 65535),
    sort_order  INT  NOT NULL DEFAULT 0,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE seven_and_me.stock_chart_mootdx_servers IS 'mootdx TDX 服务器列表';

CREATE INDEX IF NOT EXISTS idx_stock_chart_mootdx_servers_enabled_sort
ON seven_and_me.stock_chart_mootdx_servers (enabled, sort_order);

-- ============================================================================
-- 便利视图
-- ============================================================================

CREATE OR REPLACE VIEW seven_and_me.v_ths_fund_flow_latest AS
SELECT *
FROM seven_and_me.ths_fund_flow_daily
ORDER BY trade_date DESC
LIMIT 1;

CREATE OR REPLACE VIEW seven_and_me.v_market_pulse_rotation_latest AS
SELECT *
FROM seven_and_me.market_pulse_rotation
ORDER BY trade_date DESC
LIMIT 1;

CREATE OR REPLACE VIEW seven_and_me.v_self_selected_items AS
SELECT
    i.*,
    g.name AS group_name,
    g.color AS group_color
FROM seven_and_me.self_selected_items i
JOIN seven_and_me.self_selected_groups g ON g.id = i.group_id;

CREATE OR REPLACE VIEW seven_and_me.v_app_analysis_results AS
SELECT
    r.*,
    t.target_type,
    t.symbol,
    t.name,
    t.adjust,
    t.tags
FROM seven_and_me.app_analysis_results r
JOIN seven_and_me.app_analysis_targets t ON t.id = r.target_id;

CREATE OR REPLACE VIEW seven_and_me.v_app_analysis_history AS
SELECT
    h.*,
    t.name AS target_name,
    t.adjust AS target_adjust,
    t.symbol AS target_symbol,
    t.tags AS target_tags
FROM seven_and_me.app_analysis_history h
JOIN seven_and_me.app_analysis_targets t ON t.id = h.target_id;

CREATE OR REPLACE VIEW seven_and_me.v_industry_app_results AS
SELECT
    r.*,
    t.target_type,
    t.symbol,
    t.name,
    t.tags
FROM seven_and_me.industry_app_results r
JOIN seven_and_me.industry_app_targets t ON t.id = r.target_id;

CREATE OR REPLACE VIEW seven_and_me.v_industry_app_history AS
SELECT
    h.*,
    t.name AS target_name,
    t.symbol AS target_symbol,
    t.tags AS target_tags
FROM seven_and_me.industry_app_history h
JOIN seven_and_me.industry_app_targets t ON t.id = h.target_id;

CREATE OR REPLACE VIEW seven_and_me.v_stock_universe_latest_day AS
SELECT max(trading_day) AS trading_day
FROM seven_and_me.stock_universe_daily;

CREATE OR REPLACE VIEW seven_and_me.v_stock_universe_latest AS
SELECT d.*
FROM seven_and_me.stock_universe_daily d
JOIN seven_and_me.v_stock_universe_latest_day l
  ON l.trading_day = d.trading_day;

-- ============================================================================
-- updated_at triggers
-- ============================================================================

DO $$
DECLARE
    tbl TEXT;
    tables_with_updated_at TEXT[] := ARRAY[
        'instruments',
        'mp4_history',
        'stock_workspaces',
        'workspace_configs',
        'annotations',
        'kline_cache',
        'kline_bars',
        'intraday_cache',
        'intraday_ticks',
        'auction_cache',
        'market_breadth_latest',
        'market_breadth_series',
        'f10_cache',
        'f10_limit_count',
        'turnover_files',
        'turnover_entries',
        'app_analysis_targets',
        'app_analysis_horizon',
        'app_analysis_scheduler_state',
        'app_analysis_results',
        'app_analysis_history',
        'app_analysis_auction',
        'app_analysis_snapshots',
        'industry_app_targets',
        'industry_app_results',
        'industry_app_history',
        'self_selected_groups',
        'self_selected_items',
        'ths_industries',
        'ths_industry_info',
        'ths_industry_klines',
        'ths_industry_constituents_meta',
        'ths_industry_constituents',
        'stock_universe_daily',
        'stock_universe_codes',
        'stock_universe_failed_codes',
        'stock_universe_progress',
        'stock_universe_groups',
        'stock_universe_quote_cache',
        'stock_universe_shares_cache',
        'stock_universe_qt_fund_flow',
        'market_pulse_rotation',
        'sectors_concepts',
        'sectors_industries',
        'sectors_styles',
        'sectors_index',
        'tdx_industry_56',
        'scheduler_jobs',
        'scheduler_job_state',
        'stock_chart_config',
        'stock_chart_mootdx_servers'
    ];
BEGIN
    FOREACH tbl IN ARRAY tables_with_updated_at LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_trigger
            WHERE tgname = 'trg_set_updated_at'
              AND tgrelid = format('seven_and_me.%I', tbl)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_set_updated_at
                 BEFORE UPDATE ON seven_and_me.%I
                 FOR EACH ROW
                 EXECUTE FUNCTION seven_and_me.set_updated_at()',
                tbl
            );
        END IF;
    END LOOP;
END $$;

-- ============================================================================
-- 常用 JSONB 查询索引：默认只给较稳定/较小 payload，避免大 JSONB 全量 GIN 膨胀
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_f10_cache_payload_gin
ON seven_and_me.f10_cache USING GIN (payload jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_market_breadth_series_payload_gin
ON seven_and_me.market_breadth_series USING GIN (payload jsonb_path_ops)
WHERE payload IS NOT NULL;

-- ============================================================================
-- 分区辅助示例
-- 说明:
--   默认分区已经创建，可以直接插入。
--   上线后建议按月/季度提前建实际分区，然后逐步迁出 default partition。
--   示例:
--     CREATE TABLE seven_and_me.stock_universe_daily_2026_06
--       PARTITION OF seven_and_me.stock_universe_daily
--       FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
--
--     CREATE TABLE seven_and_me.ths_industry_constituents_2026_q2
--       PARTITION OF seven_and_me.ths_industry_constituents
--       FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
-- ============================================================================

-- ============================================================================
-- END
-- ============================================================================
