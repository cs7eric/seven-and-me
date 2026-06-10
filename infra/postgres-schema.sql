-- ============================================================================
-- mp4-to-word → PostgreSQL Schema
-- 文档:    infra/postgres-schema.md
-- 配套:    infra/persistence-inventory.md
-- 生成:    2026-06-09
-- PG 版本: 15+
-- schema:  app (业务单 schema, 不用 public)
-- 设计原则:
--   1. 缓存类 (kline/intraday/auction/f10) → JSONB payload, 复合 PK
--   2. 关系类 (self-selected / ths constituents) → 规范化
--   3. 单例状态 (scheduler live / breadth latest) → PK=1 + CHECK
--   4. 时序数据 (turnover entries / app analysis history) → 含 trade_date 的复合 PK + 倒序索引
--   5. upsert 全部走 ON CONFLICT, 复刻现有 "首次读落盘 + 后续覆写"
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS seven_and_me;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ============================================================================
-- §4 MP4 转写历史 (1 张)
-- 源: reference/parse/data/mp4-{uuid}.json (5 条)
--      reference/parse/index/index.json (索引)
-- ============================================================================

CREATE TABLE seven_and_me.mp4_history (
    id           TEXT PRIMARY KEY,                         -- 'mp4-{uuid}'
    task_id      TEXT NOT NULL UNIQUE,                     -- {uuid}, 对应 uploads/ 文件名
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('pending','running','done','error')),
    file_name    TEXT,
    transcript   TEXT,                                     -- Whisper 原文
    polished     TEXT,                                     -- MiniMax 润色
    summary      TEXT,                                     -- MiniMax 结构化总结
    metadata     JSONB,                                    -- {categories, tags, ...}
    created_at   TIMESTAMPTZ NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.mp4_history IS 'MP4 转写历史 (源: reference/parse/data/*.json, 当前 5 条)';

CREATE INDEX idx_mp4_history_created_at ON seven_and_me.mp4_history (created_at DESC);

-- ============================================================================
-- §5 个股 workspace + 渲染配置 + 标线 (3 张)
-- 源: reference/stock/index/workspaces.json (10 条)
--      reference/stock/data/snapshots/*.json (14 条)
--      reference/stock/data/annotations/*.json (7 文件, 多条)
-- ============================================================================

-- §5.1 stock_workspaces
CREATE TABLE seven_and_me.stock_workspaces (
    id            TEXT PRIMARY KEY,                         -- 'stock-{symbol}' 或 'index-{symbol}'
    target_type   TEXT NOT NULL CHECK (target_type IN ('stock','index','sector')),
    symbol        TEXT NOT NULL,
    name          TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.stock_workspaces IS '个股工作区 (源: reference/stock/index/workspaces.json, 当前 10 条)';

CREATE UNIQUE INDEX uq_stock_workspaces_type_symbol ON seven_and_me.stock_workspaces (target_type, symbol);
CREATE INDEX idx_stock_workspaces_updated_at ON seven_and_me.stock_workspaces (updated_at DESC);

-- §5.2 workspace_configs (1:1 → workspaces)
CREATE TABLE seven_and_me.workspace_configs (
    workspace_id         TEXT PRIMARY KEY REFERENCES seven_and_me.stock_workspaces(id) ON DELETE CASCADE,
    period               TEXT NOT NULL DEFAULT '1d' CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust               TEXT NOT NULL DEFAULT 'qfq' CHECK (adjust IN ('none','qfq','hfq')),
    indicators           TEXT[] NOT NULL DEFAULT '{}',
    drawing_tool         TEXT,
    show_auction_panel   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.workspace_configs IS '工作区渲染配置 (源: reference/stock/data/snapshots/*.json, 当前 14 条)';

-- §5.3 annotations (含 B/S 标记)
CREATE TABLE seven_and_me.annotations (
    id             TEXT PRIMARY KEY,                       -- 'anno-{ts}'
    target_id      TEXT NOT NULL,                          -- 'stock-{symbol}' 等
    period         TEXT NOT NULL,                          -- '1d' / '5m' / 'bs_signals'
    overlay_type   TEXT NOT NULL CHECK (overlay_type IN ('bs_point','trend_line','custom')),
    points         JSONB NOT NULL,                         -- [{timestamp, value}]
    styles         JSONB NOT NULL DEFAULT '{}'::jsonb,     -- {side: 'B'|'S', source, trade_date, ...}
    text           TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL,
    CHECK (
        overlay_type <> 'bs_point'
        OR (styles ? 'side' AND styles->>'side' IN ('B','S'))
    )
);
COMMENT ON TABLE seven_and_me.annotations IS '标线 + B/S 标记 (源: reference/stock/data/annotations/*.json, 当前 7 文件)';

CREATE INDEX idx_annotations_target_period ON seven_and_me.annotations (target_id, period, overlay_type);
CREATE INDEX idx_annotations_target ON seven_and_me.annotations (target_id);

-- ============================================================================
-- §6 行情缓存 (3 张)
-- 源: reference/stock/cache/klines/*.json (86 个)
--      reference/stock/cache/intraday/*.json (10 个)
--      reference/stock/cache/auction/*.json (15 个)
-- ============================================================================

-- §6.1 kline_cache (复合 PK, JSONB items)
CREATE TABLE seven_and_me.kline_cache (
    target_id    TEXT NOT NULL,
    period       TEXT NOT NULL CHECK (period IN ('1d','1w','5m','15m','30m','60m')),
    adjust       TEXT NOT NULL CHECK (adjust IN ('none','qfq','hfq')),
    source       TEXT,                                     -- 'tencent' / 'eastmoney' / 'mootdx'
    items        JSONB NOT NULL DEFAULT '[]'::jsonb,       -- [{timestamp, trade_date, open, close, high, low, volume, amount}, ...]
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (target_id, period, adjust)
);
COMMENT ON TABLE seven_and_me.kline_cache IS 'K线缓存 (源: reference/stock/cache/klines/, 当前 86 文件)';

-- §6.2 intraday_cache
CREATE TABLE seven_and_me.intraday_cache (
    target_id               TEXT NOT NULL,
    trade_date              DATE NOT NULL,
    requested_trade_date    DATE,
    effective_adjust        TEXT CHECK (effective_adjust IN ('none','qfq','hfq')),
    requested_adjust        TEXT CHECK (requested_adjust IN ('none','qfq','hfq')),
    timeshare               JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (target_id, trade_date)
);
COMMENT ON TABLE seven_and_me.intraday_cache IS '分时缓存 (源: reference/stock/cache/intraday/, 当前 10 文件)';

CREATE INDEX idx_intraday_cache_date ON seven_and_me.intraday_cache (trade_date DESC);

-- §6.3 auction_cache
CREATE TABLE seven_and_me.auction_cache (
    symbol       TEXT NOT NULL,
    trade_date   DATE NOT NULL,
    opening      JSONB NOT NULL,                            -- {time, price, volume, amount, matchPrice, unmatchedBuyVolume, ...}
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, trade_date)
);
COMMENT ON TABLE seven_and_me.auction_cache IS '集合竞价快照 (源: reference/stock/cache/auction/, 当前 15 文件)';

CREATE INDEX idx_auction_cache_date ON seven_and_me.auction_cache (trade_date DESC);

-- ============================================================================
-- §7 涨跌家数 (2 张)
-- 源: reference/stock/cache/breadth/{latest,series,eltdx_latest}.json
-- ============================================================================

-- §7.1 latest (单例)
CREATE TABLE seven_and_me.market_breadth_latest (
    id                  INT  PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    up_count            INT,
    down_count          INT,
    limit_up_count      INT,
    limit_down_count    INT,
    total_count         INT,
    break_rate          NUMERIC,
    max_lian_ban        INT,
    yesterday_limit_up_return NUMERIC,
    total_turnover      NUMERIC,
    down_over5_count    INT,
    new20_high_count    INT,
    new20_low_count     INT,
    source              TEXT,                                -- 'cfi' / 'eltdx'
    cached_at           TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.market_breadth_latest IS '涨跌家数 - 最新 (源: reference/stock/cache/breadth/latest.json, 单例)';

-- §7.2 series (历史时序)
CREATE TABLE seven_and_me.market_breadth_series (
    trade_date          DATE PRIMARY KEY,
    up_count            INT,
    down_count          INT,
    limit_up_count      INT,
    limit_down_count    INT,
    total_count         INT,
    source              TEXT,
    payload             JSONB,                                -- 完整原始结构
    updated_at          TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.market_breadth_series IS '涨跌家数 - 历史序列 (源: reference/stock/cache/breadth/series.json)';

CREATE INDEX idx_market_breadth_series_date ON seven_and_me.market_breadth_series (trade_date DESC);

-- ============================================================================
-- §8 F10 业务缓存 (2 张: 通用 + limit_count 独立)
-- 源: reference/stock/cache/f10/{12 个子目录}/ (110+ 文件)
-- ============================================================================

-- §8.1 f10_cache (通用: business_composition / company_profile / concept_sectors_market /
--                       finance_diagnosis / finance_report / governance /
--                       industry_sectors_market / profit_forecast / ranking_detail /
--                       sectors_market / stock_info / stock_score / theme_market /
--                       topics / turnover / valuation)
CREATE TABLE seven_and_me.f10_cache (
    category     TEXT NOT NULL,                              -- 'finance_report' 等
    key          TEXT NOT NULL,                              -- '{symbol}-{subkey}', e.g. '000001-lrb', 'c-6-涨跌幅-False-0-80'
    payload      JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (category, key)
);
COMMENT ON TABLE seven_and_me.f10_cache IS 'F10 业务通用缓存 (源: reference/stock/cache/f10/, 12 类业务共 110+ 文件)';

CREATE INDEX idx_f10_cache_category ON seven_and_me.f10_cache (category);

-- §8.2 f10_limit_count (独立: 数据量大, 需分页查询)
CREATE TABLE seven_and_me.f10_limit_count (
    trade_date         DATE PRIMARY KEY,
    up_count           INT NOT NULL DEFAULT 0,
    down_count         INT NOT NULL DEFAULT 0,
    flat_count         INT NOT NULL DEFAULT 0,
    limit_up_count     INT NOT NULL DEFAULT 0,
    limit_down_count   INT NOT NULL DEFAULT 0,
    total_count        INT NOT NULL,
    threshold_rules    JSONB,                                -- {main_board: 9.95, ...}
    payload            JSONB,                                -- 完整原始结构
    updated_at         TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.f10_limit_count IS '涨跌停统计 (源: reference/stock/cache/f10/limit_count/, 当前 1 文件)';

-- ============================================================================
-- §9 行业 index 覆盖 (1 张)
-- 源: reference/stock/cache/industry_index_overrides.json (2 条)
-- ============================================================================

CREATE TABLE seven_and_me.industry_index_overrides (
    code    TEXT PRIMARY KEY,                                -- 'sh881111'
    name    TEXT NOT NULL,
    kind    TEXT NOT NULL CHECK (kind IN ('sector','concept','industry','style'))
);
COMMENT ON TABLE seven_and_me.industry_index_overrides IS '行业 index 手动覆盖 (源: reference/stock/cache/industry_index_overrides.json, 2 条)';

-- ============================================================================
-- §10 换手率 (2 张: 元 + 明细)
-- 源: reference/stock/turnover/*.json (5 文件, 每个含 entries[])
-- ============================================================================

CREATE TABLE seven_and_me.turnover_files (
    symbol              TEXT NOT NULL,
    period              TEXT NOT NULL DEFAULT '1d',
    adjust              TEXT NOT NULL DEFAULT 'qfq',
    target_type         TEXT NOT NULL CHECK (target_type IN ('stock','index')),
    circulating_shares  NUMERIC,
    total_shares        NUMERIC,
    source              TEXT,                                -- 'eltdx'
    updated_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, period, adjust)
);
COMMENT ON TABLE seven_and_me.turnover_files IS '换手率文件元数据 (源: reference/stock/turnover/*.json, 5 文件)';

CREATE TABLE seven_and_me.turnover_entries (
    symbol           TEXT NOT NULL,
    period           TEXT NOT NULL DEFAULT '1d',
    adjust           TEXT NOT NULL DEFAULT 'qfq',
    trade_date       DATE NOT NULL,
    turnover_rate    NUMERIC,                                -- 换手率 (%)
    volume           NUMERIC,
    amount           NUMERIC,
    PRIMARY KEY (symbol, period, adjust, trade_date),
    FOREIGN KEY (symbol, period, adjust) REFERENCES seven_and_me.turnover_files(symbol, period, adjust) ON DELETE CASCADE
);
COMMENT ON TABLE seven_and_me.turnover_entries IS '换手率明细 (源: reference/stock/turnover/*/entries[])';

CREATE INDEX idx_turnover_entries_date ON seven_and_me.turnover_entries (trade_date DESC);
CREATE INDEX idx_turnover_entries_symbol ON seven_and_me.turnover_entries (symbol, trade_date DESC);

-- ============================================================================
-- §11 个股应用分析 (6 张)
-- 源: reference/application-analysis/* (target=6, results=6, history=523, auction=7, snapshots=13)
-- ============================================================================

-- §11.1 targets
CREATE TABLE seven_and_me.app_analysis_targets (
    id                TEXT PRIMARY KEY,                       -- 'stock-600415'
    target_type       TEXT NOT NULL CHECK (target_type IN ('stock','index')),
    symbol            TEXT NOT NULL,
    name              TEXT NOT NULL,
    adjust            TEXT NOT NULL DEFAULT 'qfq',
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    interval_minutes  INT NOT NULL DEFAULT 60,
    tags              TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.app_analysis_targets IS '应用分析 target 列表 (源: reference/application-analysis/targets.json, 6 条)';

-- §11.1b horizon (全局共享, 单例)
CREATE TABLE seven_and_me.app_analysis_horizon (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    days            INT NOT NULL DEFAULT 120,
    segments        INT NOT NULL DEFAULT 4,
    monthly_keep    INT NOT NULL DEFAULT 6,
    weekly_keep     INT NOT NULL DEFAULT 12,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.app_analysis_horizon IS '应用分析 horizon 全局配置 (单例)';

-- §11.2 scheduler_state (单例)
CREATE TABLE seven_and_me.app_analysis_scheduler_state (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    running         BOOLEAN NOT NULL DEFAULT FALSE,
    started_at      TIMESTAMPTZ,
    tick_count      BIGINT NOT NULL DEFAULT 0,
    runs_count      BIGINT NOT NULL DEFAULT 0,
    last_tick_at    TIMESTAMPTZ,
    last_run        JSONB,                                    -- {target_id: {status, elapsed_seconds, source, finished_at, ...}}
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.app_analysis_scheduler_state IS '应用分析 scheduler 实时状态 (源: reference/application-analysis/scheduler.json, 单例)';

-- §11.3 results (1:1 → targets)
CREATE TABLE seven_and_me.app_analysis_results (
    target_id       TEXT PRIMARY KEY REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    target_type     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    name            TEXT NOT NULL,
    adjust          TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL,
    overlay_count   INT,
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,                                    -- 含 daily_segments[].items[]
    analysis_output JSONB
);
COMMENT ON TABLE seven_and_me.app_analysis_results IS '应用分析最新结果 (源: reference/application-analysis/results/, 6 文件)';

-- §11.4 history (时序, 倒序索引)
CREATE TABLE seven_and_me.app_analysis_history (
    id              TEXT PRIMARY KEY,                         -- '{target_id}-{finished_at_iso}'
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('success','error','running')),
    elapsed_seconds NUMERIC,
    source          TEXT,                                     -- 'scheduler' / 'manual'
    finished_at     TIMESTAMPTZ NOT NULL,
    overlay_count   INT,
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.app_analysis_history IS '应用分析历史 (源: reference/application-analysis/history/, 523 文件)';

CREATE INDEX idx_app_analysis_history_target_time ON seven_and_me.app_analysis_history (target_id, finished_at DESC);
CREATE INDEX idx_app_analysis_history_time ON seven_and_me.app_analysis_history (finished_at DESC);

-- §11.5 auction (每日每 target)
CREATE TABLE seven_and_me.app_analysis_auction (
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB,
    updated_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (target_id, trade_date)
);
COMMENT ON TABLE seven_and_me.app_analysis_auction IS '应用分析集合竞价 AI (源: reference/application-analysis/auction/, 7 文件)';

CREATE INDEX idx_app_analysis_auction_date ON seven_and_me.app_analysis_auction (trade_date DESC);

-- §11.6 snapshots (盘后 15:30 recent30)
CREATE TABLE seven_and_me.app_analysis_snapshots (
    target_id       TEXT NOT NULL REFERENCES seven_and_me.app_analysis_targets(id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    snapshot        JSONB,                                    -- recent30 K线分段 + AI 摘要
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (target_id, trade_date)
);
COMMENT ON TABLE seven_and_me.app_analysis_snapshots IS '应用分析盘后快照 (源: reference/application-analysis/snapshots/, 13 文件)';

CREATE INDEX idx_app_analysis_snapshots_date ON seven_and_me.app_analysis_snapshots (trade_date DESC);

-- ============================================================================
-- §12 行业应用分析 (3 张, 同构于 §11)
-- 源: reference/industry-application/* (target=4, results=3, history=5)
-- ============================================================================

CREATE TABLE seven_and_me.industry_app_targets (
    id                TEXT PRIMARY KEY,                       -- 'industry-sh880301'
    target_type       TEXT NOT NULL CHECK (target_type IN ('industry','concept')),
    symbol            TEXT NOT NULL,                          -- 'sh880301'
    name              TEXT NOT NULL,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    interval_minutes  INT NOT NULL DEFAULT 60,
    tags              TEXT[] NOT NULL DEFAULT '{}',
    horizon_days      INT NOT NULL DEFAULT 120,
    horizon_segments  INT NOT NULL DEFAULT 4,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.industry_app_targets IS '行业应用分析 target 列表 (源: reference/industry-application/targets.json, 4 条)';

CREATE TABLE seven_and_me.industry_app_results (
    target_id       TEXT PRIMARY KEY REFERENCES seven_and_me.industry_app_targets(id) ON DELETE CASCADE,
    target_type     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    name            TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    segments        INT,
    horizon         JSONB,
    target          JSONB,
    analysis_input  JSONB,
    analysis_output JSONB
);
COMMENT ON TABLE seven_and_me.industry_app_results IS '行业应用分析最新结果 (源: reference/industry-application/results/, 3 文件)';

CREATE TABLE seven_and_me.industry_app_history (
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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.industry_app_history IS '行业应用分析历史 (源: reference/industry-application/history/, 5 文件)';

CREATE INDEX idx_industry_app_history_target_time ON seven_and_me.industry_app_history (target_id, finished_at DESC);

-- ============================================================================
-- §13 自选股 (2 张, FK 级联)
-- 源: reference/self-selected/{groups,items}.json (2 组, 1 标)
-- ============================================================================

CREATE TABLE seven_and_me.self_selected_groups (
    id          TEXT PRIMARY KEY,                            -- 'ss-grp-{ts}-{rand}'
    name        TEXT NOT NULL,
    description TEXT,
    color       TEXT NOT NULL DEFAULT 'blue',
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.self_selected_groups IS '自选股分组 (源: reference/self-selected/groups.json, 2 条)';

CREATE INDEX idx_self_selected_groups_sort ON seven_and_me.self_selected_groups (sort_order, created_at);

CREATE TABLE seven_and_me.self_selected_items (
    id          TEXT PRIMARY KEY,                            -- 'ss-itm-{ts}-{rand}'
    group_id    TEXT NOT NULL REFERENCES seven_and_me.self_selected_groups(id) ON DELETE CASCADE,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL CHECK (market IN ('SH','SZ','BJ','HK','US')),
    name        TEXT NOT NULL,
    notes       TEXT,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (group_id, symbol, market)                        -- 同组不重复加同标的
);
COMMENT ON TABLE seven_and_me.self_selected_items IS '自选股标的 (源: reference/self-selected/items.json, 1 条)';

CREATE INDEX idx_self_selected_items_group ON seven_and_me.self_selected_items (group_id, sort_order);

-- ============================================================================
-- §14 同花顺行业 / 资金 (5 张)
-- 源: reference/ths-fund-flow/* (latest + 1 history)
--      reference/ths-industry/* (industry_list / info / kline / constituents × 90)
-- ============================================================================

-- §14.1 ths_fund_flow_daily (latest 用 SELECT MAX(trade_date))
CREATE TABLE seven_and_me.ths_fund_flow_daily (
    trade_date        DATE PRIMARY KEY,
    ok                BOOLEAN NOT NULL,
    row_count         INT NOT NULL,
    total_pages       INT NOT NULL,
    page_row_counts   INT[] NOT NULL DEFAULT '{}',
    fetched_at        TIMESTAMPTZ NOT NULL,
    rows              JSONB NOT NULL DEFAULT '[]'::jsonb     -- 11 列 × 90 行业
);
COMMENT ON TABLE seven_and_me.ths_fund_flow_daily IS '同花顺全行业主力资金 (源: reference/ths-fund-flow/history/, 当前 1 文件 + latest)';

CREATE INDEX idx_ths_fund_flow_daily_date ON seven_and_me.ths_fund_flow_daily (fetched_at DESC);

-- §14.2 ths_industries (90 行业字典)
CREATE TABLE seven_and_me.ths_industries (
    code            TEXT PRIMARY KEY,                        -- '881121'
    name            TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ
);
COMMENT ON TABLE seven_and_me.ths_industries IS '同花顺 90 行业字典 (源: reference/ths-industry/industry_list.json, 90 条)';

-- §14.3 ths_industry_info (9 项 × 每日)
CREATE TABLE seven_and_me.ths_industry_info (
    industry_code    TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    trade_date       DATE NOT NULL,
    data             JSONB NOT NULL,                          -- 9 项: 今开/昨收/最高/最低/成交量/成交额/涨跌幅/涨跌额/振幅/换手率
    fetched_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (industry_code, trade_date)
);
COMMENT ON TABLE seven_and_me.ths_industry_info IS '同花顺 90 行业 9 项实时 (源: reference/ths-industry/industry_info.json)';

-- §14.4 ths_industry_klines
CREATE TABLE seven_and_me.ths_industry_klines (
    industry_code   TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    data            JSONB NOT NULL,                          -- OHLCV
    fetched_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (industry_code, trade_date)
);
COMMENT ON TABLE seven_and_me.ths_industry_klines IS '同花顺 90 行业 K 线 (源: reference/ths-industry/kline/, ~975 bars × 90 行业)';

-- §14.5 ths_industry_constituents_meta (每个 snapshot 的元)
CREATE TABLE seven_and_me.ths_industry_constituents_meta (
    industry_code      TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    snapshot_date      DATE NOT NULL,                         -- 周频, 周六 18:00 重爬
    ok                 BOOLEAN NOT NULL,
    total_pages        INT NOT NULL,
    page_row_counts    INT[] NOT NULL DEFAULT '{}',
    row_count          INT NOT NULL,
    fetched_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (industry_code, snapshot_date)
);
COMMENT ON TABLE seven_and_me.ths_industry_constituents_meta IS '同花顺 90 行业成分股 snapshot 元数据 (源: reference/ths-industry/constituents/, 周频)';

CREATE INDEX idx_ths_industry_constituents_meta_date ON seven_and_me.ths_industry_constituents_meta (snapshot_date DESC);

-- §14.6 ths_industry_constituents (明细, 90 × 4666 = ~420K 行)
CREATE TABLE seven_and_me.ths_industry_constituents (
    industry_code     TEXT NOT NULL REFERENCES seven_and_me.ths_industries(code) ON DELETE CASCADE,
    snapshot_date     DATE NOT NULL,
    seq               INT,                                    -- 序号
    stock_code        TEXT NOT NULL,                          -- 成分股 code
    stock_name        TEXT NOT NULL,
    payload           JSONB NOT NULL,                         -- 14 列全量 (现价/涨跌幅/涨跌/涨速/换手/量比/振幅/成交额/流通股/流通市值/市盈率)
    PRIMARY KEY (industry_code, snapshot_date, stock_code),
    FOREIGN KEY (industry_code, snapshot_date) REFERENCES seven_and_me.ths_industry_constituents_meta(industry_code, snapshot_date) ON DELETE CASCADE
);
COMMENT ON TABLE seven_and_me.ths_industry_constituents IS '同花顺 90 行业成分股明细 (源: reference/ths-industry/constituents/, ~4666 股 × 周频)';

CREATE INDEX idx_ths_industry_constituents_stock ON seven_and_me.ths_industry_constituents (stock_code);

-- ============================================================================
-- §15 A 股全市场 (14 张)
-- 源: reference/stock-universe/*
-- ============================================================================

-- §15.1 stock_universe_daily (主表, 5530 × 每日)
CREATE TABLE seven_and_me.stock_universe_daily (
    trading_day    DATE NOT NULL,
    code           TEXT NOT NULL,                            -- 'sh600415' / 'sz000001' / 'bj920022'
    name           TEXT,
    industry       TEXT,                                     -- TDX 归一后行业名
    raw            JSONB,                                    -- 完整原始结构
    fetched_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (trading_day, code)
);
COMMENT ON TABLE seven_and_me.stock_universe_daily IS 'A 股全市场每日快照 (源: reference/stock-universe/YYYY-MM-DD.json, 5530 行 × 日)';

CREATE INDEX idx_stock_universe_daily_day ON seven_and_me.stock_universe_daily (trading_day);
CREATE INDEX idx_stock_universe_daily_code ON seven_and_me.stock_universe_daily (code);

-- §15.2 stock_universe_daily_topics (多对多)
CREATE TABLE seven_and_me.stock_universe_daily_topics (
    trading_day    DATE NOT NULL,
    code           TEXT NOT NULL,
    topic_id       TEXT NOT NULL,
    topic_name     TEXT,
    PRIMARY KEY (trading_day, code, topic_id),
    FOREIGN KEY (trading_day, code) REFERENCES seven_and_me.stock_universe_daily(trading_day, code) ON DELETE CASCADE
);
COMMENT ON TABLE seven_and_me.stock_universe_daily_topics IS 'A 股全市场每日快照 - 题材 M2M';

CREATE INDEX idx_stock_universe_daily_topics_topic ON seven_and_me.stock_universe_daily_topics (topic_id, trading_day);
CREATE INDEX idx_stock_universe_daily_topics_code ON seven_and_me.stock_universe_daily_topics (code);

-- §15.3 stock_universe_codes (全 A 股 code 列表, ~5530)
CREATE TABLE seven_and_me.stock_universe_codes (
    code        TEXT PRIMARY KEY,                            -- 'sh600415'
    listed_market TEXT NOT NULL CHECK (listed_market IN ('SH','SZ','BJ')),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.stock_universe_codes IS '全 A 股 code 列表 (源: reference/stock-universe/_codes.json)';

-- §15.4 stock_universe_failed_codes (拉取失败记录)
CREATE TABLE seven_and_me.stock_universe_failed_codes (
    code             TEXT PRIMARY KEY,
    last_failed_at   TIMESTAMPTZ NOT NULL,
    reason           TEXT
);
COMMENT ON TABLE seven_and_me.stock_universe_failed_codes IS '全 A 股拉取失败记录 (源: reference/stock-universe/_failed_codes.json)';

-- §15.5 stock_universe_progress (单例)
CREATE TABLE seven_and_me.stock_universe_progress (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    total           INT,
    completed       INT,
    last_updated_at TIMESTAMPTZ,
    payload         JSONB
);
COMMENT ON TABLE seven_and_me.stock_universe_progress IS '全 A 股拉取进度 (源: reference/stock-universe/_progress.json, 单例)';

-- §15.6 stock_universe_groups (分片桶)
CREATE TABLE seven_and_me.stock_universe_groups (
    group_id     TEXT PRIMARY KEY,                           -- '0001' ~ '0007'
    payload      JSONB NOT NULL,                             -- 该桶的 stock 数组
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.stock_universe_groups IS '全 A 股分片桶 (源: reference/stock-universe/groups/, 7 文件)';

-- §15.7 stock_universe_quote_cache (当日行情缓存)
CREATE TABLE seven_and_me.stock_universe_quote_cache (
    trade_date   DATE PRIMARY KEY,
    payload      JSONB NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.stock_universe_quote_cache IS '全 A 股行情缓存 (源: reference/stock-universe/_quote_cache/)';

-- §15.8 stock_universe_shares_cache (股本)
CREATE TABLE seven_and_me.stock_universe_shares_cache (
    trade_date    DATE PRIMARY KEY,
    shares        JSONB NOT NULL,                            -- {code: float, ...}
    source        TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.stock_universe_shares_cache IS '全 A 股股本缓存 (源: reference/stock-universe/_shares_cache/)';

-- §15.9 stock_universe_qt_fund_flow (qt.gtimg.cn 个股资金流)
CREATE TABLE seven_and_me.stock_universe_qt_fund_flow (
    code           TEXT NOT NULL,                            -- 'sh600519'
    snapshot_date  DATE NOT NULL,
    data           JSONB NOT NULL,                           -- 88 字段
    fetched_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (code, snapshot_date)
);
COMMENT ON TABLE seven_and_me.stock_universe_qt_fund_flow IS 'qt.gtimg.cn 个股资金流 (源: reference/stock-universe/qt_fund_flow/, 当前 5 只)';

-- §15.10 market_pulse_rotation (行情页轮动 Top N)
CREATE TABLE seven_and_me.market_pulse_rotation (
    trade_date    DATE PRIMARY KEY,
    top_n         INT NOT NULL,
    items         JSONB NOT NULL,                            -- [{name, changePct, mainNet, inflow, outflow, stockCount, leadingStock, leadingChangePct, rank}]
    source        TEXT,                                      -- 'akshare.stock_fund_flow_industry (10jqka)'
    fetched_at    TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.market_pulse_rotation IS '行情页 15:30 收盘 Top N 快照 (源: reference/stock-universe/market_pulse/rotation/, 3 文件)';

CREATE INDEX idx_market_pulse_rotation_date ON seven_and_me.market_pulse_rotation (fetched_at DESC);

-- §15.11 sectors_concepts (270 概念)
CREATE TABLE seven_and_me.sectors_concepts (
    topic_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ
);
COMMENT ON TABLE seven_and_me.sectors_concepts IS '概念板块字典 (源: reference/stock-universe/sectors/sectors_concepts_2.json, 270 条)';

-- §15.12 sectors_industries
CREATE TABLE seven_and_me.sectors_industries (
    industry_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ
);
COMMENT ON TABLE seven_and_me.sectors_industries IS '行业板块字典';

-- §15.13 sectors_styles
CREATE TABLE seven_and_me.sectors_styles (
    style_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ
);
COMMENT ON TABLE seven_and_me.sectors_styles IS '风格板块字典';

-- §15.14 sectors_index (单例)
CREATE TABLE seven_and_me.sectors_index (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    payload         JSONB NOT NULL,                          -- {concepts, industries, styles 索引}
    updated_at      TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE seven_and_me.sectors_index IS '板块顶层索引 (源: reference/stock-universe/sectors/index.json, 单例)';

-- §15.15 tdx_industry_56 (TDX 56 行业)
CREATE TABLE seven_and_me.tdx_industry_56 (
    industry_code   TEXT PRIMARY KEY,
    name            TEXT NOT NULL
);
COMMENT ON TABLE seven_and_me.tdx_industry_56 IS 'TDX 56 行业映射 (源: reference/stock-universe/tdx_industry_56.json, 56 条)';

-- ============================================================================
-- §16 Scheduler (6 张)
-- 源: scheduler/jobs.json (8 个 job)
--      scheduler/{5 个}_job.json (实时状态)
-- ============================================================================

-- §16.1 scheduler_jobs (注册表)
CREATE TABLE seven_and_me.scheduler_jobs (
    id              TEXT PRIMARY KEY,                        -- 'turnover_refresh' 等
    name            TEXT NOT NULL,
    description     TEXT,
    config_file     TEXT,
    service_module  TEXT,
    service_class   TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at   TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_jobs IS 'Scheduler 注册表 (源: scheduler/jobs.json, 8 个 job)';

CREATE INDEX idx_scheduler_jobs_enabled ON seven_and_me.scheduler_jobs (enabled) WHERE enabled = TRUE;

-- §16.2 scheduler_turnover_state (单例)
CREATE TABLE seven_and_me.scheduler_turnover_state (
    id                       INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    job_name                 TEXT NOT NULL,
    enabled                  BOOLEAN NOT NULL,
    schedule                 JSONB NOT NULL,                  -- {workday_only, intraday_windows, post_close_run}
    timezone_offset_hours   INT NOT NULL,
    tick_seconds             INT NOT NULL,
    last_run_at              TIMESTAMPTZ,
    last_run_slot            TEXT,
    last_run_date            DATE,
    last_status              TEXT,
    last_targets_processed   INT,
    last_duration_seconds    NUMERIC,
    last_error               TEXT,
    total_runs               BIGINT,
    total_targets_processed  BIGINT,
    total_failures           BIGINT,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_turnover_state IS '换手率 scheduler 状态 (源: scheduler/turnover_job.json, 单例)';

-- §16.3 scheduler_auction_state (单例)
CREATE TABLE seven_and_me.scheduler_auction_state (
    id                       INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    job_name                 TEXT NOT NULL,
    enabled                  BOOLEAN NOT NULL,
    schedule                 JSONB NOT NULL,                  -- {workday_only, run_time, run_once_per_day}
    timezone_offset_hours   INT NOT NULL,
    tick_seconds             INT NOT NULL,
    last_run_at              TIMESTAMPTZ,
    last_run_date            DATE,
    last_status              TEXT,
    last_targets_processed   INT,
    last_duration_seconds    NUMERIC,
    last_error               TEXT,
    total_runs               BIGINT,
    total_targets_processed  BIGINT,
    total_failures           BIGINT,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_auction_state IS '集合竞价 AI scheduler 状态 (源: scheduler/auction_analysis_job.json, 单例)';

-- §16.4 scheduler_market_pulse_state (单例)
CREATE TABLE seven_and_me.scheduler_market_pulse_state (
    id                              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    name                            TEXT NOT NULL,
    last_run_at                     TIMESTAMPTZ,
    last_run_ok                     BOOLEAN,
    last_run_error                  TEXT,
    last_inside_refresh_at          TIMESTAMPTZ,
    last_close_snapshot_at          TIMESTAMPTZ,
    total_inside                    BIGINT,
    total_close                     BIGINT,
    scheduler_started_at            TIMESTAMPTZ,
    last_top_n                      JSONB,                       -- [{name, changePct}]
    last_constituents_at            TIMESTAMPTZ,
    last_constituents_ok            BOOLEAN,
    last_constituents_error         TEXT,
    last_constituents_elapse_ms     BIGINT,
    last_constituents_industries_ok INT,
    last_constituents_industries_total INT,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_market_pulse_state IS '行情页 scheduler 状态 (源: scheduler/market_pulse_job.json, 单例)';

-- §16.5 scheduler_stock_universe_state (单例)
CREATE TABLE seven_and_me.scheduler_stock_universe_state (
    id                       INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    job_name                 TEXT NOT NULL,
    enabled                  BOOLEAN NOT NULL,
    schedule                 JSONB NOT NULL,
    timezone_offset_hours   INT NOT NULL,
    tick_seconds             INT NOT NULL,
    last_run_at              TIMESTAMPTZ,
    last_run_slot            TEXT,
    last_run_date            DATE,
    last_status              TEXT,
    last_stock_count         INT,
    last_industry_count      INT,
    last_topic_count         INT,
    last_duration_seconds    NUMERIC,
    last_error               TEXT,
    last_file                TEXT,
    total_runs               BIGINT,
    total_failures           BIGINT,
    last_log_file            TEXT,
    last_exit_code           INT,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_stock_universe_state IS 'A 股全市场 scheduler 状态 (源: scheduler/stock_universe_job.json, 单例)';

-- §16.6 scheduler_ths_industry_constituents_state (单例)
CREATE TABLE seven_and_me.scheduler_ths_industry_constituents_state (
    id                            INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    job_name                      TEXT NOT NULL,
    enabled                       BOOLEAN NOT NULL,
    schedule                      JSONB NOT NULL,
    timezone_offset_hours        INT NOT NULL,
    tick_seconds                  INT NOT NULL,
    inter_industry_sleep_seconds  NUMERIC,
    inter_industry_sleep_jitter   NUMERIC,
    last_run_at                   TIMESTAMPTZ,
    last_run_week                 TEXT,
    last_run_weekday              INT,
    last_status                   TEXT,
    last_industry_count           INT,
    last_total_rows               BIGINT,
    last_failed_codes             TEXT[],
    last_duration_seconds         NUMERIC,
    last_error                    TEXT,
    total_runs                    BIGINT,
    total_industries_crawled      BIGINT,
    total_failures                BIGINT,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.scheduler_ths_industry_constituents_state IS '同花顺 90 行业成分股 scheduler 状态 (源: scheduler/ths_industry_constituents_job.json, 单例)';

-- ============================================================================
-- §17 K 线数据源配置 (2 张)
-- 源: reference/stock/index/stock_chart_config.json
-- ============================================================================

-- §17.1 stock_chart_config (单例)
CREATE TABLE seven_and_me.stock_chart_config (
    id                   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    minute_provider      TEXT NOT NULL,
    daily_provider       TEXT NOT NULL,
    weekly_provider      TEXT NOT NULL,
    minute_fallback      TEXT[] NOT NULL DEFAULT '{}',
    daily_fallback       TEXT[] NOT NULL DEFAULT '{}',
    weekly_fallback      TEXT[] NOT NULL DEFAULT '{}',
    mootdx_timeout       INT NOT NULL DEFAULT 10,
    minute_adjust_mode   TEXT NOT NULL DEFAULT 'none_only',
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE seven_and_me.stock_chart_config IS 'K 线数据源配置 (源: reference/stock/index/stock_chart_config.json, 单例)';

-- §17.2 stock_chart_mootdx_servers
CREATE TABLE seven_and_me.stock_chart_mootdx_servers (
    id          BIGSERIAL PRIMARY KEY,
    host        TEXT NOT NULL,
    port        INT  NOT NULL,
    sort_order  INT  NOT NULL DEFAULT 0,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE seven_and_me.stock_chart_mootdx_servers IS 'mootdx TDX 服务器列表 (源: reference/stock/index/stock_chart_config.json:mootdx.servers, 当前 3 条)';

-- ============================================================================
-- §便利视图 (可选)
-- ============================================================================

-- 同花顺全行业资金最新一份
CREATE OR REPLACE VIEW seven_and_me.v_ths_fund_flow_latest AS
SELECT * FROM seven_and_me.ths_fund_flow_daily
ORDER BY trade_date DESC LIMIT 1;

-- 行情页 latest market_pulse
CREATE OR REPLACE VIEW seven_and_me.v_market_pulse_rotation_latest AS
SELECT * FROM seven_and_me.market_pulse_rotation
ORDER BY trade_date DESC LIMIT 1;

-- 自选股 items JOIN groups (前端直接 SELECT 即可拿到 group_name)
CREATE OR REPLACE VIEW seven_and_me.v_self_selected_items AS
SELECT i.*, g.name AS group_name, g.color AS group_color
FROM seven_and_me.self_selected_items i
JOIN seven_and_me.self_selected_groups g ON g.id = i.group_id;

-- 应用分析 history + target name
CREATE OR REPLACE VIEW seven_and_me.v_app_analysis_history AS
SELECT h.*, t.name AS target_name, t.adjust AS target_adjust
FROM seven_and_me.app_analysis_history h
JOIN seven_and_me.app_analysis_targets t ON t.id = h.target_id;

-- ============================================================================
-- §END
-- ============================================================================