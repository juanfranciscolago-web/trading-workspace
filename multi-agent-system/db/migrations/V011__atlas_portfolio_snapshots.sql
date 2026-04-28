-- V011: Schema atlas + tabla atlas.portfolio_snapshots.
--
-- atlas.portfolio_snapshots guarda los estados del portfolio que ATLAS usó
-- para validar cada trade. La snapshot_id (SHA-256) es la PK y aparece en
-- trades.atlas_validations.portfolio_snapshot_id como FK lógica.
--
-- Separada de portfolio.snapshots (que es un hypertable de series temporales
-- periódicas del portfolio completo). Esta tabla es event-driven: un snapshot
-- por cada validación ATLAS que requirió un estado nuevo del portfolio.

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.portfolio_snapshots (
    snapshot_id           VARCHAR(64)    PRIMARY KEY,  -- SHA-256 hex
    snapshot_at           TIMESTAMPTZ    NOT NULL,
    nav_usd               NUMERIC(14,2)  NOT NULL,
    cash_usd              NUMERIC(14,2)  NOT NULL,
    buying_power_used_pct NUMERIC(5,2),
    portfolio_beta        NUMERIC(6,4),
    vega_total            NUMERIC(10,2),
    pnl_daily_usd         NUMERIC(14,2),
    drawdown_from_peak_pct NUMERIC(8,4),
    open_positions_count  INTEGER        NOT NULL DEFAULT 0,
    positions_json        JSONB          NOT NULL,      -- serialización completa de las posiciones
    created_at            TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_atlas_snapshots_at
    ON atlas.portfolio_snapshots(snapshot_at DESC);
