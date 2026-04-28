-- V007: market.ohlcv and market.iv_surface — time-series price data.
-- Both are hypertables (high-volume append-only, all queries are time-range lookups).

CREATE TABLE IF NOT EXISTS market.ohlcv (
    ts        TIMESTAMPTZ   NOT NULL,
    ticker    VARCHAR(32)   NOT NULL,
    -- 1m | 5m | 1h | 1d
    timeframe VARCHAR(5)    NOT NULL,
    open      NUMERIC(14,6) NOT NULL,
    high      NUMERIC(14,6) NOT NULL,
    low       NUMERIC(14,6) NOT NULL,
    close     NUMERIC(14,6) NOT NULL,
    volume    BIGINT,
    vwap      NUMERIC(14,6),
    PRIMARY KEY (ts, ticker, timeframe)
);

SELECT create_hypertable(
    'market.ohlcv', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Primary query pattern: WHERE ticker = X AND timeframe = Y AND ts > Z ORDER BY ts DESC
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_tf_time
    ON market.ohlcv(ticker, timeframe, ts DESC);


CREATE TABLE IF NOT EXISTS market.iv_surface (
    ts            TIMESTAMPTZ   NOT NULL,
    underlying    VARCHAR(32)   NOT NULL,
    expiration    DATE          NOT NULL,
    strike        NUMERIC(14,4) NOT NULL,
    -- CALL | PUT
    option_type   VARCHAR(4)    NOT NULL,
    iv            NUMERIC(8,6)  NOT NULL,
    delta         NUMERIC(8,6),
    gamma         NUMERIC(10,8),
    theta         NUMERIC(10,6),
    vega          NUMERIC(10,6),
    open_interest INTEGER,
    volume        INTEGER,
    PRIMARY KEY (ts, underlying, expiration, strike, option_type)
);

SELECT create_hypertable(
    'market.iv_surface', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_iv_surface_underlying_time
    ON market.iv_surface(underlying, ts DESC);
