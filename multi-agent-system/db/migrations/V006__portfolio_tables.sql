-- V006: portfolio.snapshots and portfolio.positions.
-- snapshots: hypertable (append-only periodic snapshots, dashboard queries by recent time).
-- positions: regular table (current open positions, queries by is_open / source).

CREATE TABLE IF NOT EXISTS portfolio.snapshots (
    id                      BIGSERIAL     NOT NULL,
    snapshot_at             TIMESTAMPTZ   NOT NULL,
    total_nav_usd           NUMERIC(14,2) NOT NULL,
    cash_available_usd      NUMERIC(14,2),
    buying_power_used_pct   NUMERIC(5,2),
    portfolio_beta          NUMERIC(6,4),
    vega_total              NUMERIC(10,2),
    delta_total             NUMERIC(10,2),
    theta_total             NUMERIC(10,2),
    tech_concentration_pct  NUMERIC(5,2),
    drawdown_from_peak_pct  NUMERIC(8,4),
    -- GREEN | YELLOW | RED | BLACK
    risk_mode               VARCHAR(10)   NOT NULL DEFAULT 'GREEN',
    open_positions_count    INTEGER       NOT NULL DEFAULT 0,
    full_state              JSONB,
    PRIMARY KEY (id, snapshot_at)
);

SELECT create_hypertable(
    'portfolio.snapshots', 'snapshot_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);


CREATE TABLE IF NOT EXISTS portfolio.positions (
    position_id      VARCHAR(64)   PRIMARY KEY,
    source           VARCHAR(50)   NOT NULL,
    correlation_id   UUID,
    ticker           VARCHAR(32)   NOT NULL,
    asset_class      VARCHAR(20)   NOT NULL,
    strategy_type    VARCHAR(30),
    quantity         INTEGER       NOT NULL,
    entry_price      NUMERIC(14,6) NOT NULL,
    entry_timestamp  TIMESTAMPTZ   NOT NULL,
    current_price    NUMERIC(14,6),
    stop_price       NUMERIC(14,6),
    target_price     NUMERIC(14,6),
    unrealized_pnl   NUMERIC(14,2),
    delta            NUMERIC(10,4),
    vega             NUMERIC(10,4),
    theta            NUMERIC(10,4),
    is_open          BOOLEAN       NOT NULL DEFAULT true,
    closed_at        TIMESTAMPTZ,
    full_position    JSONB,
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_open
    ON portfolio.positions(is_open)
    WHERE is_open = true;
CREATE INDEX IF NOT EXISTS idx_positions_source
    ON portfolio.positions(source);
