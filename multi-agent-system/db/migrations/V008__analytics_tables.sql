-- V008: analytics.* — agent performance, calibration, LLM costs,
--        risk mode transitions, and agent trust scores.

-- ── agent_performance ─────────────────────────────────────────────────────────
-- Hypertable: computed metrics per agent per period.

CREATE TABLE IF NOT EXISTS analytics.agent_performance (
    id                    BIGSERIAL     NOT NULL,
    agent_id              VARCHAR(20)   NOT NULL,
    period_start          TIMESTAMPTZ   NOT NULL,
    period_end            TIMESTAMPTZ   NOT NULL,
    proposals_count       INTEGER       NOT NULL DEFAULT 0,
    approved_count        INTEGER       NOT NULL DEFAULT 0,
    executed_count        INTEGER       NOT NULL DEFAULT 0,
    win_count             INTEGER       NOT NULL DEFAULT 0,
    loss_count            INTEGER       NOT NULL DEFAULT 0,
    total_pl_usd          NUMERIC(14,2),
    avg_conviction_score  NUMERIC(5,2),
    calibration_brier     NUMERIC(8,6),
    sharpe_contribution   NUMERIC(8,4),
    llm_cost_usd          NUMERIC(10,4),
    PRIMARY KEY (id, period_end)
);

SELECT create_hypertable(
    'analytics.agent_performance', 'period_end',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_agent_perf_agent_time
    ON analytics.agent_performance(agent_id, period_end DESC);


-- ── calibration ───────────────────────────────────────────────────────────────
-- Tracks predicted vs actual outcomes for conviction score calibration (Brier score).

CREATE TABLE IF NOT EXISTS analytics.calibration (
    id              BIGSERIAL     PRIMARY KEY,
    agent_id        VARCHAR(20)   NOT NULL,
    correlation_id  UUID          NOT NULL,
    predicted_pop   INTEGER       NOT NULL CHECK (predicted_pop BETWEEN 0 AND 100),
    actual_outcome  VARCHAR(20)   NOT NULL,
    brier_score     NUMERIC(8,6),
    computed_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_calibration_correlation UNIQUE (correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_calibration_agent_time
    ON analytics.calibration(agent_id, computed_at DESC);


-- ── llm_costs ─────────────────────────────────────────────────────────────────
-- Hypertable: granular LLM cost tracking with caching breakdown.
-- cached_input_tokens is critical for validating the ClaudeRouter caching strategy.

CREATE TABLE IF NOT EXISTS analytics.llm_costs (
    id                   BIGSERIAL     NOT NULL,
    ts                   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    agent_id             VARCHAR(20),
    task_type            VARCHAR(50),
    model_used           VARCHAR(60)   NOT NULL,
    input_tokens         INTEGER       NOT NULL,
    cached_input_tokens  INTEGER       NOT NULL DEFAULT 0,
    output_tokens        INTEGER       NOT NULL,
    is_batch_api         BOOLEAN       NOT NULL DEFAULT false,
    -- low | standard | high | critical
    criticality          VARCHAR(20),
    cost_usd             NUMERIC(10,6) NOT NULL,
    correlation_id       UUID,
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable(
    'analytics.llm_costs', 'ts',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_llm_costs_agent_time
    ON analytics.llm_costs(agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_costs_model
    ON analytics.llm_costs(model_used, ts DESC);


-- ── risk_mode_transitions ─────────────────────────────────────────────────────
-- Audit log of every GREEN→YELLOW→RED→BLACK transition.
-- Essential for postmortem: "ATLAS estuvo en RED por 75 min porque drawdown -5.2%".

CREATE TABLE IF NOT EXISTS analytics.risk_mode_transitions (
    id                              BIGSERIAL    PRIMARY KEY,
    from_mode                       VARCHAR(10)  NOT NULL,
    to_mode                         VARCHAR(10)  NOT NULL,
    transitioned_at                 TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    duration_in_previous_mode_seconds INTEGER,
    trigger_reason                  TEXT         NOT NULL,
    triggering_event                JSONB,
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_transitions_time
    ON analytics.risk_mode_transitions(transitioned_at DESC);


-- ── agent_trust_scores ────────────────────────────────────────────────────────
-- Persistent cross-agent trust matrix: who agrees/disagrees with whom, and who's right.
-- Drives consensus weight and size modulation in the decision engine.

CREATE TABLE IF NOT EXISTS analytics.agent_trust_scores (
    id                     BIGSERIAL     PRIMARY KEY,
    from_agent             VARCHAR(20)   NOT NULL,
    to_agent               VARCHAR(20)   NOT NULL,
    -- NULL = general; non-null = context-specific (e.g. "macro_thesis", "csp_setup")
    context                VARCHAR(60),
    total_disagreements    INTEGER       NOT NULL DEFAULT 0,
    correct_disagreements  INTEGER       NOT NULL DEFAULT 0,
    current_trust_score    NUMERIC(5,4)  NOT NULL DEFAULT 0.5,
    last_updated           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_trust_from_to_context UNIQUE (from_agent, to_agent, context)
);

CREATE INDEX IF NOT EXISTS idx_trust_lookup
    ON analytics.agent_trust_scores(from_agent, to_agent);
