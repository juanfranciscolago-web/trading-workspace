'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetcher, type Json200 } from '@/lib/api-client'

type SystemMode = Json200<'/system/mode', 'get'>

export interface ToggleModeRequest {
  mode: 'paper' | 'real'
  confirmation_token?: string
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

async function postModeChange(body: ToggleModeRequest): Promise<SystemMode> {
  const res = await fetch(`${API_BASE_URL}/system/mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const err = await res.json()
      if (err?.detail) detail = err.detail
    } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<SystemMode>
}

export function useSystemMode() {
  return useQuery<SystemMode>({
    queryKey: ['system', 'mode'],
    queryFn: () => fetcher<SystemMode>('/system/mode'),
    refetchInterval: 60_000,
  })
}

export function useToggleMode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: postModeChange,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system', 'mode'] })
    },
  })
}
