-- V005: trades.* — full lifecycle of a trade: proposal → critique → decision
--        → atlas_validation → execution → postmortem.
-- No FK between these tables (event sourcing via correlation_id).
-- trades.executions is a hypertable (append-only, queries by period).

CREATE TABLE IF NOT EXISTS trades.proposals (
    id                BIGSERIAL    PRIMARY KEY,
    correlation_id    UUID         NOT NULL,
    proposing_agent   VARCHAR(20)  NOT NULL,
    ticker            VARCHAR(32)  NOT NULL,
    asset_class       VARCHAR(20)  NOT NULL,
    strategy_type     VARCHAR(30)  NOT NULL,
    conviction_score  INTEGER      CHECK (conviction_score BETWEEN 0 AND 100),
    proposed_size_pct NUMERIC(5,2),
    proposed_size_usd NUMERIC(14,2),
    time_horizon_days INTEGER,
    -- pending | under_critique | decided | atlas_validated | executing | executed | rejected | expired
    status            VARCHAR(30)  NOT NULL DEFAULT 'pending',
    full_payload      JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_proposals_correlation UNIQUE (correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_proposals_agent_time
    ON trades.proposals(proposing_agent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_ticker
    ON trades.proposals(ticker);
CREATE INDEX IF NOT EXISTS idx_proposals_active_status
    ON trades.proposals(status)
    WHERE status NOT IN ('executed', 'rejected', 'expired');


CREATE TABLE IF NOT EXISTS trades.critiques (
    id              BIGSERIAL    PRIMARY KEY,
    correlation_id  UUID         NOT NULL,
    critique_agent  VARCHAR(20)  NOT NULL,
    -- AGREE | DISAGREE | NEUTRAL | ABSTAIN
    stance          VARCHAR(20)  NOT NULL,
    contrarian_flag BOOLEAN      NOT NULL DEFAULT false,
    summary         TEXT,
    full_payload    JSONB        NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_critiques_correlation_agent UNIQUE (correlation_id, critique_agent)
);

CREATE INDEX IF NOT EXISTS idx_critiques_correlation
    ON trades.critiques(correlation_id);


CREATE TABLE IF NOT EXISTS trades.decisions (
    id                BIGSERIAL    PRIMARY KEY,
    correlation_id    UUID         NOT NULL,
    -- APPROVED | REJECTED | APPROVED_WITH_CONDITIONS | NEEDS_MORE_DATA
    outcome           VARCHAR(30)  NOT NULL,
    consensus_type    VARCHAR(60),
    approved_size_pct NUMERIC(5,2),
    conditions        TEXT[]       NOT NULL DEFAULT '{}',
    full_payload      JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_decisions_correlation UNIQUE (correlation_id)
);


CREATE TABLE IF NOT EXISTS trades.atlas_validations (
    id                      BIGSERIAL    PRIMARY KEY,
    correlation_id          UUID         NOT NULL,
    -- APPROVED | REJECTED | APPROVED_WITH_CONDITIONS | BLOCKED_RISK_MODE
    atlas_decision          VARCHAR(30)  NOT NULL,
    -- GREEN | YELLOW | RED | BLACK
    risk_mode               VARCHAR(10)  NOT NULL,
    portfolio_beta_post     NUMERIC(6,4),
    buying_power_used_pct   NUMERIC(5,2),
    vega_total_post         NUMERIC(10,2),
    full_payload            JSONB        NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_atlas_validations_correlation UNIQUE (correlation_id)
);


CREATE TABLE IF NOT EXISTS trades.executions (
    id                BIGSERIAL    NOT NULL,
    correlation_id    UUID         NOT NULL,
    execution_id      VARCHAR(64),
    fill_status       VARCHAR(20)  NOT NULL,
    fill_price        NUMERIC(14,6),
    fill_quantity     INTEGER,
    fill_timestamp    TIMESTAMPTZ,
    venue             VARCHAR(32)  NOT NULL DEFAULT 'SCHWAB',
    slippage_pct      NUMERIC(8,4),
    execution_time_ms INTEGER,
    full_payload      JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
);

SELECT create_hypertable(
    'trades.executions', 'created_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- execution_id uniqueness: hypertable unique indexes require partition column.
-- UUIDs guarantee uniqueness at application level.
CREATE INDEX IF NOT EXISTS idx_executions_execution_id
    ON trades.executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_executions_correlation
    ON trades.executions(correlation_id);


CREATE TABLE IF NOT EXISTS trades.postmortems (
    id                     BIGSERIAL    PRIMARY KEY,
    correlation_id         UUID         NOT NULL,
    trade_owner            VARCHAR(20)  NOT NULL,
    -- WIN | LOSS | BREAK_EVEN | EXPIRED
    result                 VARCHAR(20)  NOT NULL,
    pl_usd                 NUMERIC(14,2),
    pl_pct_portfolio       NUMERIC(8,4),
    holding_period_days    INTEGER,
    exit_reason            TEXT,
    premise_validated      BOOLEAN,
    mechanism_worked       BOOLEAN,
    invalidation_triggered BOOLEAN,
    full_payload           JSONB        NOT NULL,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_postmortems_correlation UNIQUE (correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_postmortems_owner
    ON trades.postmortems(trade_owner);
CREATE INDEX IF NOT EXISTS idx_postmortems_result
    ON trades.postmortems(result);
