'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher } from '@/lib/api-client'

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Summary item from GET /trades/proposals.
 * Mirrors ProposalSummaryItem in src/multi_agent/api/schemas/responses.py.
 */
export interface Proposal {
  correlation_id: string
  proposing_agent: string
  ticker: string
  asset_class: string
  strategy_type: string
  conviction_score: number | null
  proposed_size_pct: number | null
  proposed_size_usd: number | null
  time_horizon_days: number | null
  status: string
  created_at: string
}

export interface ProposalsResponse {
  items: Proposal[]
  count: number
}

/**
 * Full ProposalMessage from GET /trades/proposals/{correlation_id}.
 * Nested objects (trade.structure, thesis, sizing, data_signature) are typed
 * loosely here — F.3.2 detail view will refine field-by-field as it consumes them.
 */
export interface ProposalDetail {
  message_id: string
  message_type: string
  timestamp: string
  agent_id: string
  schema_version: string
  correlation_id: string
  parent_message_id: string | null
  trade: {
    ticker: string
    asset_class: string
    strategy_type: string
    structure: Record<string, unknown>
  }
  thesis: Record<string, unknown>
  conviction_score: number
  sizing: Record<string, unknown>
  self_acknowledged_biases: string[]
  data_signature: Record<string, unknown>
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useProposals() {
  return useQuery<ProposalsResponse>({
    queryKey: ['proposals'],
    queryFn: () => fetcher<ProposalsResponse>('/trades/proposals'),
    refetchInterval: 30_000,
  })
}

export function useProposal(corrId: string | undefined) {
  return useQuery<ProposalDetail>({
    queryKey: ['proposals', corrId],
    queryFn: () => fetcher<ProposalDetail>(`/trades/proposals/${corrId}`),
    enabled: Boolean(corrId),
  })
}
