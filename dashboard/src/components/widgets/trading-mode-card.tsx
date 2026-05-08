'use client'

import { useSystemMode } from '@/hooks/use-system-mode'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ModeBadge } from '@/components/ui/mode-badge'

const SINCE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit',
  hour12: false,
})

function formatSince(iso: string): string {
  try {
    const d = new Date(iso)
    return `since ${SINCE_FORMATTER.format(d)} UTC`
  } catch {
    return 'since —'
  }
}

const BORDER_COLOR: Record<string, string> = {
  paper: '#185FA5',
  real: '#E24B4A',
}

export function TradingModeCard() {
  const { data, isLoading, isError, error } = useSystemMode()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>Mode</CardTitle></CardHeader>
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

  return (
    <Card style={{ borderLeft: `2px solid ${BORDER_COLOR[data.mode]}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Mode</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <ModeBadge mode={data.mode} className="self-start text-base" />
        <span className="font-mono text-xs text-white/40">{formatSince(data.since)}</span>
      </CardContent>
    </Card>
  )
}
