'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type CostsDaily = Json200<'/costs/daily', 'get'>

export function useCostsDaily() {
  return useQuery<CostsDaily>({
    queryKey: ['costs', 'daily'],
    queryFn: () => fetcher<CostsDaily>('/costs/daily'),
  })
}
