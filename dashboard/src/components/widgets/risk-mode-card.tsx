'use client'

import { useAtlasHealth } from '@/hooks/use-atlas-health'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { RiskBadge } from '@/components/ui/risk-badge'

const RISK_BORDER: Record<string, string> = {
  GREEN: '#1D9E75',
  YELLOW: '#BA7517',
  RED: '#E24B4A',
  BLACK: '#444',
}

const VALID_RISK_LEVELS = ['GREEN', 'YELLOW', 'RED', 'BLACK'] as const
type RiskLevel = typeof VALID_RISK_LEVELS[number]

function isValidRiskLevel(value: unknown): value is RiskLevel {
  return typeof value === 'string' && (VALID_RISK_LEVELS as readonly string[]).includes(value)
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
  if (!isValidRiskLevel(mode)) return null

  return (
    <Card style={{ borderLeft: `2px solid ${RISK_BORDER[mode]}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">Risk</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <RiskBadge level={mode} className="self-start text-base" />
        <span className="font-mono text-xs text-white/40">
          NAV ${data.nav_usd != null ? data.nav_usd.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}
        </span>
      </CardContent>
    </Card>
  )
}
