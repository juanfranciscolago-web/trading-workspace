'use client'

import { useSystemMode } from '@/hooks/use-system-mode'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

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

const BADGE_COLOR: Record<string, string> = {
  paper: 'bg-[#185FA5]/15 text-[#185FA5] border-[#185FA5]/40',
  real: 'bg-red-900/40 text-red-400 border-red-700/40',
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
    <Card style={{ borderLeft: `2px solid ${BORDER_COLOR[data.mode] ?? '#666'}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Mode</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span
          className={`inline-block self-start text-base font-bold px-2 py-1 rounded tracking-widest uppercase border ${BADGE_COLOR[data.mode] ?? 'bg-white/5 text-white/40 border-white/20'}`}
        >
          {data.mode}
        </span>
        <span className="font-mono text-xs text-white/40">{formatSince(data.since)}</span>
      </CardContent>
    </Card>
  )
}
