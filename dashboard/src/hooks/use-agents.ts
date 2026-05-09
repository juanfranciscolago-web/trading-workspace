'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetcher } from '@/lib/api-client'
import { API_BASE_URL } from '@/lib/env'

export interface Agent {
  agent_id: string
  display_name: string
  role: string
  time_horizon_min_days: number | null
  time_horizon_max_days: number | null
  default_llm_model: string
  max_portfolio_pct: string
  is_active: boolean
  status: string | null
  current_task: string | null
  last_heartbeat: string | null
  last_proposal_at: string | null
  last_error: string | null
  error_count_24h: number | null
  llm_cost_today_usd: string | null
}

export interface AgentsResponse {
  items: Agent[]
}

export interface ToggleAgentResponse {
  agent_id: string
  is_active: boolean
}

async function postToggle(agentId: string, isActive: boolean): Promise<ToggleAgentResponse> {
  const res = await fetch(`${API_BASE_URL}/agents/${encodeURIComponent(agentId)}/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  })
  if (!res.ok) {
    throw new Error(`Toggle failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<ToggleAgentResponse>
}

export function useAgents() {
  return useQuery<AgentsResponse>({
    queryKey: ['agents'],
    queryFn: () => fetcher<AgentsResponse>('/agents'),
    refetchInterval: 30_000,
  })
}

export function useToggleAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, isActive }: { agentId: string; isActive: boolean }) =>
      postToggle(agentId, isActive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}
