'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher } from '@/lib/api-client'

export interface AlertItem {
  id: string
  event_type?: string | null
  severity?: string | null
  title?: string | null
  dedup_key?: string | null
  dedup_hit?: boolean | null
  sink?: string | null
  sent_at?: string | null
  failed_at?: string | null
  error_msg?: string | null
  source?: string | null
  correlation_id?: string | null
  created_at?: string | null
}

export interface AlertsResponse {
  items: AlertItem[]
}

export function useAlerts(limit: number = 5) {
  return useQuery<AlertsResponse>({
    queryKey: ['alerts', { limit }],
    queryFn: () => fetcher<AlertsResponse>('/alerts', { limit }),
    refetchInterval: 30_000,
  })
}
