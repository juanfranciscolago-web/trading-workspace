-- V004: messages.agent_messages — append-only audit log of every Redis stream message.
-- Hypertable partitioned by 7-day chunks (append-only, queries always by recent time).

CREATE TABLE IF NOT EXISTS messages.agent_messages (
    id              BIGSERIAL    NOT NULL,
    message_id      UUID         NOT NULL,
    message_type    VARCHAR(30)  NOT NULL,
    correlation_id  UUID         NOT NULL,
    agent_id        VARCHAR(20)  NOT NULL,
    channel         VARCHAR(60)  NOT NULL,
    payload         JSONB        NOT NULL,
    redis_entry_id  VARCHAR(30),
    received_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, received_at)
);

SELECT create_hypertable(
    'messages.agent_messages', 'received_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Unique index on hypertables must include the partition column (TimescaleDB constraint).
-- UUIDs are globally unique by construction; a regular index is sufficient here.
CREATE INDEX IF NOT EXISTS idx_agent_messages_message_id
    ON messages.agent_messages(message_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_correlation
    ON messages.agent_messages(correlation_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_type_time
    ON messages.agent_messages(message_type, received_at DESC);
