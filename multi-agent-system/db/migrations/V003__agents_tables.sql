-- V003: agents.config and agents.state — static config and runtime state per agent.

CREATE TABLE IF NOT EXISTS agents.config (
    agent_id              VARCHAR(20)   PRIMARY KEY,
    display_name          VARCHAR(50)   NOT NULL,
    role                  TEXT          NOT NULL,
    time_horizon_min_days INTEGER,
    time_horizon_max_days INTEGER,
    default_llm_model     VARCHAR(60)   NOT NULL,
    max_portfolio_pct     NUMERIC(5,2)  NOT NULL DEFAULT 20.0,
    is_active             BOOLEAN       NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agents.state (
    agent_id            VARCHAR(20)   PRIMARY KEY REFERENCES agents.config(agent_id),
    -- idle | analyzing | proposing | waiting_critique | executing | error | paused
    status              VARCHAR(20)   NOT NULL DEFAULT 'idle',
    current_task        TEXT,
    last_heartbeat      TIMESTAMPTZ,
    last_proposal_at    TIMESTAMPTZ,
    last_error          TEXT,
    error_count_24h     INTEGER       NOT NULL DEFAULT 0,
    llm_cost_today_usd  NUMERIC(10,4) NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
