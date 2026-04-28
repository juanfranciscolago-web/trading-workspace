-- V013: Fix tech debt Sprint 1 — AtlasValidationRef PENDING → VALIDATED.
--
-- DecisionMessage.atlas_validation es un objeto Pydantic frozen (inmutable).
-- El "PENDING → VALIDATED" no puede actualizarse en el mensaje en memoria,
-- pero sí en la fila de trades.decisions en la DB.
--
-- Esta migración agrega atlas_validated_at a trades.decisions.
-- La columna se actualiza en Python por MessageRepository.update_decision_atlas_ref()
-- cuando se persiste el AtlasValidationMessage correspondiente.

ALTER TABLE trades.decisions
    ADD COLUMN IF NOT EXISTS atlas_validated_at TIMESTAMPTZ;

COMMENT ON COLUMN trades.decisions.atlas_validated_at IS
    'Timestamp de cuando ATLAS validó esta decisión. NULL = pendiente de validación ATLAS.';

CREATE INDEX IF NOT EXISTS idx_decisions_atlas_pending
    ON trades.decisions(atlas_validated_at)
    WHERE atlas_validated_at IS NULL;
