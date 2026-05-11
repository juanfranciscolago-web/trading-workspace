'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '@/lib/env'
import type { ProposalDetail } from '@/hooks/use-proposals'

/**
 * Response from POST /agents/athena/trigger.
 * Mirrors TriggerAthenaResponse in src/multi_agent/api/routes/agents.py.
 *
 * When ATHENA generates a proposal: proposal is populated, no_setup=false.
 * When ATHENA declines (Shape B): proposal is null, no_setup=true.
 */
export interface TriggerAthenaResponse {
  correlation_id: string
  proposal: ProposalDetail | null
  no_setup: boolean
}

async function postTriggerAthena(): Promise<TriggerAthenaResponse> {
  const res = await fetch(`${API_BASE_URL}/agents/athena/trigger`, {
    method: 'POST',
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const err = await res.json()
      if (err?.detail) detail = err.detail
    } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<TriggerAthenaResponse>
}

export function useTriggerAthena() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: postTriggerAthena,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
    },
  })
}
