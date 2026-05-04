'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type AtlasHealth = Json200<'/atlas/health', 'get'>

export function useAtlasHealth() {
  return useQuery<AtlasHealth>({
    queryKey: ['atlas', 'health'],
    queryFn: () => fetcher<AtlasHealth>('/atlas/health'),
    refetchInterval: 30_000,
  })
}
