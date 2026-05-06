'use client'

import { useAlerts } from '@/hooks/use-alerts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

const SEVERITY_DOT: Record<string, string> = {
  CRITICAL: 'bg-red-500',
  ERROR: 'bg-red-500',
  WARNING: 'bg-amber-500',
  INFO: 'bg-blue-500',
}

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso)
    const now = Date.now()
    const diffMs = now - d.getTime()
    const diffSec = Math.floor(diffMs / 1000)
    if (diffSec < 60) return `${diffSec}s ago`
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDay = Math.floor(diffHr / 24)
    return `${diffDay}d ago`
  } catch {
    return '—'
  }
}

function aggregateSeverityBorder(items: Array<{ severity?: string | null }>): string {
  if (items.some((it) => it.severity === 'CRITICAL' || it.severity === 'ERROR')) return '#E24B4A'
  if (items.some((it) => it.severity === 'WARNING')) return '#BA7517'
  return '#444'
}

export function RecentAlertsCard() {
  const { data, isLoading, isError, error } = useAlerts(5)

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>Alerts</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-20 w-full" /></CardContent>
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

  const items = data?.items ?? []
  const borderColor = aggregateSeverityBorder(items)

  return (
    <Card style={{ borderLeft: `2px solid ${borderColor}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Alerts</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <span className="text-sm text-white/40">No recent alerts</span>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-2 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${SEVERITY_DOT[item.severity ?? 'INFO'] ?? 'bg-gray-500'}`} />
                <span className="flex-1 truncate text-white/80">{item.title ?? '(no title)'}</span>
                <span className="font-mono text-white/40 shrink-0">{formatRelative(item.created_at ?? '')}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
