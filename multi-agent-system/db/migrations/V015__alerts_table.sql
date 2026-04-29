-- V015: Alert notification history.
--
-- Stores every alert that passed through the AlertRouter — both sent and failed.
-- dedup_hit=TRUE means the event was suppressed by the dedup window and
-- no sink was called. retry_count/last_retry_at reserved for 2B.2.b retry queue.

CREATE SCHEMA IF NOT EXISTS alerts;

CREATE TABLE IF NOT EXISTS alerts.sent_alerts (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(64)  NOT NULL,
    severity        VARCHAR(16)  NOT NULL,
    title           VARCHAR(256) NOT NULL,
    dedup_key       VARCHAR(256),
    dedup_hit       BOOLEAN      NOT NULL DEFAULT FALSE,
    sink            VARCHAR(32)  NOT NULL DEFAULT 'telegram',
    sink_message_id VARCHAR(128),
    sent_at         TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error_msg       VARCHAR(512),
    payload         JSONB,
    source          VARCHAR(64),
    -- Optional: ID of the ATLAS/trade/decision event that originated this alert.
    -- Null for system alerts not tied to a specific trade cycle.
    correlation_id  UUID,
    -- Retry support (used by 2B.2.b retry queue — populated here for schema stability)
    retry_count     INTEGER      NOT NULL DEFAULT 0,
    last_retry_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sent_alerts_event_type
    ON alerts.sent_alerts(event_type);
CREATE INDEX IF NOT EXISTS idx_sent_alerts_created_at
    ON alerts.sent_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sent_alerts_severity
    ON alerts.sent_alerts(severity)
    WHERE dedup_hit = FALSE;
CREATE INDEX IF NOT EXISTS idx_sent_alerts_correlation_id
    ON alerts.sent_alerts(correlation_id)
    WHERE correlation_id IS NOT NULL;
