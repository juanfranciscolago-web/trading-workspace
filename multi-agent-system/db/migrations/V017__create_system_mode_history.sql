-- V017: Add system schema and mode_history table for runtime mode toggles.
-- The application currently reads TRADING_MODE from env var only at startup.
-- This table records every mode change so the runtime mode can survive
-- restarts and the audit trail is preserved.

CREATE SCHEMA IF NOT EXISTS system;

CREATE TABLE IF NOT EXISTS system.mode_history (
    id                 BIGSERIAL    PRIMARY KEY,
    mode               VARCHAR(8)   NOT NULL CHECK (mode IN ('paper', 'real')),
    changed_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source             VARCHAR(16)  NOT NULL CHECK (source IN ('env', 'api', 'cli')),
    confirmation_token VARCHAR(128),
    actor              VARCHAR(64),
    notes              TEXT
);

CREATE INDEX IF NOT EXISTS mode_history_changed_at_desc_idx
    ON system.mode_history (changed_at DESC);

COMMENT ON TABLE system.mode_history IS
    'Audit trail of trading mode changes. Latest row by changed_at is the active mode.';
COMMENT ON COLUMN system.mode_history.source IS
    'env=set at startup from env var, api=POST /system/mode, cli=manual psql/script.';
COMMENT ON COLUMN system.mode_history.confirmation_token IS
    'For source=api with mode=real, the REAL_MODE_TOKEN that was provided. NULL otherwise.';
COMMENT ON COLUMN system.mode_history.actor IS
    'User identifier when known (postponed: requires auth, NULL for now).';
