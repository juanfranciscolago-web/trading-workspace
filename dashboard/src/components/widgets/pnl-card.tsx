'use client'

import { usePortfolioSnapshot } from '@/hooks/use-portfolio'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function pnlColor(value: number): string {
  if (value > 0) return 'text-green-500'
  if (value < 0) return 'text-red-500'
  return 'text-muted-foreground'
}

function formatPnl(usdValue: number, pct: number): string {
  const sign = usdValue > 0 ? '+' : ''
  const pctSign = pct > 0 ? '+' : ''
  return `${sign}${usd.format(usdValue)} (${pctSign}${pct.toFixed(2)}%)`
}

export function PnLCard() {
  const { data, isLoading, isError, error } = usePortfolioSnapshot()

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>NAV</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-10 w-40" />
          <Skeleton className="h-6 w-28" />
        </CardContent>
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
    <Card>
      <CardHeader>
        <CardTitle>NAV</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span className="font-mono text-4xl font-semibold">
          {usd.format(data.nav_usd)}
        </span>
        <span className={`font-mono text-sm ${pnlColor(data.pnl_daily_usd)}`}>
          {formatPnl(data.pnl_daily_usd, data.pnl_daily_pct)}
        </span>
      </CardContent>
    </Card>
  )
}
