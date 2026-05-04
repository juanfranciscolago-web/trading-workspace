'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type SystemMode = Json200<'/system/mode', 'get'>

export function useSystemMode() {
  return useQuery<SystemMode>({
    queryKey: ['system', 'mode'],
    queryFn: () => fetcher<SystemMode>('/system/mode'),
    refetchInterval: 60_000,
  })
}
