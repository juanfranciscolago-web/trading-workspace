'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type AlertsList = Json200<'/alerts', 'get'>

export function useAlerts(limit: number = 5) {
  return useQuery<AlertsList>({
    queryKey: ['alerts', { limit }],
    queryFn: () => fetcher<AlertsList>('/alerts', { limit }),
    refetchInterval: 30_000,
  })
}
