'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher } from '@/lib/api-client'
import { type ProposalDetail } from '@/hooks/use-proposals'

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * CritiqueMessage from agent.critiques (Sprint 4 B.4.2).
 * Mirrors CritiqueMessage in src/multi_agent/communication/schemas/critique.py.
 */
export interface Critique {
  message_id: string
  message_type: string
  timestamp: string
  agent_id: string
  schema_version: string
  correlation_id: string
  parent_message_id: string | null
  stance: 'AGREE' | 'AGREE_WITH_CONDITIONS' | 'DISAGREE' | 'NEUTRAL'
  argument: {
    summary: string
    evidence: { claim: string; data_source: string; value: string | number }[]
    concern: string
    data_that_would_change_my_mind: string
  }
  alternative_proposal: Record<string, unknown> | null
  veto_request: boolean
  contrarian_flag_raised: boolean
}

/**
 * DecisionMessage from agent.decisions (Sprint 4 B.4.3).
 * Mirrors DecisionMessage in src/multi_agent/communication/schemas/decision.py.
 */
export interface Decision {
  message_id: string
  message_type: string
  timestamp: string
  agent_id: string
  schema_version: string
  correlation_id: string
  parent_message_id: string | null
  outcome: 'APPROVED' | 'APPROVED_WITH_CONDITIONS' | 'BLOCKED' | 'DEFERRED' | 'REJECTED'
  consensus_state: {
    agree: string[]
    disagree: string[]
    neutral: string[]
    consensus_type: string
  }
  size_modulation: {
    original_size_pct: number
    approved_size_pct: number
    reduction_reason: string
  } | null
  conditions: string[]
  atlas_validation: { status: string }
  contrarian_flag_raised: boolean
}

/**
 * AtlasValidationMessage from agent.atlas_validations (Sprint 2A).
 * Mirrors AtlasValidationMessage in src/multi_agent/communication/schemas/atlas_validation.py.
 * Note: Decimal fields (executed_size, original_size) serialize as strings via
 * Pydantic model_dump(mode='json').
 */
export interface AtlasValidation {
  message_id: string
  message_type: string
  timestamp: string
  agent_id: string
  schema_version: string
  correlation_id: string
  parent_message_id: string | null
  atlas_version: string
  approved: boolean
  executed_size: string
  original_size: string
  reason: string
  risk_mode: 'GREEN' | 'YELLOW' | 'RED' | 'BLACK'
  checks_passed: string[]
  checks_failed: string[]
  metrics_snapshot: Record<string, unknown>
  portfolio_snapshot_id: string
  evaluation_time_ms: number
}

/**
 * Aggregated pipeline state from GET /trades/pipeline/{correlation_id}.
 * Mirrors PipelineStatusResponse in src/multi_agent/api/schemas/responses.py.
 */
export interface PipelineStatus {
  correlation_id: string
  status: string
  proposal: ProposalDetail
  critiques: Critique[]
  decision: Decision | null
  atlas_validation: AtlasValidation | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3000

/**
 * Statuses that mean the chain is fully done and polling should stop.
 * Per the schema comment in db/migrations/V005__trades_tables.sql.
 */
const TERMINAL_STATUSES = new Set(['atlas_validated', 'rejected', 'expired'])

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * Poll the pipeline aggregator endpoint while the chain is mid-flight.
 *
 * Polls every POLL_INTERVAL_MS until either:
 *   1. status reaches a terminal value (atlas_validated / rejected / expired), OR
 *   2. atlas_validation appears in the response (covers the B.4.5a gap where
 *      AtlasConsumer doesn't yet transition status from 'decided' to
 *      'atlas_validated' — once the atlas row is in the DB, the chain is
 *      effectively complete even if the status column hasn't been updated).
 *
 * Initial 404 (proposal doesn't exist) surfaces as an error in `error` — the
 * detail widget renders "proposal not found".
 *
 * Uses `enabled: Boolean(corrId)` to defer the first fetch until the URL
 * param is available.
 */
export function usePipeline(corrId: string | undefined) {
  return useQuery<PipelineStatus>({
    queryKey: ['pipeline', corrId],
    queryFn: () => fetcher<PipelineStatus>(`/trades/pipeline/${corrId}`),
    enabled: Boolean(corrId),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return POLL_INTERVAL_MS
      if (TERMINAL_STATUSES.has(data.status)) return false
      if (data.atlas_validation !== null) return false
      return POLL_INTERVAL_MS
    },
  })
}
