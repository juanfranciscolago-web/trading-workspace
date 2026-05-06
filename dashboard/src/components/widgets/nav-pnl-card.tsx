'use client'

import { usePortfolioSnapshot } from '@/hooks/use-portfolio'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

function formatUsd(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function formatPct(n: number): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function pnlColor(pct: number): string {
  if (pct > 0) return 'text-green-400'
  if (pct < 0) return 'text-red-400'
  return 'text-white/60'
}

function pnlBorder(pct: number): string {
  if (pct > 0) return '#1D9E75'
  if (pct < 0) return '#E24B4A'
  return '#444'
}

export function NavPnLCard() {
  const { data, isLoading, isError, error } = usePortfolioSnapshot()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>NAV / P&L</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-8 w-32" /></CardContent>
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

  const dailyPct = data.pnl_daily_pct ?? 0
  const dailyUsd = data.pnl_daily_usd ?? 0

  return (
    <Card style={{ borderLeft: `2px solid ${pnlBorder(dailyPct)}` }}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-white/60 uppercase tracking-wide">NAV / P&L</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span className="font-mono text-2xl">${formatUsd(data.nav_usd ?? 0)}</span>
        <div className="flex items-baseline gap-2">
          <span className={`font-mono text-base ${pnlColor(dailyPct)}`}>
            {dailyUsd >= 0 ? '+' : ''}${formatUsd(Math.abs(dailyUsd))}
          </span>
          <span className={`font-mono text-sm ${pnlColor(dailyPct)}`}>
            ({formatPct(dailyPct)})
          </span>
        </div>
        <div className="font-mono text-xs text-white/40 flex gap-3">
          <span>D {formatPct(dailyPct)}</span>
          <span>W {formatPct(data.pnl_weekly_pct ?? 0)}</span>
          <span>M {formatPct(data.pnl_monthly_pct ?? 0)}</span>
        </div>
        <span className="font-mono text-xs text-white/40">
          dd {formatPct(data.drawdown_from_peak_pct ?? 0)}
        </span>
      </CardContent>
    </Card>
  )
}
