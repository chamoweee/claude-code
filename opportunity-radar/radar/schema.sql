-- Opportunity Radar history database.
-- All timestamps ending in _at are UTC ISO-8601. All *_date columns are
-- calendar dates in Australia/Sydney, because that is the day Chamk lives in.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- Run bookkeeping
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK (kind IN ('weekly', 'daily', 'seed', 'manual')),
    status       TEXT NOT NULL CHECK (status IN (
                     'running', 'ok', 'partial', 'failed', 'skipped', 'budget_halted')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    sydney_date  TEXT NOT NULL,
    git_sha      TEXT,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_kind_date ON runs (kind, sydney_date);

-- Every query issued, every source consulted, every error raised. This is the
-- "log every run" rule: if it is not in here, it did not happen.
CREATE TABLE IF NOT EXISTS run_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    at      TEXT NOT NULL,
    level   TEXT NOT NULL CHECK (level IN ('debug', 'info', 'warn', 'error')),
    event   TEXT NOT NULL,  -- 'query' | 'source' | 'fetch' | 'error' | 'email' | ...
    detail  TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events (run_id, id);

-- ---------------------------------------------------------------------------
-- Spend ledger. Checked BEFORE each API call, never only reported after.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS spend (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER REFERENCES runs (id) ON DELETE CASCADE,
    at                 TEXT NOT NULL,
    month              TEXT NOT NULL,  -- YYYY-MM in Australia/Sydney
    model              TEXT NOT NULL,
    purpose            TEXT,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    web_searches       INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL NOT NULL DEFAULT 0,
    cost_aud           REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_spend_month ON spend (month);

-- ---------------------------------------------------------------------------
-- Macro
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS macro_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    as_of_date      TEXT NOT NULL,
    metric          TEXT NOT NULL,  -- 'brent' | 'gold' | 'copper' | 'rba_cash_rate' | ...
    value           REAL,
    unit            TEXT,
    value_text      TEXT,           -- for things that are not a number, e.g. "hike expected"
    source_name     TEXT,
    source_url      TEXT,
    source_date     TEXT,
    source_strength TEXT CHECK (source_strength IN ('primary', 'reputable_media', 'weak')),
    note            TEXT,
    UNIQUE (as_of_date, metric)
);

-- ---------------------------------------------------------------------------
-- Themes (the tracked list) and their weekly status
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS themes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    description   TEXT,
    watch_for     TEXT,  -- what would move this theme's status
    status        TEXT NOT NULL CHECK (status IN ('NEW', 'RISING', 'STABLE', 'FADING', 'DEAD')),
    is_baseline   INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    created_date  TEXT NOT NULL,
    retired_date  TEXT
);

CREATE TABLE IF NOT EXISTS theme_updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    theme_id    INTEGER NOT NULL REFERENCES themes (id) ON DELETE CASCADE,
    run_id      INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    as_of_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('NEW', 'RISING', 'STABLE', 'FADING', 'DEAD')),
    prev_status TEXT,
    reason      TEXT NOT NULL,  -- one line, shown in the email table
    UNIQUE (theme_id, as_of_date)
);

-- ---------------------------------------------------------------------------
-- Opportunities. Note the two separate evidence columns: source rules require
-- "the platform makes money" to be kept apart from "individuals can
-- realistically make money".
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS opportunities (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                          TEXT NOT NULL UNIQUE,
    theme_id                      INTEGER REFERENCES themes (id) ON DELETE SET NULL,
    title                         TEXT NOT NULL,
    summary                       TEXT,
    who_earns                     TEXT,
    platform_revenue_evidence     TEXT,
    individual_earnings_evidence  TEXT,
    startup_cost_aud_min          REAL,
    startup_cost_aud_max          REAL,
    time_to_first_dollar_days     INTEGER,
    skills_required               TEXT,
    saturation                    TEXT,
    red_flags                     TEXT,
    au_eligibility                TEXT,
    status                        TEXT NOT NULL DEFAULT 'open'
                                      CHECK (status IN ('open', 'watching', 'discarded', 'acted')),
    first_seen_date               TEXT NOT NULL,
    last_seen_date                TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Evidence. Every number needs a source and a date. Nothing reaches the email
-- without a row in here.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    subject_type    TEXT NOT NULL CHECK (subject_type IN
                        ('theme', 'opportunity', 'macro', 'watchlist')),
    subject_id      INTEGER,
    claim           TEXT NOT NULL,
    number_value    TEXT,           -- kept as text: "~$2B run rate", "+38% y/y"
    source_name     TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    source_date     TEXT NOT NULL,
    source_strength TEXT NOT NULL CHECK (source_strength IN
                        ('primary', 'reputable_media', 'weak')),
    conflicts_with  INTEGER REFERENCES evidence (id) ON DELETE SET NULL,
    captured_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence (subject_type, subject_id);

-- ---------------------------------------------------------------------------
-- Scoring. Sub-scores come from the model with reasons; `total` is computed in
-- Python so the arithmetic is auditable and stable week to week.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scores (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id    INTEGER NOT NULL REFERENCES opportunities (id) ON DELETE CASCADE,
    run_id            INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    as_of_date        TEXT NOT NULL,
    evidence_strength INTEGER NOT NULL CHECK (evidence_strength BETWEEN 1 AND 10),
    personal_fit      INTEGER NOT NULL CHECK (personal_fit BETWEEN 1 AND 10),
    capital_fit       INTEGER NOT NULL CHECK (capital_fit BETWEEN 1 AND 10),
    hours_fit         INTEGER NOT NULL CHECK (hours_fit BETWEEN 1 AND 10),
    speed_to_dollar   INTEGER NOT NULL CHECK (speed_to_dollar BETWEEN 1 AND 10),
    risk              INTEGER NOT NULL CHECK (risk BETWEEN 1 AND 10),
    total             REAL NOT NULL,
    capped_reason     TEXT,  -- set when weak-only sourcing capped the total
    rationale         TEXT,
    UNIQUE (opportunity_id, as_of_date)
);

-- ---------------------------------------------------------------------------
-- Watchlist prices and the alerts they trigger
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS watchlist_quotes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    symbol     TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    close      REAL,
    prev_close REAL,
    pct_change REAL,
    currency   TEXT,
    source     TEXT,
    UNIQUE (symbol, as_of_date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    fired_at    TEXT NOT NULL,
    sydney_date TEXT NOT NULL,
    rule        TEXT NOT NULL,  -- 'watchlist_move' | 'commodity_move' | 'rate_decision' | ...
    subject     TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'notable', 'urgent')),
    headline    TEXT NOT NULL,
    detail      TEXT,
    source_url  TEXT,
    emailed     INTEGER NOT NULL DEFAULT 0,
    dedupe_key  TEXT NOT NULL UNIQUE  -- stops the same event emailing twice
);

-- ---------------------------------------------------------------------------
-- The weekly "top 3 actions", so next week can check whether they happened
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS actions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    as_of_date     TEXT NOT NULL,
    rank           INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
    title          TEXT NOT NULL,
    why            TEXT,
    est_minutes    INTEGER NOT NULL CHECK (est_minutes <= 180),
    opportunity_id INTEGER REFERENCES opportunities (id) ON DELETE SET NULL,
    outcome        TEXT NOT NULL DEFAULT 'pending'
                       CHECK (outcome IN ('pending', 'done', 'skipped', 'unknown')),
    UNIQUE (as_of_date, rank)
);

-- ---------------------------------------------------------------------------
-- Rendered reports, so a resend never needs the model again
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs (id) ON DELETE SET NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('weekly', 'daily_alert', 'error', 'budget')),
    sydney_date TEXT NOT NULL,
    subject     TEXT NOT NULL,
    path        TEXT,
    sent_at     TEXT,
    UNIQUE (kind, sydney_date)
);
