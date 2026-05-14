-- V018: market.iv_history — daily ATM IV per ticker for iv_rank computation.
-- ADR-005 D1: separate table from market.iv_surface; minimal scalar per (ticker, day).
-- Hypertable for forward time-series accumulation (no historical backfill per ADR-005 D9).

CREATE TABLE IF NOT EXISTS market.iv_history (
    ts                TIMESTAMPTZ   NOT NULL,
    ticker            VARCHAR(32)   NOT NULL,
    atm_iv            NUMERIC(8,6)  NOT NULL,
    underlying_close  NUMERIC(14,6),
    PRIMARY KEY (ts, ticker)
);

SELECT create_hypertable(
    'market.iv_history', 'ts',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_iv_history_ticker_time
    ON market.iv_history(ticker, ts DESC);

COMMENT ON TABLE market.iv_history IS
    'Daily ATM IV per ticker for iv_rank percentile computation. '
    'Forward accumulation only (ADR-005 D9). 1 row per (ticker, trading day). '
    'Populated by IvHistoryWorker at 21:15 UTC daily.';

COMMENT ON COLUMN market.iv_history.atm_iv IS
    'ATM implied volatility — avg(call.iv, put.iv) at strike closest to spot. '
    'See ADR-005 D3 for fallback logic when only one side is available.';

COMMENT ON COLUMN market.iv_history.underlying_close IS
    'Spot price at snapshot time, for context audit. Optional (NULL accepted). '
    'MAY become required Sprint 7+ if cross-table joins with market.ohlcv require this anchor.';
