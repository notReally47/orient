CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS instruments (
    symbol       text PRIMARY KEY,
    asset_class  text NOT NULL CHECK (asset_class IN ('equity', 'etf', 'index', 'future', 'currency', 'crypto', 'fund')),
    name         text NOT NULL,
    sector       text,
    exchange     text,
    currency     text,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    symbol          text NOT NULL REFERENCES instruments (symbol) ON DELETE CASCADE,
    session_date    date NOT NULL,
    signals_version text NOT NULL,
    signals         jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, session_date, signals_version)
);

CREATE INDEX IF NOT EXISTS sessions_symbol_date ON sessions (symbol, session_date DESC);

CREATE TABLE IF NOT EXISTS runs (
    id            uuid PRIMARY KEY,
    trace_id      text,
    symbol        text NOT NULL,
    session_date  date NOT NULL,
    level         text NOT NULL CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    status        text NOT NULL CHECK (status IN ('running', 'ok', 'caveated', 'failed', 'cancelled')),
    phase_timings jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_usage   jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);

CREATE TABLE IF NOT EXISTS summaries (
    id               uuid PRIMARY KEY,
    symbol           text NOT NULL REFERENCES instruments (symbol) ON DELETE CASCADE,
    session_date     date NOT NULL,
    level            text NOT NULL CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    status           text NOT NULL CHECK (status IN ('ok', 'caveated')),
    sections         jsonb NOT NULL,
    annotations      jsonb NOT NULL DEFAULT '[]'::jsonb,
    signals_snapshot jsonb NOT NULL,
    signals_version  text NOT NULL,
    skill_version    text NOT NULL,
    pinned           boolean NOT NULL DEFAULT false,
    run_id           uuid REFERENCES runs (id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS summaries_cache_key
    ON summaries (symbol, session_date, level, signals_version, skill_version);

CREATE INDEX IF NOT EXISTS summaries_recent ON summaries (symbol, session_date DESC);
CREATE INDEX IF NOT EXISTS summaries_pinned ON summaries (created_at DESC) WHERE pinned;

CREATE TABLE IF NOT EXISTS claims (
    id                uuid PRIMARY KEY,
    summary_id        uuid NOT NULL REFERENCES summaries (id) ON DELETE CASCADE,
    subject_symbol    text NOT NULL,
    mentioned_symbols text[] NOT NULL DEFAULT '{}',
    session_date      date NOT NULL,
    kind              text NOT NULL CHECK (kind IN ('observation', 'expectation', 'anomaly')),
    statement         text NOT NULL,
    attribution       text,
    target_date       date,
    resolved_by       uuid REFERENCES claims (id) ON DELETE SET NULL,
    resolution        text CHECK (resolution IN ('supported', 'contradicted', 'unresolved')),
    embedding         vector(1536),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT expectation_has_target CHECK (kind <> 'expectation' OR target_date IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS claims_subject_date ON claims (subject_symbol, session_date DESC);
CREATE INDEX IF NOT EXISTS claims_mentions ON claims USING gin (mentioned_symbols);
CREATE INDEX IF NOT EXISTS claims_open ON claims (subject_symbol, target_date) WHERE resolved_by IS NULL;
CREATE INDEX IF NOT EXISTS claims_embedding ON claims USING hnsw (embedding vector_cosine_ops);