-- V012: trades.rejected_dlq — tabla de trades rechazados por ATLAS o caídos al DLQ del bus.
--
-- Dos fuentes de registros:
--   1. ATLAS rejection: trades con approved=False procesados por atlas_consumer.py
--   2. DLQ del bus: mensajes que agotaron reintentos en AgentMessageBus
--
-- Esta tabla es el punto de revisión humana: el operador ve aquí qué se bloqueó y por qué.

CREATE TABLE IF NOT EXISTS trades.rejected_dlq (
    id                BIGSERIAL    PRIMARY KEY,
    -- Fuente del rechazo
    source            VARCHAR(20)  NOT NULL,   -- 'atlas_rejection' | 'bus_dlq'
    -- Trade identifiers (nullable si vino del DLQ sin parseo)
    correlation_id    UUID,
    ticker            VARCHAR(32),
    proposing_agent   VARCHAR(20),
    -- Detalle del rechazo
    reason            VARCHAR(80),             -- AtlasReason o 'bus_dlq:<error_type>'
    original_channel  VARCHAR(80),             -- stream de Redis donde ocurrió (si aplica)
    dlq_entry_id      VARCHAR(80),             -- ID de entrada en el stream DLQ de Redis
    -- Payload completo para análisis
    payload           JSONB        NOT NULL,
    -- Metadata
    atlas_version     VARCHAR(32),
    processed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rejected_dlq_correlation
    ON trades.rejected_dlq(correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rejected_dlq_source
    ON trades.rejected_dlq(source, processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_rejected_dlq_reason
    ON trades.rejected_dlq(reason);
