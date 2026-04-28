-- V010: ALTER trades.atlas_validations para el nuevo contrato de Sprint 2A.
--
-- Las columnas del Sprint 1 (atlas_decision, portfolio_beta_post, etc.) se
-- mantienen pero se marcan como DEPRECATED en los comentarios.
-- Se agregarán las nuevas columnas del contrato Sprint 2A.
-- Cleanup (DROP COLUMN de los deprecated) en Sprint 3+ cuando esté validado.

ALTER TABLE trades.atlas_validations
    ADD COLUMN IF NOT EXISTS approved              BOOLEAN,
    ADD COLUMN IF NOT EXISTS executed_size_pct     NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS original_size_pct     NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS reason                VARCHAR(80),
    ADD COLUMN IF NOT EXISTS atlas_version         VARCHAR(32),
    ADD COLUMN IF NOT EXISTS portfolio_snapshot_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS evaluation_time_ms    NUMERIC(10,3),
    ADD COLUMN IF NOT EXISTS checks_passed         TEXT[],
    ADD COLUMN IF NOT EXISTS checks_failed         TEXT[],
    ADD COLUMN IF NOT EXISTS metrics_snapshot      JSONB;

COMMENT ON COLUMN trades.atlas_validations.atlas_decision IS
    'DEPRECATED Sprint 2A — reemplazado por approved (bool). Mantener hasta Sprint 3.';
COMMENT ON COLUMN trades.atlas_validations.portfolio_beta_post IS
    'DEPRECATED Sprint 2A — ahora en metrics_snapshot["portfolio.beta_post"]. Mantener hasta Sprint 3.';
COMMENT ON COLUMN trades.atlas_validations.buying_power_used_pct IS
    'DEPRECATED Sprint 2A — ahora en metrics_snapshot["portfolio.buying_power_used_pct"]. Mantener hasta Sprint 3.';
COMMENT ON COLUMN trades.atlas_validations.vega_total_post IS
    'DEPRECATED Sprint 2A — ahora en metrics_snapshot["portfolio.vega_total_post"]. Mantener hasta Sprint 3.';

COMMENT ON COLUMN trades.atlas_validations.approved IS
    'True si ATLAS aprobó la ejecución (executed_size_pct > 0)';
COMMENT ON COLUMN trades.atlas_validations.executed_size_pct IS
    'Tamaño a ejecutar como % del portfolio (puede ser menor que original_size_pct)';
COMMENT ON COLUMN trades.atlas_validations.original_size_pct IS
    'Tamaño original propuesto como % del portfolio';
COMMENT ON COLUMN trades.atlas_validations.reason IS
    'Razón de la decisión — AtlasReason constant (formato category:detail)';
COMMENT ON COLUMN trades.atlas_validations.portfolio_snapshot_id IS
    'SHA-256 del portfolio snapshot usado en la validación — FK lógica a atlas.portfolio_snapshots';

CREATE INDEX IF NOT EXISTS idx_atlas_validations_approved
    ON trades.atlas_validations(approved)
    WHERE approved = FALSE;

CREATE INDEX IF NOT EXISTS idx_atlas_validations_snapshot_id
    ON trades.atlas_validations(portfolio_snapshot_id)
    WHERE portfolio_snapshot_id IS NOT NULL;
