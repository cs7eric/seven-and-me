-- ============================================================================
-- Schema delta: sectors_* tables use BIGSERIAL id (v3 of scheme.sql)
-- Apply BEFORE running infra/seed.sql (which inserts into these tables)
--
-- If you're creating schema fresh, just replace the sectors_* definitions
-- in scheme.sql with these.
--
-- If you already applied scheme.sql with TEXT topic_id / industry_id / style_id,
-- run the migration block at the bottom.
-- ============================================================================

-- ---------- REPLACEMENT TABLE DEFINITIONS (copy-paste into scheme.sql) ------

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_concepts (
    id                 BIGSERIAL PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    source_updated_at  TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE seven_and_me.sectors_concepts IS '概念板块字典 (源: sectors_concepts_2.json, 270 条)';

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_industries (
    id                 BIGSERIAL PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    source_updated_at  TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE seven_and_me.sectors_industries IS '行业板块字典';

CREATE TABLE IF NOT EXISTS seven_and_me.sectors_styles (
    id                 BIGSERIAL PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    source_updated_at  TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE seven_and_me.sectors_styles IS '风格板块字典';

-- ---------- MIGRATION (only if TEXT PK version already exists) --------------

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='seven_and_me' AND table_name='sectors_concepts' AND column_name='topic_id'
    ) THEN
        ALTER TABLE seven_and_me.sectors_concepts DROP CONSTRAINT IF EXISTS sectors_concepts_pkey;
        ALTER TABLE seven_and_me.sectors_concepts ADD COLUMN IF NOT EXISTS id BIGSERIAL PRIMARY KEY;
        ALTER TABLE seven_and_me.sectors_concepts ADD CONSTRAINT sectors_concepts_name_key UNIQUE (name);
        ALTER TABLE seven_and_me.sectors_concepts DROP COLUMN IF EXISTS topic_id;
        CREATE SEQUENCE IF NOT EXISTS seven_and_me.sectors_concepts_id_seq OWNED BY seven_and_me.sectors_concepts.id;
        PERFORM setval('seven_and_me.sectors_concepts_id_seq', COALESCE((SELECT MAX(id) FROM seven_and_me.sectors_concepts), 1));
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='seven_and_me' AND table_name='sectors_industries' AND column_name='industry_id'
    ) THEN
        ALTER TABLE seven_and_me.sectors_industries DROP CONSTRAINT IF EXISTS sectors_industries_pkey;
        ALTER TABLE seven_and_me.sectors_industries ADD COLUMN IF NOT EXISTS id BIGSERIAL PRIMARY KEY;
        ALTER TABLE seven_and_me.sectors_industries ADD CONSTRAINT sectors_industries_name_key UNIQUE (name);
        ALTER TABLE seven_and_me.sectors_industries DROP COLUMN IF EXISTS industry_id;
        CREATE SEQUENCE IF NOT EXISTS seven_and_me.sectors_industries_id_seq OWNED BY seven_and_me.sectors_industries.id;
        PERFORM setval('seven_and_me.sectors_industries_id_seq', COALESCE((SELECT MAX(id) FROM seven_and_me.sectors_industries), 1));
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='seven_and_me' AND table_name='sectors_styles' AND column_name='style_id'
    ) THEN
        ALTER TABLE seven_and_me.sectors_styles DROP CONSTRAINT IF EXISTS sectors_styles_pkey;
        ALTER TABLE seven_and_me.sectors_styles ADD COLUMN IF NOT EXISTS id BIGSERIAL PRIMARY KEY;
        ALTER TABLE seven_and_me.sectors_styles ADD CONSTRAINT sectors_styles_name_key UNIQUE (name);
        ALTER TABLE seven_and_me.sectors_styles DROP COLUMN IF EXISTS style_id;
        CREATE SEQUENCE IF NOT EXISTS seven_and_me.sectors_styles_id_seq OWNED BY seven_and_me.sectors_styles.id;
        PERFORM setval('seven_and_me.sectors_styles_id_seq', COALESCE((SELECT MAX(id) FROM seven_and_me.sectors_styles), 1));
    END IF;
END $$;