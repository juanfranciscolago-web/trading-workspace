-- V002: shared.trades_log — cross-system trade audit log (Eolo + multi-agent).
-- Source of truth for performance attribution between systems.

CREATE TABLE IF NOT EXISTS shared.trades_log (
    id              BIGSERIAL     PRIMARY KEY,
    execution_id    VARCHAR(64)   NOT NULL,
    source          VARCHAR(50)   NOT NULL,
    symbol          VARCHAR(32)   NOT NULL,
    asset_class     VARCHAR(20)   NOT NULL,
    option_type     VARCHAR(10),
    strike          NUMERIC(18,6),
    expiration      DATE,
    underlying      VARCHAR(32),
    direction       VARCHAR(10)   NOT NULL,
    quantity        INTEGER       NOT NULL,
    fill_price      NUMERIC(18,6),
    fill_timestamp  TIMESTAMPTZ,
    status          VARCHAR(20)   NOT NULL,
    venue           VARCHAR(32)   NOT NULL DEFAULT 'SCHWAB',
    commissions     NUMERIC(10,4) NOT NULL DEFAULT 0,
    slippage_pct    NUMERIC(8,4),
    strategy        VARCHAR(64),
    error_message   TEXT,
    metadata        JSONB         NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_trades_log_execution_id UNIQUE (execution_id),
    CONSTRAINT valid_source CHECK (source IN (
        'eolo_v1', 'eolo_v2_spx', 'eolo_crypto',
        'multi_agent_athena', 'multi_agent_apollo', 'multi_agent_hermes',
        'multi_agent_nyx', 'multi_agent_vesta',
        'human_via_eolo', 'human_direct'
    ))
);

CREATE INDEX IF NOT EXISTS idx_trades_log_source
    ON shared.trades_log(source);
CREATE INDEX IF NOT EXISTS idx_trades_log_symbol
    ON shared.trades_log(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_log_fill_timestamp
    ON shared.trades_log(fill_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_trades_log_strategy
    ON shared.trades_log(strategy);
