'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type SystemStatus = Json200<'/system/status', 'get'>

export function useSystemStatus() {
  return useQuery<SystemStatus>({
    queryKey: ['system', 'status'],
    queryFn: () => fetcher<SystemStatus>('/system/status'),
    refetchInterval: 30_000,
  })
}
