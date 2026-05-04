'use client'

import { useSystemStatus } from '@/hooks/use-system-status'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

const STATUS_DOT: Record<string, string> = {
  ok: 'bg-green-500',
  error: 'bg-red-500',
  unknown: 'bg-amber-500',
}

function aggregateStatus(s: { api: string; bus: string; atlas: string; db: string }): 'ok' | 'error' | 'unknown' {
  const values = [s.api, s.bus, s.atlas, s.db]
  if (values.some((v) => v === 'error')) return 'error'
  if (values.some((v) => v === 'unknown')) return 'unknown'
  return 'ok'
}

const BORDER_COLOR: Record<string, string> = {
  ok: '#1D9E75',
  error: '#E24B4A',
  unknown: '#BA7517',
}

const SUBSYSTEMS = ['api', 'bus', 'atlas', 'db'] as const

export function SystemStatusCard() {
  const { data, isLoading, isError, error } = useSystemStatus()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>System</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-8 w-24" /></CardContent>
      </Card>
    )
  }

  if (isError) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    )
  }

  if (!data) return null

  const agg = aggregateStatus(data)

  return (
    <Card style={{ borderLeft: `2px solid ${BORDER_COLOR[agg]}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">System</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${STATUS_DOT[agg] ?? 'bg-gray-500'}`} />
          <span className="font-mono text-lg uppercase">{agg}</span>
        </div>
        <div className="flex gap-3 font-mono text-xs text-white/40">
          {SUBSYSTEMS.map((key) => (
            <span key={key} className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[data[key]] ?? 'bg-amber-500'}`} />
              {key}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
