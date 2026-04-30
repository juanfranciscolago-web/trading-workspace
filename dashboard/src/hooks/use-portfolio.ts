'use client'

import { useQuery } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type PortfolioSnapshot = Json200<'/portfolio/snapshot', 'get'>

export function usePortfolioSnapshot() {
  return useQuery<PortfolioSnapshot>({
    queryKey: ['portfolio', 'snapshot'],
    queryFn: () => fetcher<PortfolioSnapshot>('/portfolio/snapshot'),
  })
}
