'use client'

import { useAtlasHealth } from '@/hooks/use-atlas-health'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

const RISK_BORDER: Record<string, string> = {
  GREEN: '#1D9E75',
  YELLOW: '#BA7517',
  RED: '#E24B4A',
  BLACK: '#444',
}

const RISK_COLOR: Record<string, string> = {
  GREEN: 'bg-green-500/15 text-green-400 border-green-500/40',
  YELLOW: 'bg-amber-500/15 text-amber-400 border-amber-500/40',
  RED: 'bg-red-500/15 text-red-400 border-red-500/40',
  BLACK: 'bg-white/5 text-white/40 border-white/20',
}

export function RiskModeCard() {
  const { data, isLoading, isError, error } = useAtlasHealth()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>Risk</CardTitle></CardHeader>
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

  const mode = data.risk_mode ?? 'BLACK'

  return (
    <Card style={{ borderLeft: `2px solid ${RISK_BORDER[mode] ?? '#666'}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Risk</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span
          className={`inline-block self-start text-base font-bold px-2 py-1 rounded tracking-widest uppercase border ${RISK_COLOR[mode] ?? 'bg-white/5 text-white/40 border-white/20'}`}
        >
          {mode}
        </span>
        <span className="font-mono text-xs text-white/40">
          NAV ${data.nav_usd != null ? data.nav_usd.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}
        </span>
      </CardContent>
    </Card>
  )
}
