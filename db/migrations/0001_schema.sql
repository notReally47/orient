CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS instruments
(
    symbol      text PRIMARY KEY,
    asset_class text NOT NULL CHECK (asset_class IN ('equity', 'etf', 'index', 'future', 'currency', 'crypto', 'fund')),
    name        text NOT NULL,
    sector      text,
    exchange    text,
    currency    text
);

CREATE TABLE IF NOT EXISTS bars
(
    symbol       text             NOT NULL,
    session_date date             NOT NULL,
    open         double precision NOT NULL,
    high         double precision NOT NULL,
    low          double precision NOT NULL,
    close        double precision NOT NULL,
    volume       bigint           NOT NULL,
    PRIMARY KEY (symbol, session_date)
);

CREATE TABLE IF NOT EXISTS sessions
(
    symbol          text        NOT NULL REFERENCES instruments (symbol) ON DELETE CASCADE,
    session_date    date        NOT NULL,
    signals_version text        NOT NULL,
    signals         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, session_date, signals_version)
);

CREATE INDEX IF NOT EXISTS sessions_symbol_date ON sessions (symbol, session_date DESC);

CREATE TABLE IF NOT EXISTS summaries
(
    id               uuid PRIMARY KEY,
    symbol           text        NOT NULL REFERENCES instruments (symbol) ON DELETE CASCADE,
    session_date     date        NOT NULL,
    level            text        NOT NULL CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    status           text        NOT NULL CHECK (status IN ('ok', 'caveated')),
    thesis           text        NOT NULL DEFAULT '',
    sections         jsonb       NOT NULL,
    annotations      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    calendar         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    signals_snapshot jsonb       NOT NULL,
    signals_version  text        NOT NULL,
    skill_version    text        NOT NULL,
    pinned           boolean     NOT NULL DEFAULT false,
    trace_id         text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS summaries_cache_key
    ON summaries (symbol, session_date, level, signals_version, skill_version);

CREATE INDEX IF NOT EXISTS summaries_recent ON summaries (symbol, session_date DESC);
CREATE INDEX IF NOT EXISTS summaries_pinned ON summaries (created_at DESC) WHERE pinned;

CREATE TABLE IF NOT EXISTS claims
(
    id                uuid PRIMARY KEY,
    summary_id        uuid        NOT NULL REFERENCES summaries (id) ON DELETE CASCADE,
    subject_symbol    text        NOT NULL,
    mentioned_symbols text[]      NOT NULL DEFAULT '{}',
    session_date      date        NOT NULL,
    kind              text        NOT NULL CHECK (kind IN ('attribution', 'expectation', 'anomaly')),
    statement         text        NOT NULL,
    attribution       text,
    target_date       date,
    resolved_by       uuid        REFERENCES claims (id) ON DELETE SET NULL,
    resolution        text CHECK (resolution IN ('supported', 'contradicted', 'unresolved')),
    embedding         vector(1536),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT claims_attribution_has_a_cause
        CHECK (kind <> 'attribution' OR attribution IS NOT NULL),
    CONSTRAINT claims_expectation_has_a_date
        CHECK (kind <> 'expectation' OR target_date IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS claims_subject_date ON claims (subject_symbol, session_date DESC);
CREATE INDEX IF NOT EXISTS claims_mentions ON claims USING gin (mentioned_symbols);
CREATE INDEX IF NOT EXISTS claims_open ON claims (subject_symbol, target_date) WHERE resolved_by IS NULL;
CREATE INDEX IF NOT EXISTS claims_embedding ON claims USING hnsw (embedding vector_cosine_ops);