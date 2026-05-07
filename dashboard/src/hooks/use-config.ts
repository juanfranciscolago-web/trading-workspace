'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher } from '@/lib/api-client'

export type ConfigData = Record<string, unknown>

export function useLimitsConfig() {
  return useQuery<ConfigData>({
    queryKey: ['config', 'limits'],
    queryFn: () => fetcher<ConfigData>('/config/limits'),
    refetchInterval: false,
    staleTime: Infinity,
  })
}

export function useBucketsConfig() {
  return useQuery<ConfigData>({
    queryKey: ['config', 'buckets'],
    queryFn: () => fetcher<ConfigData>('/config/buckets'),
    refetchInterval: false,
    staleTime: Infinity,
  })
}
